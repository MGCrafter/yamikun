"""Web-Admin-Panel für den Bot (Sammelkarten, Spiele, Channel).

- Läuft als aiohttp-Server IM Bot-Prozess (gleiche SQLite-Verbindung, kein
  zweiter Schreiber, Zugriff auf den Bot-Cache für Rechte-Prüfungen).
- Login via Discord-OAuth2 (Scope `identify`). Zugriff nur, wenn der eingeloggte
  User auf dem jeweiligen Server die Berechtigung "Server verwalten"
  (manage_guild) hat.
- Karten-Bilder werden hochgeladen, lokal unter static/cards/<guild>/ gespeichert
  und unter WEB_BASE_URL/static/... ausgeliefert (damit Discord sie laden kann).

Aktiviert über die Umgebungsvariable WEB_ENABLED=1. Benötigt zusätzlich:
  WEB_BASE_URL, OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET
Optional: WEB_HOST (Standard 0.0.0.0), WEB_PORT (Standard 8080).
"""

from __future__ import annotations

import html
import logging
import os
import secrets
import time
import urllib.parse
from pathlib import Path

import aiohttp
import discord
from aiohttp import web
from discord.ext import commands

from cogs.gamecards import RARITIES, RARITY_ORDER, _slug

logger = logging.getLogger("oaken-tower-bot")

API_BASE = "https://discord.com/api"
SCOPE = "identify"
SESSION_COOKIE = "ot_session"
STATE_COOKIE = "ot_oauth_state"
SESSION_TTL = 60 * 60 * 8  # 8 Stunden
MAX_UPLOAD = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Hochgeladene Karten-Bilder. Über DATA_DIR auf einen persistenten Ordner
# umlenkbar (z.B. /data in Containern). Lokal: aktuelles Verzeichnis.
STATIC_DIR = Path(os.environ.get("DATA_DIR", ".")) / "static"


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


class WebPanelCog(commands.Cog):
    """Startet/stoppt den Admin-Webserver mit dem Bot."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]
        self.enabled = os.environ.get("WEB_ENABLED") == "1"
        self.base_url = os.environ.get("WEB_BASE_URL", "").rstrip("/")
        self.client_id = os.environ.get("OAUTH_CLIENT_ID", "")
        self.client_secret = os.environ.get("OAUTH_CLIENT_SECRET", "")
        self.host = os.environ.get("WEB_HOST", "0.0.0.0")
        self.port = int(os.environ.get("WEB_PORT", "8080"))
        self.redirect_uri = f"{self.base_url}/callback"
        self.secure_cookies = self.base_url.startswith("https://")

        self._runner: web.AppRunner | None = None
        self._http: aiohttp.ClientSession | None = None
        # token -> {"user_id", "username", "guilds": {gid: name}, "csrf", "exp"}
        self._sessions: dict[str, dict] = {}

    # --- Lifecycle ------------------------------------------------------------

    async def cog_load(self) -> None:
        if not self.enabled:
            logger.info("Webpanel deaktiviert (WEB_ENABLED != 1).")
            return
        missing = [
            n for n, v in (
                ("WEB_BASE_URL", self.base_url),
                ("OAUTH_CLIENT_ID", self.client_id),
                ("OAUTH_CLIENT_SECRET", self.client_secret),
            ) if not v
        ]
        if missing:
            logger.warning("Webpanel nicht gestartet — fehlende Variablen: %s", ", ".join(missing))
            return

        STATIC_DIR.mkdir(parents=True, exist_ok=True)
        (STATIC_DIR / "cards").mkdir(exist_ok=True)
        self._http = aiohttp.ClientSession()

        app = web.Application(client_max_size=MAX_UPLOAD)
        app.add_routes([
            web.get("/", self.h_index),
            web.get("/login", self.h_login),
            web.get("/callback", self.h_callback),
            web.get("/logout", self.h_logout),
            web.get("/g/{gid}/cards", self.h_cards),
            web.post("/g/{gid}/cards/add", self.h_cards_add),
            web.post("/g/{gid}/cards/delete", self.h_cards_delete),
            web.get("/g/{gid}/games", self.h_games),
            web.post("/g/{gid}/games/add", self.h_games_add),
            web.post("/g/{gid}/games/remove", self.h_games_remove),
            web.post("/g/{gid}/channel", self.h_set_channel),
        ])
        app.router.add_static("/static/", path=str(STATIC_DIR))

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        logger.info("Webpanel läuft auf %s:%s (öffentlich: %s)", self.host, self.port, self.base_url)

    async def cog_unload(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
        if self._http is not None:
            await self._http.close()

    # --- Auth-Helper ----------------------------------------------------------

    def _new_session(self, user_id: int, username: str, guilds: dict[int, str]) -> str:
        token = secrets.token_urlsafe(32)
        self._sessions[token] = {
            "user_id": user_id,
            "username": username,
            "guilds": guilds,
            "csrf": secrets.token_urlsafe(24),
            "exp": time.time() + SESSION_TTL,
        }
        return token

    def _session(self, request: web.Request) -> dict | None:
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            return None
        sess = self._sessions.get(token)
        if not sess:
            return None
        if sess["exp"] < time.time():
            self._sessions.pop(token, None)
            return None
        return sess

    def _require(self, request: web.Request) -> dict:
        sess = self._session(request)
        if sess is None:
            raise web.HTTPFound("/login")
        return sess

    def _require_guild(self, request: web.Request) -> tuple[dict, int]:
        sess = self._require(request)
        try:
            gid = int(request.match_info["gid"])
        except (KeyError, ValueError):
            raise web.HTTPBadRequest(text="Ungültige Guild-ID")
        if gid not in sess["guilds"]:
            raise web.HTTPForbidden(text="Keine Berechtigung für diesen Server.")
        return sess, gid

    def _check_csrf(self, sess: dict, data) -> None:
        if data.get("csrf") != sess["csrf"]:
            raise web.HTTPForbidden(text="Ungültiges CSRF-Token. Seite neu laden.")

    async def _admin_guilds(self, user_id: int) -> dict[int, str]:
        """Server, auf denen der Bot ist UND der User manage_guild hat."""
        result: dict[int, str] = {}
        for guild in self.bot.guilds:
            try:
                member = guild.get_member(user_id) or await guild.fetch_member(user_id)
            except (discord.NotFound, discord.HTTPException):
                continue
            if member.guild_permissions.manage_guild or guild.owner_id == user_id:
                result[guild.id] = guild.name
        return result

    # --- OAuth2 ---------------------------------------------------------------

    async def h_login(self, request: web.Request) -> web.StreamResponse:
        state = secrets.token_urlsafe(16)
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "state": state,
            "prompt": "consent",
        }
        url = f"{API_BASE}/oauth2/authorize?" + urllib.parse.urlencode(params)
        resp = web.HTTPFound(url)
        resp.set_cookie(
            STATE_COOKIE, state, max_age=600, httponly=True,
            secure=self.secure_cookies, samesite="Lax",
        )
        return resp

    async def h_callback(self, request: web.Request) -> web.StreamResponse:
        code = request.query.get("code")
        state = request.query.get("state")
        if not code or state != request.cookies.get(STATE_COOKIE):
            return web.HTTPBadRequest(text="Login fehlgeschlagen (ungültiger State).")
        assert self._http is not None
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
        }
        async with self._http.post(
            f"{API_BASE}/oauth2/token", data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as r:
            if r.status != 200:
                return web.HTTPBadGateway(text="Token-Tausch mit Discord fehlgeschlagen.")
            token = (await r.json())["access_token"]
        async with self._http.get(
            f"{API_BASE}/users/@me", headers={"Authorization": f"Bearer {token}"}
        ) as r:
            if r.status != 200:
                return web.HTTPBadGateway(text="Konnte Discord-Profil nicht laden.")
            user = await r.json()

        user_id = int(user["id"])
        guilds = await self._admin_guilds(user_id)
        if not guilds:
            return web.Response(
                text=self._page_simple(
                    "Kein Zugriff",
                    "Du hast auf keinem Server, auf dem dieser Bot ist, die Berechtigung "
                    "<b>Server verwalten</b>. Zugriff verweigert.",
                ),
                content_type="text/html",
            )
        sess_token = self._new_session(user_id, user.get("global_name") or user["username"], guilds)
        resp = web.HTTPFound("/")
        resp.del_cookie(STATE_COOKIE)
        resp.set_cookie(
            SESSION_COOKIE, sess_token, max_age=SESSION_TTL, httponly=True,
            secure=self.secure_cookies, samesite="Lax",
        )
        return resp

    async def h_logout(self, request: web.Request) -> web.StreamResponse:
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            self._sessions.pop(token, None)
        resp = web.HTTPFound("/login")
        resp.del_cookie(SESSION_COOKIE)
        return resp

    # --- Seiten ---------------------------------------------------------------

    async def h_index(self, request: web.Request) -> web.StreamResponse:
        sess = self._require(request)
        guilds = sess["guilds"]
        if len(guilds) == 1:
            gid = next(iter(guilds))
            raise web.HTTPFound(f"/g/{gid}/cards")
        items = "".join(
            f'<li><a href="/g/{gid}/cards">{_esc(name)}</a></li>' for gid, name in guilds.items()
        )
        body = f"<h2>Server wählen</h2><ul class='guildlist'>{items}</ul>"
        return self._html(sess, None, body)

    async def h_cards(self, request: web.Request) -> web.StreamResponse:
        sess, gid = self._require_guild(request)
        cards = self.db.list_custom_cards(gid)  # (cid, name, rarity, url, game)
        games = self.db.list_reward_games(gid)

        rarity_opts = "".join(
            f'<option value="{r}">{RARITIES[r]["emoji"]} {RARITIES[r]["label"]}</option>'
            for r in RARITIES
        )
        game_datalist = "".join(f'<option value="{_esc(g)}">' for g in games)

        by_rar: dict[str, list[tuple]] = {}
        for cid, name, rarity, url, game in cards:
            by_rar.setdefault(rarity, []).append((cid, name, url, game))
        rows = []
        for r in RARITY_ORDER:
            for cid, name, url, game in by_rar.get(r, []):
                thumb = (
                    f'<img src="{_esc(url)}" class="thumb" alt="">' if url else '<span class="noimg">—</span>'
                )
                rows.append(
                    f"<tr><td>{thumb}</td><td>{_esc(name)}</td>"
                    f"<td>{RARITIES[r]['emoji']} {RARITIES[r]['label']}</td>"
                    f"<td>{_esc(game or '—')}</td>"
                    f"<td><form method='post' action='/g/{gid}/cards/delete' "
                    f"onsubmit=\"return confirm('Karte wirklich löschen?')\">"
                    f"<input type='hidden' name='csrf' value='{sess['csrf']}'>"
                    f"<input type='hidden' name='card_id' value='{_esc(cid)}'>"
                    f"<button class='danger'>Löschen</button></form></td></tr>"
                )
        table = (
            "<table><thead><tr><th>Bild</th><th>Name</th><th>Seltenheit</th>"
            "<th>Spiel</th><th></th></tr></thead><tbody>"
            + ("".join(rows) or "<tr><td colspan='5'><i>Noch keine Karten.</i></td></tr>")
            + "</tbody></table>"
        )

        form = f"""
        <h3>Neue Karte hochladen</h3>
        <form method="post" action="/g/{gid}/cards/add" enctype="multipart/form-data" class="card-form">
          <input type="hidden" name="csrf" value="{sess['csrf']}">
          <label>Spiel <input name="game" list="games" required placeholder="z.B. Lost Ark"></label>
          <datalist id="games">{game_datalist}</datalist>
          <label>Name <input name="name" required maxlength="100"></label>
          <label>Seltenheit <select name="rarity">{rarity_opts}</select></label>
          <label>Bild <input type="file" name="image" accept="image/*" required></label>
          <button class="primary">Karte anlegen</button>
        </form>
        """
        body = f"<h2>Sammelkarten</h2>{form}<h3>Vorhandene Karten ({len(cards)})</h3>{table}"
        return self._html(sess, gid, body, active="cards")

    async def h_cards_add(self, request: web.Request) -> web.StreamResponse:
        sess, gid = self._require_guild(request)
        data = await request.post()
        self._check_csrf(sess, data)
        game = str(data.get("game", "")).strip()
        name = str(data.get("name", "")).strip()
        rarity = str(data.get("rarity", "common"))
        field = data.get("image")
        if not game or not name or rarity not in RARITIES:
            return web.HTTPBadRequest(text="Spiel, Name und gültige Seltenheit sind Pflicht.")
        if not isinstance(field, web.FileField):
            return web.HTTPBadRequest(text="Kein Bild hochgeladen.")
        ext = Path(field.filename or "").suffix.lower()
        if ext not in ALLOWED_EXT:
            return web.HTTPBadRequest(text=f"Dateityp nicht erlaubt ({', '.join(sorted(ALLOWED_EXT))}).")
        card_id = _slug(game, name)
        if card_id is None:
            return web.HTTPBadRequest(text="Ungültiger Name (mind. ein Buchstabe/Ziffer).")

        guild_dir = STATIC_DIR / "cards" / str(gid)
        guild_dir.mkdir(parents=True, exist_ok=True)
        # Alte Bilder dieser Karte (andere Endung) entfernen.
        for old in guild_dir.glob(f"{card_id}.*"):
            old.unlink(missing_ok=True)
        dest = guild_dir / f"{card_id}{ext}"
        content = field.file.read()
        dest.write_bytes(content)

        url = f"{self.base_url}/static/cards/{gid}/{card_id}{ext}"
        self.db.add_custom_card(gid, card_id, name, rarity, url, game)
        raise web.HTTPFound(f"/g/{gid}/cards")

    async def h_cards_delete(self, request: web.Request) -> web.StreamResponse:
        sess, gid = self._require_guild(request)
        data = await request.post()
        self._check_csrf(sess, data)
        card_id = str(data.get("card_id", ""))
        if card_id:
            self.db.remove_custom_card(gid, card_id)
            for old in (STATIC_DIR / "cards" / str(gid)).glob(f"{card_id}.*"):
                old.unlink(missing_ok=True)
        raise web.HTTPFound(f"/g/{gid}/cards")

    async def h_games(self, request: web.Request) -> web.StreamResponse:
        sess, gid = self._require_guild(request)
        games = self.db.list_reward_games(gid)
        guild = self.bot.get_guild(gid)
        chan_id = self.db.get_card_channel(gid)

        game_rows = "".join(
            f"<tr><td>{_esc(g)}</td><td><form method='post' action='/g/{gid}/games/remove'>"
            f"<input type='hidden' name='csrf' value='{sess['csrf']}'>"
            f"<input type='hidden' name='game' value='{_esc(g)}'>"
            f"<button class='danger'>Entfernen</button></form></td></tr>"
            for g in games
        ) or "<tr><td colspan='2'><i>Keine Spiele eingetragen.</i></td></tr>"

        chan_opts = ['<option value="">— DMs (kein Channel) —</option>']
        if guild is not None:
            for ch in guild.text_channels:
                sel = " selected" if chan_id == ch.id else ""
                chan_opts.append(f'<option value="{ch.id}"{sel}>#{_esc(ch.name)}</option>')

        body = f"""
        <h2>Belohnungs-Spiele</h2>
        <form method="post" action="/g/{gid}/games/add" class="inline-form">
          <input type="hidden" name="csrf" value="{sess['csrf']}">
          <input name="game" required placeholder="Exakter Spielname (wie in Discord)">
          <button class="primary">Hinzufügen</button>
        </form>
        <table><thead><tr><th>Spiel</th><th></th></tr></thead><tbody>{game_rows}</tbody></table>

        <h2>Karten-Drop-Channel</h2>
        <form method="post" action="/g/{gid}/channel" class="inline-form">
          <input type="hidden" name="csrf" value="{sess['csrf']}">
          <select name="channel_id">{''.join(chan_opts)}</select>
          <button class="primary">Speichern</button>
        </form>
        """
        return self._html(sess, gid, body, active="games")

    async def h_games_add(self, request: web.Request) -> web.StreamResponse:
        sess, gid = self._require_guild(request)
        data = await request.post()
        self._check_csrf(sess, data)
        game = str(data.get("game", "")).strip()
        if game:
            self.db.add_reward_game(gid, game)
        raise web.HTTPFound(f"/g/{gid}/games")

    async def h_games_remove(self, request: web.Request) -> web.StreamResponse:
        sess, gid = self._require_guild(request)
        data = await request.post()
        self._check_csrf(sess, data)
        game = str(data.get("game", "")).strip()
        if game:
            self.db.remove_reward_game(gid, game)
        raise web.HTTPFound(f"/g/{gid}/games")

    async def h_set_channel(self, request: web.Request) -> web.StreamResponse:
        sess, gid = self._require_guild(request)
        data = await request.post()
        self._check_csrf(sess, data)
        raw = str(data.get("channel_id", "")).strip()
        self.db.set_card_channel(gid, int(raw) if raw.isdigit() else None)
        raise web.HTTPFound(f"/g/{gid}/games")

    # --- HTML-Rendering -------------------------------------------------------

    def _html(self, sess: dict, gid: int | None, body: str, active: str = "") -> web.Response:
        nav = ""
        if gid is not None:
            def cls(name: str) -> str:
                return ' class="active"' if name == active else ""
            nav = (
                f'<a href="/g/{gid}/cards"{cls("cards")}>Karten</a>'
                f'<a href="/g/{gid}/games"{cls("games")}>Spiele &amp; Channel</a>'
            )
        page = f"""<!doctype html><html lang="de"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bot-Adminpanel</title><style>{CSS}</style></head>
<body><header><div class="brand">🃏 Bot-Adminpanel</div><nav>{nav}</nav>
<div class="user">{_esc(sess['username'])} · <a href="/logout">Logout</a></div></header>
<main>{body}</main></body></html>"""
        return web.Response(text=page, content_type="text/html")

    def _page_simple(self, title: str, message: str) -> str:
        return f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<title>{_esc(title)}</title><style>{CSS}</style></head><body><main>
<h2>{_esc(title)}</h2><p>{message}</p><p><a href="/login">Erneut anmelden</a></p>
</main></body></html>"""


CSS = """
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,Segoe UI,Roboto,sans-serif;background:#1a1b1e;color:#e6e6e6}
header{display:flex;align-items:center;gap:1.5rem;padding:.8rem 1.4rem;background:#26272b;border-bottom:1px solid #3a3b40}
.brand{font-weight:700}
nav{display:flex;gap:1rem;flex:1}
nav a{color:#b9bbbe;text-decoration:none;padding:.3rem .2rem}
nav a.active,nav a:hover{color:#fff;border-bottom:2px solid #5865F2}
.user{color:#b9bbbe;font-size:.9rem}
.user a{color:#5865F2}
main{max-width:900px;margin:1.5rem auto;padding:0 1.2rem}
h2{margin-top:0}
h3{margin-top:1.6rem}
table{width:100%;border-collapse:collapse;margin-top:.6rem;background:#26272b;border-radius:8px;overflow:hidden}
th,td{padding:.55rem .7rem;text-align:left;border-bottom:1px solid #34353a;vertical-align:middle}
th{background:#2f3035;font-size:.85rem;color:#b9bbbe}
.thumb{width:46px;height:46px;object-fit:cover;border-radius:6px}
.noimg{color:#666}
form.card-form{display:grid;gap:.7rem;max-width:420px;background:#26272b;padding:1rem;border-radius:8px}
.card-form label{display:flex;flex-direction:column;gap:.25rem;font-size:.9rem;color:#b9bbbe}
.inline-form{display:flex;gap:.5rem;margin:.6rem 0}
input,select{padding:.5rem;border:1px solid #3a3b40;border-radius:6px;background:#1f2023;color:#e6e6e6}
input[type=file]{padding:.35rem}
button{padding:.5rem .9rem;border:0;border-radius:6px;cursor:pointer;font-weight:600}
button.primary{background:#5865F2;color:#fff}
button.danger{background:#3a2326;color:#f08a8a}
button:hover{filter:brightness(1.12)}
.guildlist{list-style:none;padding:0}
.guildlist a{color:#5865F2;font-size:1.1rem}
"""


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WebPanelCog(bot))

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
MAX_UPLOAD = 25 * 1024 * 1024  # 25 MB
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Hochgeladene Karten-Bilder. Über DATA_DIR auf einen persistenten Ordner
# umlenkbar (z.B. /data in Containern). Lokal: aktuelles Verzeichnis.
STATIC_DIR = Path(os.environ.get("DATA_DIR", ".")) / "static"
# Mitgelieferte Design-Assets (Logo etc.) — liegen im Repo, immer verfügbar.
ASSETS_DIR = PROJECT_ROOT / "webassets"


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _color(rarity: str) -> str:
    """Seltenheits-Farbe als #RRGGBB für CSS."""
    return f"#{RARITIES.get(rarity, RARITIES['common'])['color']:06X}"


# Schlanke Line-Icons (Lucide-Stil) statt Emojis — erben die Farbe via currentColor.
_ICON_PATHS = {
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/>'
            '<rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "layers": '<path d="M12 2 2 7l10 5 10-5-10-5Z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/>',
    "gamepad": '<rect x="2" y="6" width="20" height="12" rx="5"/><line x1="6" y1="12" x2="10" y2="12"/>'
               '<line x1="8" y1="10" x2="8" y2="14"/><circle cx="15" cy="13" r="1"/><circle cx="18" cy="11" r="1"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
             '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "box": '<path d="M21 8v8a2 2 0 0 1-1 1.73l-7 4a2 2 0 0 1-2 0l-7-4A2 2 0 0 1 3 16V8a2 2 0 0 1 1-1.73l7-4'
           'a2 2 0 0 1 2 0l7 4A2 2 0 0 1 21 8Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
    "hash": '<line x1="4" y1="9" x2="20" y2="9"/><line x1="4" y1="15" x2="20" y2="15"/>'
            '<line x1="10" y1="3" x2="8" y2="21"/><line x1="16" y1="3" x2="14" y2="21"/>',
    "arrow": '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "alert": '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/>'
             '<line x1="12" y1="16" x2="12.01" y2="16"/>',
}

# Banner-Texte für Upload-Ergebnisse (Fehlercodes via ?err=…).
UPLOAD_ERRORS = {
    "size": "Datei zu groß — maximal 25 MB erlaubt.",
    "type": "Dateityp nicht unterstützt — erlaubt sind PNG, JPG, GIF und WebP.",
    "fields": "Bitte Spiel, Name und Seltenheit ausfüllen.",
    "noimg": "Bitte ein Bild auswählen.",
    "name": "Ungültiger Name — mindestens ein Buchstabe oder eine Ziffer nötig.",
}


def _icon(name: str, size: int = 18) -> str:
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{_ICON_PATHS[name]}</svg>')


FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    'family=Bricolage+Grotesque:opsz,wght@12..96,500..800&'
    'family=Hanken+Grotesk:wght@400;500;600;700&'
    'family=JetBrains+Mono:wght@400;500&display=swap">'
)

UPLOAD_JS = """
const dz=document.getElementById('dz'),inp=document.getElementById('imgInput'),
pv=document.getElementById('preview'),fn=document.getElementById('fname');
function show(){const f=inp.files[0];if(!f)return;fn.textContent=f.name;
pv.src=URL.createObjectURL(f);pv.style.display='block';}
dz.addEventListener('click',()=>inp.click());
inp.addEventListener('change',show);
['dragover','dragenter'].forEach(e=>dz.addEventListener(e,ev=>{ev.preventDefault();dz.classList.add('drag');}));
['dragleave','dragend'].forEach(e=>dz.addEventListener(e,()=>dz.classList.remove('drag')));
dz.addEventListener('drop',ev=>{ev.preventDefault();dz.classList.remove('drag');
if(ev.dataTransfer.files.length){inp.files=ev.dataTransfer.files;show();}});
"""


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
            web.get("/g/{gid}/overview", self.h_overview),
            web.get("/g/{gid}/cards", self.h_cards),
            web.post("/g/{gid}/cards/add", self.h_cards_add),
            web.post("/g/{gid}/cards/delete", self.h_cards_delete),
            web.get("/g/{gid}/games", self.h_games),
            web.post("/g/{gid}/games/add", self.h_games_add),
            web.post("/g/{gid}/games/remove", self.h_games_remove),
            web.post("/g/{gid}/channel", self.h_set_channel),
        ])
        app.router.add_static("/static/", path=str(STATIC_DIR))
        if ASSETS_DIR.is_dir():
            app.router.add_static("/assets/", path=str(ASSETS_DIR))

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
            raise web.HTTPFound(f"/g/{gid}/overview")
        items = "".join(
            f'<a href="/g/{gid}/overview">{_esc(name)}{_icon("arrow")}</a>'
            for gid, name in guilds.items()
        )
        body = f'<div class="guilds">{items}</div>'
        return self._html(sess, None, body, title="Server wählen")

    async def h_overview(self, request: web.Request) -> web.StreamResponse:
        sess, gid = self._require_guild(request)
        cards = self.db.list_custom_cards(gid)
        games = self.db.list_reward_games(gid)
        guild = self.bot.get_guild(gid)
        chan_id = self.db.get_card_channel(gid)

        rc = {r: 0 for r in RARITIES}
        for _cid, _name, rarity, _url, _game in cards:
            if rarity in rc:
                rc[rarity] += 1
        row = self.db.conn.execute(
            "SELECT COALESCE(SUM(count),0) AS s, COUNT(DISTINCT user_id) AS u "
            "FROM card_inventory WHERE guild_id=? AND count>0",
            (gid,),
        ).fetchone()
        total_owned, collectors = int(row["s"]), int(row["u"])
        chan_label = "DMs"
        if chan_id and guild:
            ch = guild.get_channel(chan_id)
            chan_label = f"#{ch.name}" if ch else "—"

        def stat(n: object, label: str, ic: str) -> str:
            return (f'<div class="stat"><span class="ic">{_icon(ic, 19)}</span>'
                    f'<div class="n">{_esc(n)}</div><div class="l">{label}</div></div>')

        stats = (
            '<div class="stats">'
            + stat(len(cards), "Kartentypen", "layers")
            + stat(len(games), "Belohnungs-Spiele", "gamepad")
            + stat(collectors, "Sammler", "users")
            + stat(f"{total_owned:,}".replace(",", " "), "Karten im Umlauf", "box")
            + stat(chan_label, "Drop-Channel", "hash")
            + "</div>"
        )
        chips = "".join(
            f'<span class="chip"><span class="dot" style="background:{_color(r)}"></span>'
            f'{RARITIES[r]["label"]} <b>{rc[r]}</b></span>'
            for r in RARITY_ORDER if rc[r] > 0
        ) or '<span class="chip">Noch keine Karten</span>'

        body = (
            stats
            + f'<div class="panel"><h2>Seltenheits-Verteilung</h2>'
            f'<div class="rar-chips">{chips}</div></div>'
            + '<div class="panel"><h2>Schnellzugriff</h2><div class="list">'
            + f'<a class="row" href="/g/{gid}/cards"><span class="rl">{_icon("layers")} '
            f'Sammelkarten verwalten &amp; hochladen</span>{_icon("arrow")}</a>'
            + f'<a class="row" href="/g/{gid}/games"><span class="rl">{_icon("gamepad")} '
            f'Spiele &amp; Drop-Channel einstellen</span>{_icon("arrow")}</a>'
            + "</div></div>"
        )
        return self._html(sess, gid, body, active="overview", title="Übersicht",
                          subtitle=guild.name if guild else "")

    async def h_cards(self, request: web.Request) -> web.StreamResponse:
        sess, gid = self._require_guild(request)
        cards = self.db.list_custom_cards(gid)  # (cid, name, rarity, url, game)
        games = self.db.list_reward_games(gid)

        rarity_opts = "".join(
            f'<option value="{r}">{RARITIES[r]["label"]}</option>' for r in RARITIES
        )
        game_datalist = "".join(f'<option value="{_esc(g)}">' for g in games)

        upload = f"""
        <div class="panel">
          <h2>Neue Karte hochladen</h2>
          <form method="post" action="/g/{gid}/cards/add" enctype="multipart/form-data" class="form-grid">
            <input type="hidden" name="csrf" value="{sess['csrf']}">
            <label class="f">Spiel<input name="game" list="games" required placeholder="z. B. Lost Ark"></label>
            <datalist id="games">{game_datalist}</datalist>
            <label class="f">Kartenname<input name="name" required maxlength="100" placeholder="z. B. Goblin Späher"></label>
            <label class="f">Seltenheit<select name="rarity">{rarity_opts}</select></label>
            <div class="dropzone" id="dz">
              <span class="dz-ic">⬆</span>
              <div class="dz-txt"><b id="fname">Bild hierher ziehen</b><br>oder klicken · PNG · JPG · GIF · WebP · max. 25 MB</div>
              <img class="pv" id="preview" alt="">
              <input type="file" name="image" id="imgInput" accept="image/*" required hidden>
            </div>
            <div class="actions"><button class="btn primary">Karte anlegen</button></div>
          </form>
        </div>
        <script>{UPLOAD_JS}</script>
        """

        sort = request.query.get("sort", "game")
        if sort not in ("game", "rarity"):
            sort = "game"
        rar_index = {r: i for i, r in enumerate(RARITY_ORDER)}
        counter = {"i": 0}

        def render_card(cid: str, name: str, rarity: str, url: str | None, sub_text: str) -> str:
            col = _color(rarity)
            delay = f"{counter['i'] * 0.03:.2f}"
            counter["i"] += 1
            img = (f'<div class="img"><img src="{_esc(url)}" loading="lazy" alt=""></div>'
                   if url else '<div class="img empty">kein Bild</div>')
            return (
                f'<article class="card" style="--rar:{col};animation-delay:{delay}s">'
                f'<span class="top">{RARITIES.get(rarity, RARITIES["common"])["label"]}</span>'
                f'<form method="post" action="/g/{gid}/cards/delete" '
                f'onsubmit="return confirm(\'Karte löschen?\')">'
                f'<input type="hidden" name="csrf" value="{sess["csrf"]}">'
                f'<input type="hidden" name="card_id" value="{_esc(cid)}">'
                f'<button class="del" title="Löschen">✕</button></form>{img}'
                f'<div class="meta"><div class="nm"><span class="dot"></span>{_esc(name)}</div>'
                f'<div class="sb">{_esc(sub_text)}</div></div></article>'
            )

        sections = ""
        if sort == "rarity":
            by_rar: dict[str, list[tuple]] = {}
            for cid, name, rarity, url, game in cards:
                by_rar.setdefault(rarity, []).append((cid, name, rarity, url, game))
            for r in RARITY_ORDER:
                items = by_rar.get(r)
                if not items:
                    continue
                col = _color(r)
                cardhtml = "".join(
                    render_card(cid, name, rarity, url, game or "—")
                    for cid, name, rarity, url, game in sorted(items, key=lambda c: c[1].lower())
                )
                sections += (
                    f'<div class="sect-h"><span class="sdot" style="background:{col};'
                    f'box-shadow:0 0 10px {col}"></span>{RARITIES[r]["label"]} '
                    f'<span class="count">{len(items)}</span></div><div class="grid">{cardhtml}</div>'
                )
        else:  # nach Spiel
            by_game: dict[str, list[tuple]] = {}
            for cid, name, rarity, url, game in cards:
                by_game.setdefault((game or "").strip(), []).append((cid, name, rarity, url, game))
            for g in sorted(by_game, key=lambda k: (k == "", k.lower())):
                items = sorted(by_game[g], key=lambda c: (rar_index.get(c[2], 99), c[1].lower()))
                cardhtml = "".join(
                    render_card(cid, name, rarity, url, RARITIES.get(rarity, RARITIES["common"])["label"])
                    for cid, name, rarity, url, game in items
                )
                label = g if g else "Ohne Spiel"
                sections += (
                    f'<div class="sect-h"><span class="sdot-i">{_icon("gamepad", 16)}</span>'
                    f'{_esc(label)} <span class="count">{len(items)}</span></div>'
                    f'<div class="grid">{cardhtml}</div>'
                )
        if not sections:
            sections = ('<div class="empty-state">Noch keine Karten angelegt — '
                        'lade oben deine erste Karte hoch!</div>')

        def tab(key: str, label: str) -> str:
            cls = "seg active" if sort == key else "seg"
            return f'<a class="{cls}" href="/g/{gid}/cards?sort={key}">{label}</a>'

        toolbar = (
            '<div class="toolbar"><span class="tb-lbl">Sortierung</span>'
            f'<div class="seg-group">{tab("game", "Nach Spiel")}{tab("rarity", "Nach Seltenheit")}</div></div>'
        )

        banner = ""
        if request.query.get("ok"):
            banner = f'<div class="banner ok">{_icon("check")} Karte erfolgreich angelegt.</div>'
        elif request.query.get("err") in UPLOAD_ERRORS:
            banner = f'<div class="banner err">{_icon("alert")} {UPLOAD_ERRORS[request.query["err"]]}</div>'

        body = banner + upload + toolbar + sections
        return self._html(sess, gid, body, active="cards", title="Sammelkarten",
                          subtitle=f"{len(cards)} Karten")

    async def h_cards_add(self, request: web.Request) -> web.StreamResponse:
        sess, gid = self._require_guild(request)
        back = f"/g/{gid}/cards"
        # Zu große Uploads lösen beim Body-Parsing 413 aus → freundlich abfangen.
        try:
            data = await request.post()
        except web.HTTPRequestEntityTooLarge:
            raise web.HTTPFound(f"{back}?err=size")
        self._check_csrf(sess, data)
        game = str(data.get("game", "")).strip()
        name = str(data.get("name", "")).strip()
        rarity = str(data.get("rarity", "common"))
        field = data.get("image")
        if not game or not name or rarity not in RARITIES:
            raise web.HTTPFound(f"{back}?err=fields")
        if not isinstance(field, web.FileField):
            raise web.HTTPFound(f"{back}?err=noimg")
        ext = Path(field.filename or "").suffix.lower()
        if ext not in ALLOWED_EXT:
            raise web.HTTPFound(f"{back}?err=type")
        card_id = _slug(game, name)
        if card_id is None:
            raise web.HTTPFound(f"{back}?err=name")

        guild_dir = STATIC_DIR / "cards" / str(gid)
        guild_dir.mkdir(parents=True, exist_ok=True)
        # Alte Bilder dieser Karte (andere Endung) entfernen.
        for old in guild_dir.glob(f"{card_id}.*"):
            old.unlink(missing_ok=True)
        dest = guild_dir / f"{card_id}{ext}"
        dest.write_bytes(field.file.read())

        url = f"{self.base_url}/static/cards/{gid}/{card_id}{ext}"
        self.db.add_custom_card(gid, card_id, name, rarity, url, game)
        raise web.HTTPFound(f"{back}?ok=1")

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
            f'<div class="row"><span>🎮 {_esc(g)}</span>'
            f'<form method="post" action="/g/{gid}/games/remove">'
            f'<input type="hidden" name="csrf" value="{sess["csrf"]}">'
            f'<input type="hidden" name="game" value="{_esc(g)}">'
            f'<button class="x">Entfernen</button></form></div>'
            for g in games
        ) or '<div class="empty-state">Keine Spiele eingetragen.</div>'

        chan_opts = ['<option value="">— DMs (kein Channel) —</option>']
        if guild is not None:
            for ch in guild.text_channels:
                sel = " selected" if chan_id == ch.id else ""
                chan_opts.append(f'<option value="{ch.id}"{sel}>#{_esc(ch.name)}</option>')

        body = f"""
        <div class="panel">
          <h2>Belohnungs-Spiele</h2>
          <form method="post" action="/g/{gid}/games/add" class="inline">
            <input type="hidden" name="csrf" value="{sess['csrf']}">
            <input name="game" required placeholder="Exakter Spielname (wie in Discord angezeigt)">
            <button class="btn primary">Hinzufügen</button>
          </form>
          <div class="list">{game_rows}</div>
        </div>
        <div class="panel">
          <h2>Karten-Drop-Channel</h2>
          <p class="hint">Wohin der Bot neue Karten-Drops meldet. Ohne Channel gehen sie per DM raus.</p>
          <form method="post" action="/g/{gid}/channel" class="inline">
            <input type="hidden" name="csrf" value="{sess['csrf']}">
            <select name="channel_id">{''.join(chan_opts)}</select>
            <button class="btn primary">Speichern</button>
          </form>
        </div>
        """
        return self._html(sess, gid, body, active="games", title="Spiele & Channel",
                          subtitle=guild.name if guild else "")

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

    def _html(self, sess: dict, gid: int | None, body: str, *,
              active: str = "", title: str = "", subtitle: str = "") -> web.Response:
        nav = ""
        if gid is not None:
            def item(href: str, ic: str, label: str, key: str) -> str:
                cls = "active" if key == active else ""
                return f'<a class="{cls}" href="{href}"><span class="ic">{_icon(ic)}</span>{label}</a>'
            nav = (
                '<nav class="nav">'
                + item(f"/g/{gid}/overview", "grid", "Übersicht", "overview")
                + item(f"/g/{gid}/cards", "layers", "Sammelkarten", "cards")
                + item(f"/g/{gid}/games", "gamepad", "Spiele &amp; Channel", "games")
                + "</nav>"
            )
        sub = f'<div class="sub">{_esc(subtitle)}</div>' if subtitle else ""
        page = f"""<!doctype html><html lang="de"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title) or "Panel"} · Yumikun</title>{FONTS}<style>{CSS}</style></head>
<body><div class="app">
<aside class="sidebar">
  <div class="brand"><img class="logo" src="/assets/YamiKun.png" alt=""> Yumikun</div>
  {nav}
  <div class="sb-foot"><span class="who">Angemeldet als <b>{_esc(sess['username'])}</b></span>
  <a class="logout" href="/logout">Abmelden</a></div>
</aside>
<main class="content">
  <div class="topbar"><div><h1>{_esc(title)}</h1>{sub}</div></div>
  {body}
</main></div></body></html>"""
        return web.Response(text=page, content_type="text/html")

    def _page_simple(self, title: str, message: str) -> str:
        return f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)} · Yumikun</title>{FONTS}<style>{CSS}</style></head>
<body><div class="simple"><div class="box">
<img class="logo-lg" src="/assets/YamiKun.png" alt=""><h2>{_esc(title)}</h2><p>{message}</p>
<a class="btn primary" href="/login">Erneut anmelden</a>
</div></div></body></html>"""


CSS = """
:root{
  --bg:#0c0d11;--bg2:#101218;--panel:#14161d;--panel2:#181b23;
  --line:#23262f;--line2:#2d313b;--txt:#e9ebf1;--muted:#9aa1ad;--faint:#69707d;
  --accent:#c8ff4d;--accent-ink:#161e00;--danger:#ff6b6b;--radius:14px;
  color-scheme:dark;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  font-family:"Hanken Grotesk",system-ui,sans-serif;color:var(--txt);min-height:100vh;
  -webkit-font-smoothing:antialiased;
  background:
    radial-gradient(1100px 560px at 85% -12%,rgba(200,255,77,.06),transparent 60%),
    radial-gradient(900px 520px at -10% 112%,rgba(120,160,255,.045),transparent 60%),
    var(--bg);
}
a{color:inherit;text-decoration:none}
h1,h2{font-family:"Bricolage Grotesque","Hanken Grotesk",sans-serif;letter-spacing:-.025em}

.app{display:grid;grid-template-columns:248px 1fr;min-height:100vh}

.sidebar{position:sticky;top:0;height:100vh;display:flex;flex-direction:column;gap:6px;
  padding:22px 16px;border-right:1px solid var(--line);
  background:linear-gradient(180deg,var(--bg2),transparent 70%)}
.brand{display:flex;align-items:center;gap:10px;padding:6px 6px 20px;
  font-family:"Bricolage Grotesque";font-weight:700;font-size:1.18rem;letter-spacing:-.02em}
.brand .logo{width:32px;height:32px;border-radius:9px;object-fit:cover}
.nav{display:flex;flex-direction:column;gap:3px}
.nav a{position:relative;display:flex;align-items:center;gap:11px;padding:10px 12px;
  border-radius:10px;color:var(--muted);font-weight:500;transition:background .15s,color .15s}
.nav a .ic{display:inline-flex;align-items:center;justify-content:center;width:18px;opacity:.85}
.nav a:hover{background:var(--panel);color:var(--txt)}
.nav a.active{background:var(--panel2);color:#fff;box-shadow:inset 3px 0 0 var(--accent)}
.sb-foot{margin-top:auto;border-top:1px solid var(--line);padding-top:14px;
  display:flex;flex-direction:column;gap:6px;font-size:.85rem}
.sb-foot .who{color:var(--muted)} .sb-foot .who b{color:var(--txt);font-weight:600}
.sb-foot .logout{color:var(--faint)} .sb-foot .logout:hover{color:var(--danger)}

.content{padding:30px 38px 70px;max-width:1080px;width:100%}
.topbar{margin-bottom:24px}
.topbar h1{font-size:1.95rem;margin:0}
.topbar .sub{color:var(--muted);font-size:.92rem;margin-top:5px}

.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:14px;margin-bottom:24px}
.stat{position:relative;background:var(--panel);border:1px solid var(--line);
  border-radius:var(--radius);padding:18px;overflow:hidden;animation:rise .5s both}
.stat .n{font-family:"Bricolage Grotesque";font-weight:700;font-size:2rem;line-height:1;letter-spacing:-.02em}
.stat .l{color:var(--muted);font-size:.74rem;margin-top:9px;text-transform:uppercase;letter-spacing:.07em}
.stat .ic{position:absolute;right:14px;top:13px;font-size:1.05rem;opacity:.45}

.panel{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);
  padding:22px;margin-bottom:22px}
.panel h2{font-size:1.12rem;margin:0 0 16px}
.panel .hint{color:var(--muted);font-size:.86rem;margin:-8px 0 14px}

.rar-chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{display:inline-flex;align-items:center;gap:8px;padding:7px 13px;border-radius:999px;
  background:var(--panel2);border:1px solid var(--line);font-size:.85rem}
.chip .dot{width:9px;height:9px;border-radius:50%}
.chip b{font-family:"JetBrains Mono";font-weight:500;color:var(--txt)}

.sect-h{display:flex;align-items:center;gap:10px;margin:28px 0 13px;
  font-family:"Bricolage Grotesque";font-weight:600;font-size:1.02rem}
.sect-h .sdot{width:10px;height:10px;border-radius:50%}
.sect-h .sdot-i{display:inline-flex;color:var(--faint)}
.sect-h .count{color:var(--faint);font-weight:500;font-family:"JetBrains Mono";font-size:.85rem}

.banner{display:flex;align-items:center;gap:10px;padding:13px 16px;border-radius:11px;
  margin-bottom:18px;font-size:.9rem;font-weight:500;animation:rise .4s both}
.banner svg{flex:none}
.banner.err{color:#ffb4b4;background:color-mix(in srgb,var(--danger) 13%,transparent);
  border:1px solid color-mix(in srgb,var(--danger) 40%,transparent)}
.banner.ok{color:var(--accent);background:color-mix(in srgb,var(--accent) 12%,transparent);
  border:1px solid color-mix(in srgb,var(--accent) 38%,transparent)}
.toolbar{display:flex;align-items:center;gap:13px;margin:4px 0 2px}
.tb-lbl{color:var(--faint);font-size:.74rem;text-transform:uppercase;letter-spacing:.07em}
.seg-group{display:inline-flex;gap:2px;padding:3px;border:1px solid var(--line);
  border-radius:11px;background:var(--panel)}
.seg{padding:7px 14px;border-radius:8px;font-size:.85rem;font-weight:600;color:var(--muted);transition:.15s}
.seg:hover{color:var(--txt)}
.seg.active{background:var(--accent);color:var(--accent-ink)}

.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(166px,1fr));gap:16px}
.card{position:relative;background:var(--panel);border:1px solid var(--line);
  border-radius:14px;overflow:hidden;transition:transform .18s,border-color .18s;animation:rise .5s both}
.card:hover{transform:translateY(-4px);border-color:color-mix(in srgb,var(--rar) 55%,var(--line))}
.card .img{aspect-ratio:3/4;background:var(--bg2);position:relative;overflow:hidden}
.card .img img{width:100%;height:100%;object-fit:cover;display:block}
.card .img.empty{display:grid;place-items:center;color:var(--faint);font-size:.78rem}
.card .img::after{content:"";position:absolute;inset:0;
  background:linear-gradient(180deg,transparent 58%,rgba(0,0,0,.5));pointer-events:none}
.card .top{position:absolute;top:8px;left:8px;z-index:2;font-size:.62rem;font-weight:700;
  text-transform:uppercase;letter-spacing:.06em;padding:4px 8px;border-radius:7px;
  color:var(--rar);background:color-mix(in srgb,var(--rar) 18%,#000 70%);
  border:1px solid color-mix(in srgb,var(--rar) 40%,transparent)}
.card .meta{padding:11px 12px 13px}
.card .nm{display:flex;align-items:center;gap:7px;font-weight:600;font-size:.9rem;line-height:1.2}
.card .nm .dot{width:8px;height:8px;border-radius:50%;flex:none;background:var(--rar);box-shadow:0 0 8px var(--rar)}
.card .sb{color:var(--muted);font-size:.77rem;margin-top:5px}
.card .del{position:absolute;top:8px;right:8px;z-index:3;width:28px;height:28px;border-radius:8px;
  border:1px solid var(--line2);background:rgba(8,9,12,.72);color:var(--muted);cursor:pointer;
  opacity:0;transition:.15s;backdrop-filter:blur(4px);font-size:.8rem}
.card:hover .del{opacity:1}
.card .del:hover{color:var(--danger);border-color:var(--danger)}

@keyframes rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}

.form-grid{display:grid;gap:16px;grid-template-columns:1fr 1fr}
label.f{display:flex;flex-direction:column;gap:7px;font-size:.8rem;color:var(--muted);font-weight:600}
input,select{font-family:inherit;font-size:.92rem;padding:11px 13px;border-radius:10px;
  border:1px solid var(--line2);background:var(--bg2);color:var(--txt);transition:.15s}
input::placeholder{color:var(--faint)}
input:focus,select:focus{outline:none;border-color:var(--accent);
  box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 22%,transparent)}
.dropzone{grid-column:1/-1;display:flex;align-items:center;gap:18px;cursor:pointer;
  padding:20px;border:1.5px dashed var(--line2);border-radius:12px;background:var(--bg2);transition:.15s}
.dropzone:hover,.dropzone.drag{border-color:var(--accent);
  background:color-mix(in srgb,var(--accent) 7%,var(--bg2))}
.dropzone .dz-ic{font-size:1.5rem;color:var(--accent)}
.dropzone .dz-txt{color:var(--muted);font-size:.86rem;line-height:1.4}
.dropzone .dz-txt b{color:var(--txt);font-weight:600}
.dropzone .pv{display:none;width:62px;height:82px;object-fit:cover;border-radius:8px;
  margin-left:auto;border:1px solid var(--line2)}
.actions{grid-column:1/-1;display:flex;justify-content:flex-end}
.btn{font-family:inherit;font-weight:600;font-size:.92rem;padding:11px 20px;border-radius:10px;
  border:0;cursor:pointer;transition:.15s}
.btn.primary{background:var(--accent);color:var(--accent-ink)}
.btn.primary:hover{filter:brightness(1.07);transform:translateY(-1px)}

.inline{display:flex;gap:10px;margin-bottom:16px}
.inline input,.inline select{flex:1}
.list{display:flex;flex-direction:column;gap:8px}
.row{display:flex;align-items:center;justify-content:space-between;gap:12px;
  padding:12px 15px;border:1px solid var(--line);border-radius:11px;background:var(--bg2);transition:.15s}
a.row:hover{border-color:var(--accent);color:#fff}
.row .rl{display:inline-flex;align-items:center;gap:11px}
.row .x{background:none;border:0;color:var(--faint);cursor:pointer;font-size:.85rem;
  padding:6px 11px;border-radius:8px;font-family:inherit;font-weight:600}
.row .x:hover{color:var(--danger);background:color-mix(in srgb,var(--danger) 12%,transparent)}
.empty-state{color:var(--faint);text-align:center;padding:34px;
  border:1px dashed var(--line);border-radius:12px}

.guilds{display:grid;gap:12px;max-width:440px}
.guilds a{display:flex;align-items:center;justify-content:space-between;padding:18px 20px;
  border:1px solid var(--line);border-radius:12px;background:var(--panel);font-weight:600;font-size:1.05rem}
.guilds a:hover{border-color:var(--accent)}

.simple{min-height:100vh;display:grid;place-items:center;padding:24px}
.simple .box{max-width:420px;text-align:center;background:var(--panel);border:1px solid var(--line);
  border-radius:18px;padding:42px 34px;box-shadow:0 20px 60px rgba(0,0,0,.45)}
.simple .logo-lg{width:66px;height:66px;border-radius:16px;margin:0 auto 18px;object-fit:cover;display:block}
.simple h2{font-size:1.45rem;margin:0 0 12px}
.simple p{color:var(--muted);line-height:1.55;font-size:.92rem}
.simple .btn{display:inline-block;margin-top:20px}

@media(max-width:820px){
  .app{grid-template-columns:1fr}
  .sidebar{position:static;height:auto;flex-direction:row;flex-wrap:wrap;align-items:center;gap:10px}
  .brand{padding:6px}
  .nav{flex-direction:row;flex-wrap:wrap}
  .sb-foot{margin:0 0 0 auto;border:0;padding:0;flex-direction:row;align-items:center;gap:12px}
  .content{padding:22px}
  .form-grid{grid-template-columns:1fr}
}
"""


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WebPanelCog(bot))

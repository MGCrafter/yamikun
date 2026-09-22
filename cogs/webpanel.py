"""Web-Admin-Panel für den Bot — JSON-API + Auslieferung der React-SPA.

- Läuft als aiohttp-Server IM Bot-Prozess (gleiche SQLite-Verbindung, kein
  zweiter Schreiber, Zugriff auf den Bot-Cache für Rechte-Prüfungen).
- Login via Discord-OAuth2 (Scope `identify`). Zugriff nur, wenn der eingeloggte
  User auf dem jeweiligen Server die Berechtigung "Server verwalten"
  (manage_guild) hat.
- Die Oberfläche ist eine React-App (Vite-Build unter frontend/dist). Dieser
  Server liefert nur noch JSON unter /api/... aus und reicht alle übrigen Pfade
  an die SPA (index.html) durch — Client-seitiges Routing.
- Karten-Bilder werden hochgeladen, lokal unter static/cards/<guild>/ gespeichert
  und unter WEB_BASE_URL/static/... ausgeliefert (damit Discord sie laden kann).

Aktiviert über die Umgebungsvariable WEB_ENABLED=1. Benötigt zusätzlich:
  WEB_BASE_URL, OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET
Optional: WEB_HOST (Standard 0.0.0.0), WEB_PORT (Standard 8080).

ID-Hinweis: Discord-IDs (Guild/User/Channel) werden in JSON IMMER als String
ausgeliefert — sie überschreiten Number.MAX_SAFE_INTEGER in JavaScript.
"""

from __future__ import annotations

import asyncio
import base64
import html
import json
import logging
import os
import re
import secrets
import time
import urllib.parse
from pathlib import Path

import aiohttp
import discord
from aiohttp import web
from discord.ext import commands

from cogs.gamecards import RARITIES, RARITY_ORDER, _slug
from cogs.booster import _slug as _yami_slug, resolve_booster_emoji
from cogs.welcome import DEFAULT_WELCOME
from cogs.boostnotify import DEFAULT_BOOST
from cogs.twitch import DEFAULT_TWITCH_MESSAGE, TWITCH_PLACEHOLDERS, normalize_login
from cogs.leveling import LEVELUP_PLACEHOLDERS
from cogs.achievements import friend_achievement_payload, user_achievement_payload
from cogs.audit import CATEGORIES as AUDIT_CATEGORIES
from cogs.fusion import fuse_game, fuse_yami, fusable_counts, FUSABLE

from webpanel.constants import (
    ALLOWED_EXT,
    API_BASE,
    ASSETS_DIR,
    COIN_AMOUNT_MAX,
    EMBED_DESC_MAX,
    EMBED_TITLE_MAX,
    FRONTEND_DIST,
    GAME_REQUEST_COOLDOWN,
    IMAGE_MIME as _IMAGE_MIME,
    MAX_UPLOAD,
    MSG_MAX,
    NICK_MAX,
    PLACEHOLDER_HTML,
    SCOPE,
    SESSION_COOKIE,
    SESSION_TTL,
    STATE_COOKIE,
    STATIC_DIR,
    TRANSCRIPT_PAGE as _TRANSCRIPT_PAGE,
    UPLOAD_ERRORS,
)
from webpanel.helpers import (
    card_payload as _card,
    color_for_rarity as _color,
    discord_avatar as _discord_avatar,
    is_http_url as _is_http_url,
    local_static_url as _local_static_url,
    rarities_meta as _rarities_meta,
    rarity_label as _rarity_label,
)
from webpanel.images import (
    card_image_needs_optimization,
    optimize_existing_card_image,
    save_card_upload,
)
from webpanel.middleware import (
    cache_compress_middleware as _cache_compress_mw,
    cache_get as _cache_get,
    cache_set as _cache_set,
    rate_limit_middleware as _rate_limit_mw,
)
from webpanel.routes import register_routes

logger = logging.getLogger("oaken-tower-bot")

# Steam-artige Spielkarten-Ökonomie im Profilalbum. Das letzte Exemplar einer
# Karte kann nicht zerlegt werden; nur echte Duplikate erzeugen Arkansplitter.
CARD_SHARD_REWARDS: dict[str, int] = {
    "common": 20,
    "uncommon": 40,
    "rare": 80,
    "epic": 160,
    "legendary": 320,
    "mythic": 800,
}
GAME_BOOSTER_SHARD_COST = 400


def _game_pack_type(game: str) -> str:
    return "game:" + game.strip().lower()


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
        # Optionale Whitelist von Discord-User-IDs, die Karten hoch-/runterladen dürfen.
        # Leer = wie bisher (alle Server-Admins). Format: "123,456" (Komma/Leerzeichen).
        raw_owners = os.environ.get("WEB_OWNER_IDS", "").replace(" ", "")
        self.owner_ids = {int(x) for x in raw_owners.split(",") if x.isdigit()}
        self.redirect_uri = f"{self.base_url}/callback"
        self.secure_cookies = self.base_url.startswith("https://")

        self._runner: web.AppRunner | None = None
        self._http: aiohttp.ClientSession | None = None
        self._card_migration_task: asyncio.Task | None = None
        # token -> {"user_id", "username", "guilds": {gid: name}, "csrf", "exp"}
        self._sessions: dict[str, dict] = {}
        # user_id -> Zeitpunkt der letzten Spiel-Anfrage (Cooldown, siehe GAME_REQUEST_COOLDOWN).
        self._game_requests: dict[int, float] = {}
        # user_id -> Zeitpunkt der letzten Bug-/Feature-Anfrage aus dem Webpanel.
        self._feedback_requests: dict[int, float] = {}
        self._twitch_panel = None

    def _local_card_image_path(self, url: str | None) -> Path | None:
        """Löst eine gespeicherte /static/-URL sicher auf den persistenten Pfad auf."""
        if not url:
            return None
        path = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
        if not path.startswith("/static/"):
            return None
        root = STATIC_DIR.resolve()
        candidate = (root / path.removeprefix("/static/")).resolve()
        if candidate == root or root not in candidate.parents:
            return None
        return candidate

    async def _optimize_existing_card_images(self) -> int:
        """Migriert alte lokale PNG/JPEG/GIF-Karten einmalig zu kleinen WebPs."""
        optimized: dict[Path, str] = {}
        changed = 0

        async def optimized_url(url: str | None) -> str | None:
            nonlocal changed
            path = self._local_card_image_path(url)
            if path is None or not path.is_file():
                return url
            if path in optimized:
                return optimized[path]
            try:
                needs_optimization = await asyncio.to_thread(card_image_needs_optimization, path)
                if not needs_optimization:
                    return url
                dest = await asyncio.to_thread(optimize_existing_card_image, path)
            except (OSError, ValueError) as exc:
                logger.warning("Kartenbild konnte nicht optimiert werden (%s): %s", path, exc)
                return url
            relative = dest.relative_to(STATIC_DIR.resolve()).as_posix()
            new_url = f"{self.base_url}/static/{relative}?v={int(time.time())}"
            optimized[path] = new_url
            changed += 1
            return new_url

        for card_id, name, rarity, url, game in self.db.list_custom_cards(0):
            new_url = await optimized_url(url)
            if new_url != url:
                self.db.add_custom_card(0, card_id, name, rarity, new_url, game or "")
        for card_id, name, rarity, url in self.db.list_server_cards(0):
            new_url = await optimized_url(url)
            if new_url != url:
                self.db.add_server_card(0, card_id, name, rarity, new_url)
        return changed

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
        (STATIC_DIR / "yami").mkdir(exist_ok=True)
        (STATIC_DIR / "welcome").mkdir(exist_ok=True)
        self._http = aiohttp.ClientSession()

        app = web.Application(
            client_max_size=MAX_UPLOAD,
            # Reihenfolge: Rate-Limit zuerst (lehnt früh ab), dann Cache/gzip.
            middlewares=[_rate_limit_mw, _cache_compress_mw],
        )
        from webpanel.twitch_chat import TwitchChatPanel
        self._twitch_panel = TwitchChatPanel(self)
        self._twitch_panel.register(app)
        register_routes(app, self, static_dir=STATIC_DIR, assets_dir=ASSETS_DIR)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        await self._twitch_panel.service.start()
        logger.info("Webpanel läuft auf %s:%s (öffentlich: %s)", self.host, self.port, self.base_url)
        # Die Migration kann bei vielen/ großen Altbildern Minuten dauern. Sie darf
        # deshalb weder den Discord-Login noch CapRovers Health-Check blockieren.
        self._card_migration_task = asyncio.create_task(
            self._run_card_image_migration(), name="card-image-migration"
        )

    async def _run_card_image_migration(self) -> None:
        try:
            changed = await self._optimize_existing_card_images()
            if changed:
                logger.info("%s vorhandene Kartenbilder für schnelles Discord-Laden optimiert.", changed)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - Hintergrundtask darf den Bot nie beenden
            logger.exception("Hintergrund-Migration der Kartenbilder fehlgeschlagen.")

    async def cog_unload(self) -> None:
        if self._twitch_panel is not None:
            await self._twitch_panel.service.close()
        if self._card_migration_task is not None:
            self._card_migration_task.cancel()
        if self._runner is not None:
            await self._runner.cleanup()
        if self._http is not None:
            await self._http.close()

    # --- Auth-Helper ----------------------------------------------------------

    def _new_session(
        self, user_id: int, username: str, guilds: dict[int, str],
        member_guilds: dict[int, str] | None = None, avatar: str | None = None,
    ) -> str:
        token = secrets.token_urlsafe(32)
        self._sessions[token] = {
            "user_id": user_id,
            "username": username,
            "avatar": avatar,  # Discord-Profilbild-URL des eingeloggten Users
            "guilds": guilds,  # Admin-Guilds (manage_guild) — steuern das Admin-Panel
            "member_guilds": member_guilds or dict(guilds),  # alle geteilten Server (User-Dashboard)
            "csrf": secrets.token_urlsafe(24),
            "exp": time.time() + SESSION_TTL,
        }
        self.db.save_web_session(token, self._sessions[token])
        self.db.cleanup_web_sessions()
        return token

    def _session(self, request: web.Request) -> dict | None:
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            return None
        sess = self._sessions.get(token)
        if sess is None:
            sess = self.db.get_web_session(token)
            if sess is None:
                return None
            self._sessions[token] = sess
        if sess["exp"] < time.time():
            self._sessions.pop(token, None)
            self.db.delete_web_session(token)
            return None
        return sess

    @staticmethod
    def _err(exc_cls, code: str):
        """Baut eine HTTP-Exception mit JSON-Body {"error": code}."""
        return exc_cls(text=json.dumps({"error": code}), content_type="application/json")

    @staticmethod
    def _web_card(
        cid: str,
        name: str,
        rarity: str,
        url: str | None,
        *,
        game: str | None = None,
        count: int | None = None,
    ) -> dict:
        """Karten-Payload fürs WebPanel mit domainstabilen lokalen Bild-URLs."""
        return _card(cid, name, rarity, _local_static_url(url), game=game, count=count)

    def _require_api(self, request: web.Request) -> dict:
        sess = self._session(request)
        if sess is None:
            raise self._err(web.HTTPUnauthorized, "unauthorized")
        return sess

    def _require_guild_api(self, request: web.Request) -> tuple[dict, int]:
        sess = self._require_api(request)
        try:
            gid = int(request.match_info["gid"])
        except (KeyError, ValueError):
            raise self._err(web.HTTPBadRequest, "bad_guild")
        if gid not in sess["guilds"]:
            raise self._err(web.HTTPForbidden, "forbidden")
        return sess, gid

    def _require_member_guild_api(self, request: web.Request) -> tuple[dict, int]:
        """Wie _require_guild_api, aber nur Mitgliedschaft nötig (User-Dashboard)."""
        sess = self._require_api(request)
        try:
            gid = int(request.match_info["gid"])
        except (KeyError, ValueError):
            raise self._err(web.HTTPBadRequest, "bad_guild")
        if gid not in sess.get("member_guilds", {}):
            raise self._err(web.HTTPForbidden, "forbidden")
        return sess, gid

    def _check_csrf(self, sess: dict, request: web.Request, data=None) -> None:
        """CSRF-Token aus Header X-CSRF-Token oder Formfeld `csrf`."""
        token = request.headers.get("X-CSRF-Token")
        if not token and data is not None:
            token = data.get("csrf")
        if token != sess["csrf"]:
            raise self._err(web.HTTPForbidden, "bad_csrf")

    # --- Eingabe-Validierung (serverseitig, ergänzt die Frontend-Prüfung) -----
    @staticmethod
    def _field(data: dict, key: str) -> str:
        """Liefert ein String-Feld aus dem JSON-Body, getrimmt."""
        return str(data.get(key, "")).strip()

    def _require_fields(self, data: dict, *keys: str) -> None:
        """Wirft 'fields', wenn eines der genannten Pflichtfelder leer ist."""
        for k in keys:
            if not self._field(data, k):
                raise self._err(web.HTTPBadRequest, "fields")

    def _require_len(self, text: str, max_len: int) -> None:
        """Wirft 'too_long', wenn der Text das Discord-Limit überschreitet."""
        if len(text) > max_len:
            raise self._err(web.HTTPBadRequest, "too_long")

    @staticmethod
    def _is_http_url(url: str) -> bool:
        """True nur für echte http(s)-URLs (blockt javascript:/data:/file:)."""
        return _is_http_url(url)

    def _can_edit_cards(self, sess: dict) -> bool:
        """Darf dieser User Karten hoch-/runterladen? Ohne Whitelist: alle Admins (wie bisher)."""
        if not self.owner_ids:
            return True
        return sess["user_id"] in self.owner_ids

    def _require_card_editor(self, sess: dict) -> None:
        if not self._can_edit_cards(sess):
            raise self._err(web.HTTPForbidden, "card_editor_only")

    def _require_global_owner(self, sess: dict) -> None:
        """Globale Guthaben und Inventare dürfen nur explizite Owner ändern."""
        if sess["user_id"] not in self.owner_ids:
            raise self._err(web.HTTPForbidden, "global_owner_only")

    async def _admin_guilds(self, user_id: int) -> dict[int, str]:
        """Server, auf denen der Bot ist UND der User manage_guild hat."""
        admin, _member = await self._user_guilds(user_id)
        return admin

    async def _user_guilds(self, user_id: int) -> tuple[dict[int, str], dict[int, str]]:
        """In einem Durchlauf: (Admin-Guilds mit manage_guild, alle geteilten Guilds)."""
        admin: dict[int, str] = {}
        member: dict[int, str] = {}
        for guild in self.bot.guilds:
            try:
                m = guild.get_member(user_id) or await guild.fetch_member(user_id)
            except (discord.NotFound, discord.HTTPException):
                continue
            member[guild.id] = guild.name
            if m.guild_permissions.manage_guild or guild.owner_id == user_id:
                admin[guild.id] = guild.name
        return admin, member

    def _uname(self, uid: int) -> str:
        user = self.bot.get_user(uid)
        return user.display_name if user else f"User {uid}"

    def _avatar(self, uid: int) -> str | None:
        """Profilbild-URL eines (gecachten) Users — sonst None (Frontend zeigt Initiale)."""
        user = self.bot.get_user(uid)
        try:
            return str(user.display_avatar.url) if user else None
        except AttributeError:
            return None

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
        # Only a fixed local destination is allowed, bound to this OAuth state.
        if request.query.get("return_to") == "/twitch":
            resp.set_cookie("yami_discord_twitch_return", state, max_age=600,
                            httponly=True, secure=self.secure_cookies, samesite="Lax")
        else:
            resp.del_cookie("yami_discord_twitch_return")
        return resp

    async def h_callback(self, request: web.Request) -> web.StreamResponse:
        code = request.query.get("code")
        state = request.query.get("state")
        return_to_twitch = bool(state) and state == request.cookies.get("yami_discord_twitch_return")
        if not code or state != request.cookies.get(STATE_COOKIE):
            raise web.HTTPFound("/?error=state")
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
                raise web.HTTPFound("/?error=token")
            token = (await r.json())["access_token"]
        async with self._http.get(
            f"{API_BASE}/users/@me", headers={"Authorization": f"Bearer {token}"}
        ) as r:
            if r.status != 200:
                raise web.HTTPFound("/?error=profile")
            user = await r.json()

        user_id = int(user["id"])
        admin_guilds, member_guilds = await self._user_guilds(user_id)
        if not member_guilds and not return_to_twitch:
            # Auf keinem gemeinsamen Server -> zurück zur Landing-Page mit Hinweis.
            raise web.HTTPFound("/?error=no_access")
        sess_token = self._new_session(
            user_id, user.get("global_name") or user["username"], admin_guilds, member_guilds,
            avatar=_discord_avatar(user_id, user.get("avatar")),
        )
        resp = web.HTTPFound("/twitch" if return_to_twitch else "/app")
        resp.del_cookie("yami_discord_twitch_return")
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
            self.db.delete_web_session(token)
        resp = web.HTTPFound("/")
        resp.del_cookie(SESSION_COOKIE)
        return resp

    # --- API: Session / Meta --------------------------------------------------

    async def api_health(self, request: web.Request) -> web.Response:
        """Öffentlicher Health-Check für CapRover/Reverse-Proxy."""
        return web.json_response({
            "status": "ok",
            "guild_count": len(getattr(self.bot, "guilds", [])),
        })

    async def api_me(self, request: web.Request) -> web.Response:
        """Wer bin ich? Liefert immer 200 — nicht eingeloggt = authenticated:false."""
        sess = self._session(request)
        if sess is None:
            return web.json_response({"authenticated": False, "rarities": _rarities_meta()})
        return web.json_response({
            "authenticated": True,
            "username": sess["username"],
            "avatar": sess.get("avatar"),
            "can_edit_cards": self._can_edit_cards(sess),
            "can_manage_global_assets": sess["user_id"] in self.owner_ids,
            "csrf": sess["csrf"],
            "guilds": [{"id": str(g), "name": n} for g, n in sess["guilds"].items()],
            "member_guilds": [
                {"id": str(g), "name": n} for g, n in sess.get("member_guilds", {}).items()
            ],
            "rarities": _rarities_meta(),
        })

    # --- API: Übersicht -------------------------------------------------------

    async def api_overview(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        cache_key = f"overview:{gid}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return web.json_response(cached)
        cards = self.db.list_custom_cards(gid)
        games = self.db.list_reward_games(gid)
        guild = self.bot.get_guild(gid)
        chan_id = self.db.get_card_channel(gid)

        rc = {r: 0 for r in RARITIES}
        for _cid, _name, rarity, _url, _game in cards:
            if rarity in rc:
                rc[rarity] += 1
        owners = self.db.list_card_collectors(gid)
        collectors = len(owners)
        total_owned = sum(c for _uid, c in owners)
        chan_label = "DMs"
        if chan_id and guild:
            ch = guild.get_channel(chan_id)
            chan_label = f"#{ch.name}" if ch else "—"

        distribution = [
            {"key": r, "label": RARITIES[r]["label"], "color": _color(r), "count": rc[r]}
            for r in RARITY_ORDER if rc.get(r, 0) > 0
        ]
        payload = {
            "guild": {"id": str(gid), "name": guild.name if guild else ""},
            "stats": {
                "card_types": len(cards),
                "games": len(games),
                "collectors": collectors,
                "total_owned": total_owned,
                "channel_label": chan_label,
            },
            "rarity_distribution": distribution,
        }
        _cache_set(cache_key, payload)
        return web.json_response(payload)

    # --- API: Sammelkarten ----------------------------------------------------

    async def api_cards(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        cards = self.db.list_custom_cards(gid)  # (cid, name, rarity, url, game)
        games = self.db.list_reward_games(gid)
        return web.json_response({
            "can_edit": self._can_edit_cards(sess),
            "games": list(games),
            "cards": [self._web_card(cid, name, rarity, url, game=game or "")
                      for cid, name, rarity, url, game in cards],
        })

    async def api_cards_add(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        try:
            data = await request.post()
        except web.HTTPRequestEntityTooLarge:
            raise self._err(web.HTTPBadRequest, "size")
        self._check_csrf(sess, request, data)
        self._require_card_editor(sess)
        game = str(data.get("game", "")).strip()
        name = str(data.get("name", "")).strip()
        rarity = str(data.get("rarity", "common"))
        field = data.get("image")
        if not game or not name or rarity not in RARITIES:
            raise self._err(web.HTTPBadRequest, "fields")
        if not isinstance(field, web.FileField):
            raise self._err(web.HTTPBadRequest, "noimg")
        ext = Path(field.filename or "").suffix.lower()
        if ext not in ALLOWED_EXT:
            raise self._err(web.HTTPBadRequest, "type")
        card_id = _slug(game, name)
        if card_id is None:
            raise self._err(web.HTTPBadRequest, "name")

        guild_dir = STATIC_DIR / "cards" / str(gid)
        guild_dir.mkdir(parents=True, exist_ok=True)
        for old in guild_dir.glob(f"{card_id}.*"):
            old.unlink(missing_ok=True)
        dest = save_card_upload(field.file.read(), ext, guild_dir, card_id)
        ext = dest.suffix.lower()

        url = f"{self.base_url}/static/cards/{gid}/{card_id}{ext}"
        self.db.add_custom_card(gid, card_id, name, rarity, url, game)
        return web.json_response({"ok": True, "id": card_id})

    async def api_cards_delete(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        self._require_card_editor(sess)
        card_id = str(data.get("card_id", ""))
        if card_id:
            self.db.remove_custom_card(gid, card_id)
            for old in (STATIC_DIR / "cards" / str(gid)).glob(f"{card_id}.*"):
                old.unlink(missing_ok=True)
        return web.json_response({"ok": True})

    async def api_cards_rename(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        self._require_card_editor(sess)
        card_id = str(data.get("card_id", ""))
        name = str(data.get("newname", "")).strip()[:100]
        self._require_fields(data, "card_id")
        if not name:
            raise self._err(web.HTTPBadRequest, "fields")
        self.db.rename_custom_card(gid, card_id, name)
        return web.json_response({"ok": True})

    async def api_cards_replace(self, request: web.Request) -> web.Response:
        """Bild einer bestehenden Karte austauschen (Name/Seltenheit/Spiel bleiben)."""
        sess, gid = self._require_guild_api(request)
        try:
            data = await request.post()
        except web.HTTPRequestEntityTooLarge:
            raise self._err(web.HTTPBadRequest, "size")
        self._check_csrf(sess, request, data)
        self._require_card_editor(sess)
        card_id = str(data.get("card_id", "")).strip()
        existing = next((c for c in self.db.list_custom_cards(gid) if c[0] == card_id), None)
        if existing is None:
            raise self._err(web.HTTPBadRequest, "not_found")
        _cid, name, rarity, _url, game = existing
        field = data.get("image")
        if not isinstance(field, web.FileField):
            raise self._err(web.HTTPBadRequest, "noimg")
        ext = Path(field.filename or "").suffix.lower()
        if ext not in ALLOWED_EXT:
            raise self._err(web.HTTPBadRequest, "type")
        guild_dir = STATIC_DIR / "cards" / str(gid)
        guild_dir.mkdir(parents=True, exist_ok=True)
        for old in guild_dir.glob(f"{card_id}.*"):
            old.unlink(missing_ok=True)
        dest = save_card_upload(field.file.read(), ext, guild_dir, card_id)
        ext = dest.suffix.lower()
        # ?v=… als Cache-Buster, damit das neue Bild sofort geladen wird.
        url = f"{self.base_url}/static/cards/{gid}/{card_id}{ext}?v={int(time.time())}"
        self.db.add_custom_card(gid, card_id, name, rarity, url, game)
        return web.json_response({"ok": True, "url": url})

    # --- API: Spiele & Channel ------------------------------------------------

    async def api_games(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        games = self.db.list_reward_games_full(gid)  # (g, iv, cap, emoji)
        guild = self.bot.get_guild(gid)
        chan_id = self.db.get_card_channel(gid)

        aliases_by_game: dict[str, list[str]] = {}
        for alias, game in self.db.list_reward_game_aliases(gid):
            aliases_by_game.setdefault(game, []).append(alias)

        game_list = [{
            "name": g,
            "interval": iv,
            "cap": cap,
            "emoji": emoji or "",
            "emoji_display": str(resolve_booster_emoji(guild, self.db, g)),
            "aliases": aliases_by_game.get(g, []),
        } for g, iv, cap, emoji in games]

        channels = []
        if guild is not None:
            channels = [{"id": str(ch.id), "name": ch.name} for ch in guild.text_channels]

        return web.json_response({
            "guild": {"id": str(gid), "name": guild.name if guild else ""},
            "games": game_list,
            "channels": channels,
            "channel_id": str(chan_id) if chan_id else None,
        })

    async def api_games_add(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        game = str(data.get("game", "")).strip()
        # Leerer Spielname ist ein echter Fehler, kein stilles "ok".
        self._require_fields(data, "game")

        def _intval(key: str, default: int, lo: int, hi: int) -> int:
            raw = str(data.get(key, "")).strip()
            return max(lo, min(hi, int(raw))) if raw.lstrip("-").isdigit() else default

        interval = _intval("interval", 30, 1, 1440)
        cap = _intval("cap", 12, 1, 100)
        self.db.add_reward_game(gid, game, interval, cap)
        # Booster-Emote separat setzen (add_reward_game lässt es unangetastet).
        emoji = str(data.get("emoji", "")).strip().strip(":").strip()
        self.db.set_reward_game_emoji(gid, game, emoji or None)
        return web.json_response({"ok": True})

    async def api_games_remove(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        game = str(data.get("game", "")).strip()
        if game:
            self.db.remove_reward_game(gid, game)
        return web.json_response({"ok": True})

    async def api_games_alias(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        game = str(data.get("game", "")).strip()
        alias = str(data.get("alias", "")).strip()[:100]
        if not game or not alias:
            raise self._err(web.HTTPBadRequest, "fields")
        if not self.db.is_reward_game(gid, game):
            raise self._err(web.HTTPBadRequest, "unknown_game")
        if game.lower() == alias.lower():
            raise self._err(web.HTTPBadRequest, "same_alias")
        self.db.add_reward_game_alias(gid, game, alias)
        return web.json_response({"ok": True})

    async def api_games_alias_remove(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        alias = str(data.get("alias", "")).strip()
        if alias:
            self.db.remove_reward_game_alias(gid, alias)
        return web.json_response({"ok": True})

    async def api_games_request(self, request: web.Request) -> web.Response:
        """Nicht-Owner können ein Spiel anfragen; die WebOwner bekommen je eine DM."""
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        # Owner können Spiele direkt anlegen — für sie ist die Anfrage sinnlos.
        if self._can_edit_cards(sess):
            raise self._err(web.HTTPBadRequest, "already_editor")
        if not self.owner_ids:
            raise self._err(web.HTTPBadRequest, "no_owners")
        game = str(data.get("game", "")).strip()[:80]
        note = str(data.get("note", "")).strip()[:300]
        if not game:
            raise self._err(web.HTTPBadRequest, "fields")
        # Cooldown pro User (token-sparsam: bremst DM-Spam an die Owner aus).
        uid = sess["user_id"]
        now = time.time()
        if now - self._game_requests.get(uid, 0.0) < GAME_REQUEST_COOLDOWN:
            raise self._err(web.HTTPTooManyRequests, "cooldown")
        self._game_requests[uid] = now

        delivered = await self._notify_owners_game_request(gid, sess, game, note)
        if not delivered:
            # Kein Owner erreichbar -> Cooldown zurücksetzen, ehrlicher Fehler.
            self._game_requests.pop(uid, None)
            raise self._err(web.HTTPBadGateway, "no_delivery")
        return web.json_response({"ok": True})

    async def _notify_owners_game_request(
        self, gid: int, sess: dict, game: str, note: str
    ) -> int:
        """Schickt jedem WebOwner eine DM mit der Spiel-Anfrage. Gibt die Zahl
        erfolgreich zugestellter DMs zurück. Nutzt den Bot-Cache (get_user) und
        fällt nur bei Bedarf auf fetch_user zurück — minimale API-Last."""
        guild = self.bot.get_guild(gid)
        embed = discord.Embed(
            title="🎴 Neue Spiel-Anfrage",
            description=f"**{game}**",
            color=0x5865F2,
        )
        embed.add_field(name="Server", value=guild.name if guild else str(gid), inline=True)
        embed.add_field(
            name="Von", value=f'{sess["username"]} (`{sess["user_id"]}`)', inline=True
        )
        if note:
            embed.add_field(name="Notiz", value=note, inline=False)
        embed.set_footer(text="Über das Web-Panel angefragt")

        delivered = 0
        for oid in self.owner_ids:
            user = self.bot.get_user(oid)
            if user is None:
                try:
                    user = await self.bot.fetch_user(oid)
                except (discord.NotFound, discord.HTTPException):
                    continue
            try:
                await user.send(embed=embed)
                delivered += 1
            except discord.HTTPException:
                # Owner hat DMs gesperrt o.ä. — überspringen, andere bekommen sie trotzdem.
                continue
        return delivered

    async def api_user_feedback(self, request: web.Request) -> web.Response:
        """User können Bugs melden oder Feature-Wünsche an die WebOwner schicken."""
        sess, gid = self._require_member_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        if not self.owner_ids:
            raise self._err(web.HTTPBadRequest, "no_owners")

        kind = str(data.get("kind", "")).strip().lower()
        title = str(data.get("title", "")).strip()[:100]
        details = str(data.get("details", "")).strip()[:1000]
        if kind not in {"bug", "feature"}:
            raise self._err(web.HTTPBadRequest, "bad_kind")
        if not title or not details:
            raise self._err(web.HTTPBadRequest, "fields")

        uid = sess["user_id"]
        now = time.time()
        if now - self._feedback_requests.get(uid, 0.0) < GAME_REQUEST_COOLDOWN:
            raise self._err(web.HTTPTooManyRequests, "cooldown")
        self._feedback_requests[uid] = now

        delivered = await self._notify_owners_feedback(gid, sess, kind, title, details)
        if not delivered:
            self._feedback_requests.pop(uid, None)
            raise self._err(web.HTTPBadGateway, "no_delivery")
        return web.json_response({"ok": True})

    async def _notify_owners_feedback(
        self, gid: int, sess: dict, kind: str, title: str, details: str
    ) -> int:
        guild = self.bot.get_guild(gid)
        is_bug = kind == "bug"
        kind_label = "Bugreport" if is_bug else "Feature-Wunsch"
        embed = discord.Embed(
            title=f"{'🐞' if is_bug else '✨'} Neuer {kind_label}",
            description="Eine neue Meldung ist über das Webpanel eingegangen.",
            color=0xA855F7 if is_bug else 0xC084FC,
        )
        embed.add_field(name="Server", value=guild.name if guild else str(gid), inline=True)
        embed.add_field(name="Art", value=kind_label, inline=True)
        embed.add_field(
            name="Von", value=f'{sess["username"]} (`{sess["user_id"]}`)', inline=False
        )
        embed.add_field(name="Titel", value=title, inline=False)
        embed.add_field(name="Nachricht", value=details, inline=False)
        embed.set_footer(text="Yamikun Webpanel • Support & Wünsche")

        delivered = 0
        for oid in self.owner_ids:
            user = self.bot.get_user(oid)
            if user is None:
                try:
                    user = await self.bot.fetch_user(oid)
                except (discord.NotFound, discord.HTTPException):
                    continue
            try:
                await user.send(embed=embed)
                delivered += 1
            except discord.HTTPException:
                continue
        return delivered

    async def api_set_channel(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        raw = str(data.get("channel_id", "")).strip()
        self.db.set_card_channel(gid, int(raw) if raw.isdigit() else None)
        return web.json_response({"ok": True})

    # --- API: Yami-Karten -----------------------------------------------------

    async def api_yami(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        cards = self.db.list_server_cards(gid)  # (cid, name, rarity, url)
        return web.json_response({
            "can_edit": self._can_edit_cards(sess),
            "cards": [self._web_card(cid, name, rarity, url) for cid, name, rarity, url in cards],
        })

    async def api_yami_add(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        try:
            data = await request.post()
        except web.HTTPRequestEntityTooLarge:
            raise self._err(web.HTTPBadRequest, "size")
        self._check_csrf(sess, request, data)
        self._require_card_editor(sess)
        name = str(data.get("name", "")).strip()
        rarity = str(data.get("rarity", "common"))
        field = data.get("image")
        if not name or rarity not in RARITIES:
            raise self._err(web.HTTPBadRequest, "fields")
        if not isinstance(field, web.FileField):
            raise self._err(web.HTTPBadRequest, "noimg")
        ext = Path(field.filename or "").suffix.lower()
        if ext not in ALLOWED_EXT:
            raise self._err(web.HTTPBadRequest, "type")
        card_id = _yami_slug(name)
        if card_id is None:
            raise self._err(web.HTTPBadRequest, "name")

        yami_dir = STATIC_DIR / "yami"
        yami_dir.mkdir(parents=True, exist_ok=True)
        for old in yami_dir.glob(f"{card_id}.*"):
            old.unlink(missing_ok=True)
        dest = save_card_upload(field.file.read(), ext, yami_dir, card_id)
        ext = dest.suffix.lower()
        url = f"{self.base_url}/static/yami/{card_id}{ext}"
        self.db.add_server_card(gid, card_id, name, rarity, url)
        return web.json_response({"ok": True, "id": card_id})

    async def api_yami_delete(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        self._require_card_editor(sess)
        card_id = str(data.get("card_id", ""))
        if card_id:
            self.db.remove_server_card(gid, card_id)
            for old in (STATIC_DIR / "yami").glob(f"{card_id}.*"):
                old.unlink(missing_ok=True)
        return web.json_response({"ok": True})

    async def api_yami_replace(self, request: web.Request) -> web.Response:
        """Bild einer bestehenden Yami-Karte austauschen (Name/Seltenheit bleiben)."""
        sess, gid = self._require_guild_api(request)
        try:
            data = await request.post()
        except web.HTTPRequestEntityTooLarge:
            raise self._err(web.HTTPBadRequest, "size")
        self._check_csrf(sess, request, data)
        self._require_card_editor(sess)
        card_id = str(data.get("card_id", "")).strip()
        existing = next((c for c in self.db.list_server_cards(gid) if c[0] == card_id), None)
        if existing is None:
            raise self._err(web.HTTPBadRequest, "not_found")
        _cid, name, rarity, _url = existing
        field = data.get("image")
        if not isinstance(field, web.FileField):
            raise self._err(web.HTTPBadRequest, "noimg")
        ext = Path(field.filename or "").suffix.lower()
        if ext not in ALLOWED_EXT:
            raise self._err(web.HTTPBadRequest, "type")
        yami_dir = STATIC_DIR / "yami"
        yami_dir.mkdir(parents=True, exist_ok=True)
        for old in yami_dir.glob(f"{card_id}.*"):
            old.unlink(missing_ok=True)
        dest = save_card_upload(field.file.read(), ext, yami_dir, card_id)
        ext = dest.suffix.lower()
        url = f"{self.base_url}/static/yami/{card_id}{ext}?v={int(time.time())}"
        self.db.add_server_card(gid, card_id, name, rarity, url)
        return web.json_response({"ok": True, "url": url})

    # --- API: Economy ---------------------------------------------------------

    async def api_economy(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        # Coins/XP/Level sind global. scope=guild → nur Mitglieder dieses Servers,
        # scope=all → serverübergreifend alle.
        scope = request.query.get("scope", "guild")
        guild = self.bot.get_guild(gid)
        if scope == "all" or guild is None:
            board = self.db.leaderboard(gid, 50)  # rows: user_id, xp, level, coins
        else:
            # Nur Mitglieder dieses Servers – direkt in SQL gefiltert statt
            # 1000 Zeilen zu laden und in Python zu durchsuchen.
            board = self.db.leaderboard_members([m.id for m in guild.members], 50)
        leaderboard = []
        users = []
        for i, r in enumerate(board):
            uid = int(r["user_id"])
            name = self._uname(uid)
            users.append({"id": str(uid), "name": name})
            leaderboard.append({
                "rank": i + 1,
                "user_id": str(uid),
                "name": name,
                "avatar": self._avatar(uid),
                "level": int(r["level"]),
                "xp": int(r["xp"]),
                "coins": int(r["coins"]),
            })
        return web.json_response({"users": users, "leaderboard": leaderboard, "scope": scope})

    async def api_economy_coins(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        self._require_global_owner(sess)
        data = await request.json()
        self._check_csrf(sess, request, data)
        try:
            uid = int(str(data.get("user_id", "")).strip())
            amount = int(str(data.get("amount", "")).strip())
        except ValueError:
            raise self._err(web.HTTPBadRequest, "fields")
        # Plausible Grenze gegen Tippfehler/versehentliche Riesenbeträge.
        if abs(amount) > COIN_AMOUNT_MAX:
            raise self._err(web.HTTPBadRequest, "amount_range")
        if amount:
            self.db.add_coins(gid, uid, amount)
        return web.json_response({"ok": True})

    # --- API: Inventare -------------------------------------------------------

    async def api_inventory(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        collectors: dict[int, list[int]] = {}
        for u, c in self.db.list_card_collectors(gid):
            collectors.setdefault(u, [0, 0])[0] = c
        for u, c in self.db.list_server_collectors(gid):
            collectors.setdefault(u, [0, 0])[1] = c
        ordered = sorted(collectors.items(), key=lambda kv: kv[1][0] + kv[1][1], reverse=True)
        return web.json_response({
            "collectors": [
                {"user_id": str(uid), "name": self._uname(uid), "avatar": self._avatar(uid),
                 "game_count": g, "yami_count": y}
                for uid, (g, y) in ordered
            ]
        })

    async def api_inventory_user(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        try:
            uid = int(request.match_info["uid"])
        except (KeyError, ValueError):
            raise self._err(web.HTTPBadRequest, "bad_user")

        game_cat = {cid: (n, r, u) for cid, n, r, u, _g in self.db.list_custom_cards(gid)}
        yami_cat = {cid: (n, r, u) for cid, n, r, u in self.db.list_server_cards(gid)}
        game_coll = self.db.get_collection(gid, uid)
        yami_coll = self.db.get_server_collection(gid, uid)

        def _rar_index(rarity: str) -> int:
            return RARITY_ORDER.index(rarity) if rarity in RARITY_ORDER else 99

        def build(coll: dict[str, int], cat: dict) -> list[dict]:
            out = []
            for cid, count in coll.items():
                name, rarity, url = cat.get(cid, (cid, "common", None))
                out.append(self._web_card(cid, name, rarity, url, count=count))
            # Nach Seltenheit sortieren (seltenste zuerst), dann nach Name.
            out.sort(key=lambda c: (_rar_index(c["rarity"]), c["name"].lower()))
            return out

        return web.json_response({
            "user_id": str(uid),
            "name": self._uname(uid),
            "avatar": self._avatar(uid),
            "game_cards": build(game_coll, game_cat),
            "yami_cards": build(yami_coll, yami_cat),
        })

    async def api_inventory_remove(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        self._require_global_owner(sess)
        data = await request.json()
        self._check_csrf(sess, request, data)
        uid_raw = str(data.get("user_id", "")).strip()
        card_id = str(data.get("card_id", "")).strip()
        kind = str(data.get("kind", "game")).strip()
        if uid_raw.isdigit() and card_id:
            uid = int(uid_raw)
            if kind == "yami":
                self.db.remove_server_card_owned(gid, uid, card_id)
            else:
                self.db.remove_card(gid, uid, card_id)
        return web.json_response({"ok": True})

    # --- Reaction Roles -------------------------------------------------------

    @staticmethod
    def _emoji_display(emoji: str) -> dict:
        """Stored-Key -> Anzeige (Unicode-Char oder Custom mit CDN-Bild)."""
        name, sep, eid = emoji.rpartition(":")
        if sep and eid.isdigit():
            # .gif liefert das Discord-CDN auch für statische Emojis korrekt aus
            # (Standbild), animierte werden dadurch animiert dargestellt.
            return {"raw": emoji, "label": name,
                    "image": f"https://cdn.discordapp.com/emojis/{eid}.gif"}
        return {"raw": emoji, "label": emoji, "image": None}

    def _assignable_roles(self, guild) -> list[dict]:
        """Vergebbare Rollen (ohne @everyone/Bot-Rollen), höchste zuerst."""
        if guild is None:
            return []
        top = guild.me.top_role if guild.me else None
        out = []
        for r in sorted(guild.roles, key=lambda r: r.position, reverse=True):
            if r.is_default() or r.managed:
                continue
            out.append({
                "id": str(r.id),
                "name": r.name,
                "color": f"#{r.color.value:06X}" if r.color.value else None,
                "assignable": top is not None and r < top,
            })
        return out

    def _requirement_roles(self, guild) -> list[dict]:
        """Rollen, die als Voraussetzung wählbar sind: normale Rollen + die
        Server-Booster-Rolle (managed), aber keine Bot-Integrationsrollen.

        Der Bot vergibt diese Rolle nicht, sondern liest nur die Mitgliedschaft —
        daher ist die Hierarchie egal und auch die Booster-Rolle ist erlaubt.
        """
        if guild is None:
            return []
        booster = guild.premium_subscriber_role
        out = []
        for r in sorted(guild.roles, key=lambda r: r.position, reverse=True):
            if r.is_default() or (r.managed and r != booster):
                continue
            out.append({
                "id": str(r.id),
                "name": r.name,
                "color": f"#{r.color.value:06X}" if r.color.value else None,
            })
        return out

    async def api_reactionroles(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        guild = self.bot.get_guild(gid)
        bindings = []
        for channel_id, message_id, emoji, role_id, required_role_id in self.db.list_reaction_roles(gid):
            role = guild.get_role(role_id) if guild else None
            channel = guild.get_channel(channel_id) if guild else None
            req_role = guild.get_role(required_role_id) if guild and required_role_id else None
            bindings.append({
                "channel_id": str(channel_id),
                "channel_name": channel.name if channel else None,
                "message_id": str(message_id),
                "message_link": f"https://discord.com/channels/{gid}/{channel_id}/{message_id}",
                "emoji": self._emoji_display(emoji),
                "role_id": str(role_id),
                "role_name": role.name if role else None,
                "role_color": f"#{role.color.value:06X}" if role and role.color.value else None,
                "required_role_id": str(required_role_id) if required_role_id else None,
                "required_role_name": req_role.name if req_role else None,
            })
        emojis = (
            [{"key": f"{e.name}:{e.id}", "name": e.name, "image": str(e.url)} for e in guild.emojis]
            if guild else []
        )
        channels = [{"id": str(c.id), "name": c.name} for c in guild.text_channels] if guild else []
        return web.json_response({
            "bindings": bindings,
            "roles": self._assignable_roles(guild),
            "requirement_roles": self._requirement_roles(guild),
            "channels": channels,
            "emojis": emojis,
        })

    async def api_reactionroles_add(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        guild = self.bot.get_guild(gid)
        if guild is None:
            raise self._err(web.HTTPBadRequest, "no_guild")
        channel_id = str(data.get("channel_id", "")).strip()
        message_id = str(data.get("message_id", "")).strip()
        emoji = str(data.get("emoji", "")).strip()
        role_id = str(data.get("role_id", "")).strip()
        required_role_id = str(data.get("required_role_id", "")).strip()
        if not (channel_id.isdigit() and message_id.isdigit() and role_id.isdigit() and emoji):
            raise self._err(web.HTTPBadRequest, "fields")
        # Hierarchie serverseitig prüfen (wie der Slash-Command), damit keine
        # Bindung entsteht, die der Bot zur Laufzeit gar nicht vergeben kann.
        role = guild.get_role(int(role_id))
        top = guild.me.top_role if guild.me else None
        if role is None or (top is not None and role >= top):
            raise self._err(web.HTTPBadRequest, "role_unassignable")
        # Optionale Voraussetzungs-Rolle: muss existieren (Hierarchie egal, der Bot
        # liest sie nur). Leer/0 → keine Voraussetzung.
        req_id: int | None = None
        if required_role_id.isdigit() and int(required_role_id):
            if guild.get_role(int(required_role_id)) is None:
                raise self._err(web.HTTPBadRequest, "required_role_unknown")
            req_id = int(required_role_id)
        cog = self.bot.get_cog("ReactionRolesCog")
        if cog is None:
            raise self._err(web.HTTPBadRequest, "cog_missing")
        try:
            await cog.bind(guild, int(channel_id), int(message_id), emoji, int(role_id), req_id)
        except (discord.NotFound, ValueError):
            raise self._err(web.HTTPBadRequest, "message_not_found")
        except discord.Forbidden:
            raise self._err(web.HTTPForbidden, "forbidden_reaction")
        except discord.HTTPException:
            raise self._err(web.HTTPBadRequest, "invalid_emoji")
        return web.json_response({"ok": True})

    async def api_reactionroles_delete(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        message_id = str(data.get("message_id", "")).strip()
        emoji = str(data.get("emoji", "")).strip()
        if message_id.isdigit() and emoji:
            self.db.remove_reaction_role(gid, int(message_id), emoji)
        return web.json_response({"ok": True})

    # --- Willkommensnachrichten -----------------------------------------------

    async def api_welcome(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        guild = self.bot.get_guild(gid)
        cfg = self.db.get_welcome(gid)
        channels = [{"id": str(c.id), "name": c.name} for c in guild.text_channels] if guild else []
        return web.json_response({
            "enabled": cfg["enabled"],
            "channel_id": str(cfg["channel_id"]) if cfg["channel_id"] else None,
            "message": cfg["message"] or DEFAULT_WELCOME,
            "image": cfg.get("image"),
            "default_message": DEFAULT_WELCOME,
            "channels": channels,
            "placeholders": ["{user}", "{user_name}", "{server}", "{count}"],
        })

    async def api_welcome_save(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        ch = str(data.get("channel_id", "")).strip()
        enabled = bool(data.get("enabled"))
        channel_id = int(ch) if ch.isdigit() else None
        # Aktiviert ohne Channel ergibt keinen Sinn → ablehnen statt still speichern.
        if enabled and channel_id is None:
            raise self._err(web.HTTPBadRequest, "welcome_channel")
        message = str(data.get("message", "")).strip()
        self._require_len(message, MSG_MAX)
        self.db.set_welcome(gid, enabled, channel_id, message or None)
        return web.json_response({"ok": True})

    async def api_welcome_upload(self, request: web.Request) -> web.Response:
        """Welcome-Banner als Datei hochladen → unter static/welcome/<gid>.<ext>."""
        sess, gid = self._require_guild_api(request)
        try:
            data = await request.post()
        except web.HTTPRequestEntityTooLarge:
            raise self._err(web.HTTPBadRequest, "size")
        self._check_csrf(sess, request, data)
        field = data.get("image")
        if not isinstance(field, web.FileField):
            raise self._err(web.HTTPBadRequest, "noimg")
        ext = Path(field.filename or "").suffix.lower()
        if ext not in ALLOWED_EXT:
            raise self._err(web.HTTPBadRequest, "type")
        welcome_dir = STATIC_DIR / "welcome"
        welcome_dir.mkdir(parents=True, exist_ok=True)
        for old in welcome_dir.glob(f"{gid}.*"):
            old.unlink(missing_ok=True)
        (welcome_dir / f"{gid}{ext}").write_bytes(field.file.read())
        # Cache-Buster, damit der Browser ein ersetztes Bild sofort neu lädt.
        url = f"{self.base_url}/static/welcome/{gid}{ext}?v={int(time.time())}"
        self.db.set_welcome_image(gid, url)
        return web.json_response({"ok": True, "url": url})

    async def api_welcome_image(self, request: web.Request) -> web.Response:
        """Welcome-Bild per URL setzen oder (bei leerer URL) entfernen."""
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        url = str(data.get("url", "")).strip() or None
        # Nur echte http(s)-URLs zulassen (blockt javascript:/data:/file:).
        if url is not None and not self._is_http_url(url):
            raise self._err(web.HTTPBadRequest, "bad_url")
        if url is None:
            for old in (STATIC_DIR / "welcome").glob(f"{gid}.*"):
                old.unlink(missing_ok=True)
        self.db.set_welcome_image(gid, url)
        return web.json_response({"ok": True, "url": url})

    # --- Boost-Nachrichten ----------------------------------------------------

    async def api_boost(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        guild = self.bot.get_guild(gid)
        cfg = self.db.get_boost(gid)
        channels = [{"id": str(c.id), "name": c.name} for c in guild.text_channels] if guild else []
        return web.json_response({
            "enabled": cfg["enabled"],
            "channel_id": str(cfg["channel_id"]) if cfg["channel_id"] else None,
            "message": cfg["message"] or DEFAULT_BOOST,
            "mention": cfg["mention"],
            "image": cfg.get("image"),
            "default_message": DEFAULT_BOOST,
            "channels": channels,
            "placeholders": ["{user}", "{username}", "{displayName}", "{server}", "{boostCount}"],
        })

    async def api_boost_save(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        ch = str(data.get("channel_id", "")).strip()
        enabled = bool(data.get("enabled"))
        channel_id = int(ch) if ch.isdigit() else None
        # Aktiviert ohne Channel ergibt keinen Sinn → ablehnen statt still speichern.
        if enabled and channel_id is None:
            raise self._err(web.HTTPBadRequest, "boost_channel")
        message = str(data.get("message") or "").strip()
        self._require_len(message, MSG_MAX)
        mention = bool(data.get("mention", True))
        self.db.set_boost(gid, enabled, channel_id, message or None, mention)
        return web.json_response({"ok": True})

    async def api_boost_upload(self, request: web.Request) -> web.Response:
        """Boost-Banner als Datei hochladen → unter static/boost/<gid>.<ext>."""
        sess, gid = self._require_guild_api(request)
        try:
            data = await request.post()
        except web.HTTPRequestEntityTooLarge:
            raise self._err(web.HTTPBadRequest, "size")
        self._check_csrf(sess, request, data)
        field = data.get("image")
        if not isinstance(field, web.FileField):
            raise self._err(web.HTTPBadRequest, "noimg")
        ext = Path(field.filename or "").suffix.lower()
        if ext not in ALLOWED_EXT:
            raise self._err(web.HTTPBadRequest, "type")
        boost_dir = STATIC_DIR / "boost"
        boost_dir.mkdir(parents=True, exist_ok=True)
        for old in boost_dir.glob(f"{gid}.*"):
            old.unlink(missing_ok=True)
        (boost_dir / f"{gid}{ext}").write_bytes(field.file.read())
        # Cache-Buster, damit der Browser ein ersetztes Bild sofort neu lädt.
        url = f"{self.base_url}/static/boost/{gid}{ext}?v={int(time.time())}"
        self.db.set_boost_image(gid, url)
        return web.json_response({"ok": True, "url": url})

    async def api_boost_image(self, request: web.Request) -> web.Response:
        """Boost-Bild per URL setzen oder (bei leerer URL) entfernen."""
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        url = str(data.get("url", "")).strip() or None
        # Nur echte http(s)-URLs zulassen (blockt javascript:/data:/file:).
        if url is not None and not self._is_http_url(url):
            raise self._err(web.HTTPBadRequest, "bad_url")
        if url is None:
            boost_dir = STATIC_DIR / "boost"
            boost_dir.mkdir(parents=True, exist_ok=True)
            for old in boost_dir.glob(f"{gid}.*"):
                old.unlink(missing_ok=True)
        self.db.set_boost_image(gid, url)
        return web.json_response({"ok": True, "url": url})

    # --- Twitch Live ----------------------------------------------------------

    async def api_twitch(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        guild = self.bot.get_guild(gid)
        cfg = self.db.get_twitch_config(gid)
        channels = [{"id": str(c.id), "name": c.name} for c in guild.text_channels] if guild else []
        return web.json_response({
            "enabled": cfg["enabled"],
            "login": cfg["login"] or "",
            "channel_id": str(cfg["channel_id"]) if cfg["channel_id"] else None,
            "message": cfg["message"] or DEFAULT_TWITCH_MESSAGE,
            "mention_role_id": str(cfg["mention_role_id"]) if cfg["mention_role_id"] else None,
            "channels": channels,
            "roles": self._assignable_roles(guild),
            "placeholders": list(TWITCH_PLACEHOLDERS),
            "credentials_configured": bool(os.environ.get("TWITCH_CLIENT_ID") and os.environ.get("TWITCH_CLIENT_SECRET")),
        })

    async def api_twitch_save(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        enabled = bool(data.get("enabled"))
        login = normalize_login(str(data.get("login", "")))
        raw_channel = str(data.get("channel_id", "")).strip()
        channel_id = int(raw_channel) if raw_channel.isdigit() else None
        message = str(data.get("message", "")).strip()
        self._require_len(message, MSG_MAX)
        raw_role = str(data.get("mention_role_id", "")).strip()
        mention_role_id = int(raw_role) if raw_role.isdigit() else None
        guild = self.bot.get_guild(gid)
        if enabled and (not login or channel_id is None):
            raise self._err(web.HTTPBadRequest, "twitch_config")
        if guild is not None:
            if channel_id is not None and guild.get_channel(channel_id) not in guild.text_channels:
                raise self._err(web.HTTPBadRequest, "twitch_config")
            if mention_role_id is not None and guild.get_role(mention_role_id) is None:
                raise self._err(web.HTTPBadRequest, "twitch_config")
        self.db.set_twitch_config(gid, enabled, login, channel_id, message or None, mention_role_id)
        return web.json_response({"ok": True})

    # --- Auto-Rollen ----------------------------------------------------------

    async def api_autoroles(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        guild = self.bot.get_guild(gid)
        cfg = self.db.get_autoroles(gid)
        can_manage = bool(
            guild and guild.me and guild.me.guild_permissions.manage_roles
        )
        return web.json_response({
            "enabled": cfg["enabled"],
            "role_ids": [str(r) for r in cfg["role_ids"]],
            "roles": self._assignable_roles(guild),
            "can_manage_roles": can_manage,
        })

    async def api_autoroles_save(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        enabled = bool(data.get("enabled"))
        # `or []` fängt auch explizit gesendetes null ab (Default greift nur bei fehlendem Key).
        raw_ids = data.get("role_ids") or []
        # Nur gültige Ziffernstrings übernehmen, Rest ignorieren.
        role_ids = [int(x) for x in raw_ids if str(x).strip().isdigit()]
        # Nur Rollen speichern, die wirklich zu dieser Guild gehören (verhindert
        # das Einschleusen fremder IDs); bei nicht gecachter Guild keine Filterung.
        guild = self.bot.get_guild(gid)
        if guild is not None:
            valid = {r.id for r in guild.roles}
            role_ids = [rid for rid in role_ids if rid in valid]
        self.db.set_autoroles(gid, enabled, role_ids)
        return web.json_response({"ok": True})

    # --- Level-Up-Nachricht ---------------------------------------------------

    async def api_levelup(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        guild = self.bot.get_guild(gid)
        cfg = self.db.get_levelup_config(gid)
        channels = [{"id": str(c.id), "name": c.name} for c in guild.text_channels] if guild else []
        return web.json_response({
            "channel_id": str(cfg["channel_id"]) if cfg["channel_id"] else None,
            "message": cfg["message"] or "",
            "ping": cfg["ping"],
            "channels": channels,
            "placeholders": LEVELUP_PLACEHOLDERS,
        })

    async def api_levelup_save(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        ch = str(data.get("channel_id", "")).strip()
        message = str(data.get("message", "")).strip()
        self._require_len(message, MSG_MAX)
        self.db.set_levelup_config(
            gid,
            int(ch) if ch.isdigit() else None,
            (message or None),
            bool(data.get("ping", True)),
        )
        return web.json_response({"ok": True})

    # --- Bot-Serverprofil (Nickname + Avatar) ---------------------------------

    async def api_botprofile(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        guild = self.bot.get_guild(gid)
        stored = self.db.get_bot_profile(gid)
        me = guild.me if guild else None
        return web.json_response({
            "nick": (me.nick if me else None) or stored["nick"] or "",
            "avatar": stored["avatar"],
            "bot_name": self.bot.user.name if self.bot.user else "",
            "global_avatar": str(self.bot.user.display_avatar.url) if self.bot.user else None,
            "can_change_nick": bool(me and me.guild_permissions.change_nickname),
        })

    async def api_botprofile_nick(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        guild = self.bot.get_guild(gid)
        if guild is None or guild.me is None:
            raise self._err(web.HTTPBadRequest, "no_guild")
        nick = str(data.get("nick", "")).strip() or None
        if nick is not None:
            self._require_len(nick, NICK_MAX)
        try:
            await guild.me.edit(nick=nick, reason="Bot-Serverprofil über Webpanel geändert")
        except discord.Forbidden:
            raise self._err(web.HTTPForbidden, "forbidden_nick")
        except discord.HTTPException:
            raise self._err(web.HTTPBadRequest, "nick_failed")
        self.db.set_bot_nick(gid, nick)
        return web.json_response({"ok": True, "nick": nick or ""})

    async def _apply_guild_avatar(self, gid: int, data_uri: str | None) -> None:
        """Setzt (oder entfernt) den server-spezifischen Bot-Avatar via Roh-API.
        discord.py 2.x bietet dafür keinen High-Level-Call → direkter PATCH."""
        route = discord.http.Route("PATCH", "/guilds/{guild_id}/members/@me", guild_id=gid)
        await self.bot.http.request(route, json={"avatar": data_uri})

    async def api_botprofile_avatar(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        try:
            data = await request.post()
        except web.HTTPRequestEntityTooLarge:
            raise self._err(web.HTTPBadRequest, "size")
        self._check_csrf(sess, request, data)
        field = data.get("image")
        if not isinstance(field, web.FileField):
            raise self._err(web.HTTPBadRequest, "noimg")
        ext = Path(field.filename or "").suffix.lower()
        if ext not in _IMAGE_MIME:
            raise self._err(web.HTTPBadRequest, "type")
        raw = field.file.read()
        data_uri = f"data:{_IMAGE_MIME[ext]};base64,{base64.b64encode(raw).decode()}"
        try:
            await self._apply_guild_avatar(gid, data_uri)
        except discord.HTTPException as exc:
            logger.warning("Server-Avatar setzen fehlgeschlagen (Guild %s): %s", gid, exc)
            raise self._err(web.HTTPBadRequest, "avatar_unsupported")
        # Zur Anzeige im Panel zusätzlich lokal ablegen.
        av_dir = STATIC_DIR / "botavatar"
        av_dir.mkdir(parents=True, exist_ok=True)
        for old in av_dir.glob(f"{gid}.*"):
            old.unlink(missing_ok=True)
        (av_dir / f"{gid}{ext}").write_bytes(raw)
        url = f"{self.base_url}/static/botavatar/{gid}{ext}?v={int(time.time())}"
        self.db.set_bot_avatar(gid, url)
        return web.json_response({"ok": True, "url": url})

    async def api_botprofile_avatar_remove(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        try:
            await self._apply_guild_avatar(gid, None)
        except discord.HTTPException as exc:
            logger.warning("Server-Avatar entfernen fehlgeschlagen (Guild %s): %s", gid, exc)
            raise self._err(web.HTTPBadRequest, "avatar_unsupported")
        for old in (STATIC_DIR / "botavatar").glob(f"{gid}.*"):
            old.unlink(missing_ok=True)
        self.db.set_bot_avatar(gid, None)
        return web.json_response({"ok": True})

    # --- Nachricht senden -----------------------------------------------------

    # --- Hilfen für Nachrichten (Bild statisch hosten, Embed bauen) -----------

    @staticmethod
    def _announce_color_int(hexv: str) -> int:
        h = (hexv or "").strip().lstrip("#")
        if len(h) == 6:
            try:
                return int(h, 16)
            except ValueError:
                pass
        return 0x7C3AED

    @staticmethod
    def _norm_hex(hexv: str) -> str | None:
        h = (hexv or "").strip().lstrip("#")
        if len(h) == 6:
            try:
                int(h, 16)
                return f"#{h.upper()}"
            except ValueError:
                pass
        return None

    def _save_announce_image(self, gid: int, raw: bytes, ext: str) -> str:
        d = STATIC_DIR / "announce"
        d.mkdir(parents=True, exist_ok=True)
        name = f"{gid}-{secrets.token_hex(6)}{ext}"
        (d / name).write_bytes(raw)
        return f"{self.base_url}/static/announce/{name}?v={int(time.time())}"

    def _announce_image_path(self, url: str | None) -> Path | None:
        if not url or "/static/announce/" not in url:
            return None
        name = url.split("/static/announce/", 1)[1].split("?", 1)[0]
        return STATIC_DIR / "announce" / name

    def _announce_image_file(self, url: str | None):
        p = self._announce_image_path(url)
        if p is None or not p.exists():
            return None
        return discord.File(str(p), filename=p.name)

    def _read_upload_image(self, data, gid: int) -> str | None:
        """Hochgeladenes Bild (Feld 'image') statisch ablegen → URL (oder None)."""
        field = data.get("image")
        if not isinstance(field, web.FileField):
            return None
        ext = Path(field.filename or "").suffix.lower()
        if ext not in _IMAGE_MIME:
            raise self._err(web.HTTPBadRequest, "type")
        return self._save_announce_image(gid, field.file.read(), ext)

    @staticmethod
    def _parse_ping(data):
        role_ids = [int(x) for x in str(data.get("ping_roles", "")).split(",") if x.strip().isdigit()]
        ping_prefix = " ".join(f"<@&{rid}>" for rid in role_ids)
        mentions = discord.AllowedMentions(
            everyone=False, users=True,
            roles=[discord.Object(id=r) for r in role_ids] if role_ids else False,
        )
        return role_ids, ping_prefix, mentions

    def _build_announce_embed(self, title, content, color_hex, image_url):
        embed = discord.Embed(
            title=title or None, description=content or None,
            color=self._announce_color_int(color_hex or ""),
        )
        if image_url:
            embed.set_image(url=image_url)
        return embed

    async def api_announce(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        guild = self.bot.get_guild(gid)
        channels = [{"id": str(c.id), "name": c.name} for c in guild.text_channels] if guild else []
        roles = [
            {"id": r["id"], "name": r["name"], "color": r["color"]}
            for r in self._assignable_roles(guild)
        ]
        emojis = []
        if guild:
            for e in guild.emojis:
                emojis.append({
                    "name": e.name,
                    "code": f"<a:{e.name}:{e.id}>" if e.animated else f"<:{e.name}:{e.id}>",
                    "url": str(e.url),
                })
        messages = []
        for r in self.db.list_announcements(gid):
            ch = guild.get_channel(r["channel_id"]) if guild else None
            messages.append({
                "id": r["id"],
                "channel_id": str(r["channel_id"]),
                "channel_name": ch.name if ch else None,
                "as_embed": bool(r["as_embed"]),
                "title": r["title"] or "",
                "content": r["content"] or "",
                "color": r["color"] or "#7C3AED",
                "image": r["image_url"],
                "ping_roles": [x for x in (r["ping_roles"] or "").split(",") if x],
                "created_at": r["created_at"],
                "link": f"https://discord.com/channels/{gid}/{r['channel_id']}/{r['message_id']}",
            })
        return web.json_response({
            "channels": channels, "roles": roles, "emojis": emojis, "messages": messages,
        })

    async def api_announce_send(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        # Multipart, damit optional ein Bild mitgeschickt werden kann.
        try:
            data = await request.post()
        except web.HTTPRequestEntityTooLarge:
            raise self._err(web.HTTPBadRequest, "size")
        self._check_csrf(sess, request, data)
        guild = self.bot.get_guild(gid)
        if guild is None:
            raise self._err(web.HTTPBadRequest, "no_guild")
        ch_raw = str(data.get("channel_id", "")).strip()
        channel = guild.get_channel(int(ch_raw)) if ch_raw.isdigit() else None
        if not isinstance(channel, discord.abc.Messageable):
            raise self._err(web.HTTPBadRequest, "bad_channel")
        content = str(data.get("content", "")).replace("\\r\\n", "\n").replace("\\n", "\n").strip()
        title = str(data.get("title", "")).strip()
        color_hex = self._norm_hex(str(data.get("color", "")))
        role_ids, ping_prefix, mentions = self._parse_ping(data)
        image_url = self._read_upload_image(data, gid)
        if not content and not title and image_url is None and not ping_prefix:
            raise self._err(web.HTTPBadRequest, "empty")
        # Embed nur, wenn es auch Inhalt hätte — sonst normale (Ping-)Nachricht.
        as_embed = (str(data.get("as_embed", "")).lower() in ("1", "true", "on", "yes")
                    and bool(title or content or image_url))
        # Discord-Längenlimits erzwingen (sonst wirft Discord → generischer Fehler).
        self._require_len(title, EMBED_TITLE_MAX)
        self._require_len(content, EMBED_DESC_MAX if as_embed else MSG_MAX)
        try:
            if as_embed:
                embed = self._build_announce_embed(title, content, color_hex, image_url)
                msg = await channel.send(content=ping_prefix or None, embed=embed, allowed_mentions=mentions)
            else:
                body = f"{ping_prefix}\n{content}" if (ping_prefix and content) else (ping_prefix or content)
                file = self._announce_image_file(image_url)
                if file is not None:
                    msg = await channel.send(content=body or None, file=file, allowed_mentions=mentions)
                else:
                    msg = await channel.send(content=body, allowed_mentions=mentions)
        except discord.Forbidden:
            raise self._err(web.HTTPForbidden, "forbidden_channel")
        except discord.HTTPException:
            raise self._err(web.HTTPBadRequest, "send_failed")
        ann_id = self.db.add_announcement(
            gid, channel.id, msg.id, as_embed, title or None, content or None, color_hex,
            image_url, ",".join(str(r) for r in role_ids), int(time.time()),
        )
        return web.json_response({"ok": True, "id": ann_id})

    async def api_announce_edit(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        try:
            data = await request.post()
        except web.HTTPRequestEntityTooLarge:
            raise self._err(web.HTTPBadRequest, "size")
        self._check_csrf(sess, request, data)
        guild = self.bot.get_guild(gid)
        if guild is None:
            raise self._err(web.HTTPBadRequest, "no_guild")
        try:
            ann_id = int(str(data.get("id", "")).strip())
        except ValueError:
            raise self._err(web.HTTPBadRequest, "not_found")
        row = self.db.get_announcement(gid, ann_id)
        if row is None:
            raise self._err(web.HTTPBadRequest, "not_found")
        channel = guild.get_channel(row["channel_id"])
        if not isinstance(channel, discord.abc.Messageable):
            raise self._err(web.HTTPBadRequest, "bad_channel")
        try:
            message = await channel.fetch_message(row["message_id"])
        except discord.NotFound:
            self.db.delete_announcement(gid, ann_id)
            raise self._err(web.HTTPBadRequest, "msg_gone")
        except discord.HTTPException:
            raise self._err(web.HTTPBadRequest, "send_failed")

        content = str(data.get("content", "")).replace("\\r\\n", "\n").replace("\\n", "\n").strip()
        title = str(data.get("title", "")).strip()
        color_hex = self._norm_hex(str(data.get("color", "")))
        role_ids, ping_prefix, mentions = self._parse_ping(data)

        # Bild: neu hochgeladen / entfernen / behalten.
        new_url = self._read_upload_image(data, gid)
        remove_image = str(data.get("remove_image", "")).lower() in ("1", "true", "on", "yes")
        old_url = row["image_url"]
        if new_url:
            image_url = new_url
        elif remove_image:
            image_url = None
        else:
            image_url = old_url
        if image_url != old_url and old_url:  # alte Datei aufräumen
            p = self._announce_image_path(old_url)
            if p is not None:
                p.unlink(missing_ok=True)

        if not content and not title and image_url is None and not ping_prefix:
            raise self._err(web.HTTPBadRequest, "empty")
        as_embed = (str(data.get("as_embed", "")).lower() in ("1", "true", "on", "yes")
                    and bool(title or content or image_url))
        self._require_len(title, EMBED_TITLE_MAX)
        self._require_len(content, EMBED_DESC_MAX if as_embed else MSG_MAX)
        try:
            if as_embed:
                embed = self._build_announce_embed(title, content, color_hex, image_url)
                await message.edit(content=ping_prefix or None, embed=embed,
                                   attachments=[], allowed_mentions=mentions)
            else:
                body = f"{ping_prefix}\n{content}" if (ping_prefix and content) else (ping_prefix or content)
                file = self._announce_image_file(image_url)
                await message.edit(
                    content=body or None, embed=None,
                    attachments=[file] if file is not None else [],
                    allowed_mentions=mentions,
                )
        except discord.Forbidden:
            raise self._err(web.HTTPForbidden, "forbidden_channel")
        except discord.HTTPException:
            raise self._err(web.HTTPBadRequest, "send_failed")
        self.db.update_announcement(
            gid, ann_id, as_embed, title or None, content or None, color_hex, image_url,
            ",".join(str(r) for r in role_ids),
        )
        return web.json_response({"ok": True, "id": ann_id})

    async def api_announce_delete(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        try:
            ann_id = int(str(data.get("id", "")).strip())
        except ValueError:
            return web.json_response({"ok": True})
        row = self.db.get_announcement(gid, ann_id)
        if row is None:
            return web.json_response({"ok": True})
        if bool(data.get("delete_message")):
            guild = self.bot.get_guild(gid)
            channel = guild.get_channel(row["channel_id"]) if guild else None
            if isinstance(channel, discord.abc.Messageable):
                try:
                    msg = await channel.fetch_message(row["message_id"])
                    await msg.delete()
                except discord.HTTPException:
                    pass
        if row["image_url"]:
            p = self._announce_image_path(row["image_url"])
            if p is not None:
                p.unlink(missing_ok=True)
        self.db.delete_announcement(gid, ann_id)
        return web.json_response({"ok": True})

    # --- AutoMod / Honeypot ---------------------------------------------------

    async def api_automod(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        guild = self.bot.get_guild(gid)
        cfg = self.db.get_automod_config(gid)
        channels = [{"id": str(c.id), "name": c.name} for c in guild.text_channels] if guild else []
        return web.json_response({
            "enabled": cfg["enabled"],
            "delete_mass_mentions": cfg["delete_mass_mentions"],
            "exempt_role_ids": [str(rid) for rid in cfg["exempt_role_ids"]],
            "honeypot_channel_ids": [str(cid) for cid in cfg["honeypot_channel_ids"]],
            "honeypot_ban": cfg["honeypot_ban"],
            "honeypot_delete_seconds": cfg["honeypot_delete_seconds"],
            "channels": channels,
            "roles": self._requirement_roles(guild),
            "can_ban_members": bool(guild and guild.me and guild.me.guild_permissions.ban_members),
            "can_manage_messages": bool(guild and guild.me and guild.me.guild_permissions.manage_messages),
        })

    async def api_automod_save(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        guild = self.bot.get_guild(gid)
        raw_channels = data.get("honeypot_channel_ids") or []
        channel_ids = [int(x) for x in raw_channels if str(x).strip().isdigit()]
        if guild is not None:
            valid_channels = {c.id for c in guild.text_channels}
            channel_ids = [cid for cid in channel_ids if cid in valid_channels]
        raw_roles = data.get("exempt_role_ids") or []
        exempt_role_ids = [int(x) for x in raw_roles if str(x).strip().isdigit()]
        if guild is not None:
            valid_roles = {r.id for r in guild.roles}
            exempt_role_ids = [rid for rid in exempt_role_ids if rid in valid_roles]
        delete_seconds = int(data.get("honeypot_delete_seconds", 604800) or 0)
        delete_seconds = min(604800, max(0, delete_seconds))
        self.db.set_automod_config(
            gid,
            enabled=bool(data.get("enabled")),
            delete_mass_mentions=bool(data.get("delete_mass_mentions", True)),
            exempt_role_ids=exempt_role_ids,
            honeypot_channel_ids=channel_ids,
            honeypot_ban=bool(data.get("honeypot_ban", True)),
            honeypot_delete_seconds=delete_seconds,
        )
        return web.json_response({"ok": True})

    # --- Join-to-Create Voice -------------------------------------------------

    async def api_voice(self, request: web.Request) -> web.Response:
        _sess, gid = self._require_guild_api(request)
        guild = self.bot.get_guild(gid)
        cfg = self.db.get_voice_config(gid)
        lobby = guild.get_channel(cfg["lobby_id"]) if guild and cfg["lobby_id"] else None
        category = (
            guild.get_channel(cfg["category_id"])
            if guild and cfg["category_id"]
            else None
        )
        me = guild.me if guild else None
        permissions = me.guild_permissions if me else None
        active = []
        temporary_ids: set[int] = set()
        if guild:
            for row in self.db.list_temp_voice_channels(gid):
                temporary_ids.add(int(row["channel_id"]))
                channel = guild.get_channel(int(row["channel_id"]))
                if isinstance(channel, discord.VoiceChannel):
                    owner = guild.get_member(int(row["owner_id"]))
                    active.append({
                        "id": str(channel.id),
                        "name": channel.name,
                        "owner": owner.display_name if owner else str(row["owner_id"]),
                        "members": len([member for member in channel.members if not member.bot]),
                    })
        return web.json_response({
            "enabled": cfg["enabled"],
            "lobby_id": str(cfg["lobby_id"]) if cfg["lobby_id"] else None,
            "lobby_name": lobby.name if isinstance(lobby, discord.VoiceChannel) else None,
            "category_id": str(cfg["category_id"]) if cfg["category_id"] else None,
            "category_name": category.name if isinstance(category, discord.CategoryChannel) else None,
            "categories": [
                {"id": str(item.id), "name": item.name}
                for item in (guild.categories if guild else [])
            ],
            "voice_channels": [
                {
                    "id": str(item.id),
                    "name": item.name,
                    "category_id": str(item.category.id) if item.category else None,
                }
                for item in (guild.voice_channels if guild else [])
                if item.id not in temporary_ids
            ],
            "active_channels": active,
            "can_manage_channels": bool(permissions and permissions.manage_channels),
            "can_move_members": bool(permissions and permissions.move_members),
        })

    async def api_voice_save(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        guild = self.bot.get_guild(gid)
        if guild is None:
            raise self._err(web.HTTPNotFound, "guild_not_found")
        enabled = bool(data.get("enabled"))
        current = self.db.get_voice_config(gid)
        if enabled:
            raw_category = str(data.get("category_id", "")).strip()
            category_id = int(raw_category) if raw_category.isdigit() else None
            if category_id is not None and not isinstance(
                guild.get_channel(category_id), discord.CategoryChannel
            ):
                raise self._err(web.HTTPBadRequest, "invalid_voice_category")
            raw_lobby = str(data.get("lobby_id", "")).strip()
            lobby_id = int(raw_lobby) if raw_lobby.isdigit() else None
            if lobby_id is not None and not isinstance(
                guild.get_channel(lobby_id), discord.VoiceChannel
            ):
                raise self._err(web.HTTPBadRequest, "invalid_voice_lobby")
            raw_lobby_name = data.get("lobby_name")
            lobby_name = str(raw_lobby_name).strip()[:100] if raw_lobby_name else None
            if lobby_id is None and lobby_name is None:
                lobby_name = "➕ Eigenen Channel erstellen"
            voice_cog = self.bot.get_cog("VoiceMasterCog")
            if voice_cog is None or not hasattr(voice_cog, "ensure_voice_setup"):
                raise self._err(web.HTTPServiceUnavailable, "voice_cog_unavailable")
            try:
                _category, lobby = await voice_cog.ensure_voice_setup(  # type: ignore[attr-defined]
                    guild,
                    actor_label=f"WebPanel: {sess.get('username', sess['user_id'])}",
                    category_id=category_id,
                    lobby_id=lobby_id,
                    lobby_name=lobby_name,
                )
            except discord.Forbidden:
                raise self._err(web.HTTPForbidden, "bot_missing_voice_permissions")
            except discord.HTTPException:
                raise self._err(web.HTTPBadGateway, "discord_voice_setup_failed")
            return web.json_response({"ok": True, "lobby_id": str(lobby.id)})

        lobby = guild.get_channel(current["lobby_id"]) if current["lobby_id"] else None
        delete_lobby = bool(data.get("delete_lobby"))
        lobby_id = current["lobby_id"]
        if delete_lobby and isinstance(lobby, discord.VoiceChannel):
            try:
                await lobby.delete(reason=f"Voice-System im WebPanel deaktiviert durch {sess['user_id']}")
                lobby_id = None
            except discord.Forbidden:
                raise self._err(web.HTTPForbidden, "bot_missing_voice_permissions")
            except discord.HTTPException:
                raise self._err(web.HTTPBadGateway, "discord_voice_disable_failed")
        self.db.set_voice_config(
            gid,
            enabled=False,
            lobby_id=lobby_id,
            category_id=current["category_id"],
        )
        return web.json_response({"ok": True})

    # --- Audit-Log ------------------------------------------------------------

    async def api_audit(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        guild = self.bot.get_guild(gid)
        category = request.query.get("category") or None
        if category and category not in AUDIT_CATEGORIES:
            category = None
        try:
            limit = max(1, min(200, int(request.query.get("limit", "100"))))
        except ValueError:
            limit = 100

        entries = []
        for e in self.db.list_audit_log(gid, category, limit):
            ch = guild.get_channel(e["channel_id"]) if guild and e["channel_id"] else None
            entries.append({
                "id": e["id"],
                "ts": e["ts"],
                "category": e["category"],
                "event_type": e["event_type"],
                "summary": e["summary"],
                "detail": e["detail"],
                "actor": self._uname(e["actor_id"]) if e["actor_id"] else None,
                "target": self._uname(e["target_id"]) if e["target_id"] else None,
                "channel_name": ch.name if ch else None,
            })

        settings = [
            {"key": key, "label": label, "enabled": self.db.is_audit_enabled(gid, key)}
            for key, (label, _color) in AUDIT_CATEGORIES.items()
        ]
        chan_id = self.db.get_audit_channel(gid)
        channels = [{"id": str(c.id), "name": c.name} for c in guild.text_channels] if guild else []
        return web.json_response({
            "entries": entries,
            "settings": settings,
            "channel_id": str(chan_id) if chan_id else None,
            "channels": channels,
        })

    async def api_audit_settings(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        category = str(data.get("category", ""))
        if category not in AUDIT_CATEGORIES:
            raise self._err(web.HTTPBadRequest, "bad_category")
        self.db.set_audit_setting(gid, category, bool(data.get("enabled")))
        return web.json_response({"ok": True})

    async def api_audit_channel(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        raw = str(data.get("channel_id", "")).strip()
        self.db.set_audit_channel(gid, int(raw) if raw.isdigit() else None)
        return web.json_response({"ok": True})

    async def api_audit_clear(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        self.db.clear_audit_log(gid)
        return web.json_response({"ok": True})

    # --- Ticket-System --------------------------------------------------------

    async def api_tickets(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        guild = self.bot.get_guild(gid)
        cfg = self.db.get_ticket_config(gid)
        cats = self.db.list_ticket_categories(gid)
        channels = [{"id": str(c.id), "name": c.name} for c in guild.text_channels] if guild else []
        panel = guild.get_channel(cfg["panel_channel_id"]) if guild and cfg["panel_channel_id"] else None
        return web.json_response({
            "enabled": cfg["enabled"],
            "panel_channel_id": str(cfg["panel_channel_id"]) if cfg["panel_channel_id"] else None,
            "panel_channel_name": panel.name if panel else None,
            "support_role_id": str(cfg["support_role_id"]) if cfg["support_role_id"] else None,
            "log_channel_id": str(cfg["log_channel_id"]) if cfg["log_channel_id"] else None,
            "title": cfg["title"],
            "text": cfg["text"],
            "default_title": self.db.DEFAULT_TICKET_TITLE,
            "default_text": self.db.DEFAULT_TICKET_TEXT,
            "categories": [
                {"id": c["id"], "label": c["label"], "emoji": c["emoji"], "description": c["description"]}
                for c in cats
            ],
            "open_count": len(self.db.list_open_tickets(gid)),
            "tickets": [
                {
                    "number": t["number"],
                    "category": t["category_label"],
                    "opener": self._uname(t["opener_id"]),
                    "claimed_by": self._uname(t["claimed_by"]) if t["claimed_by"] else None,
                    "status": t["status"],
                    "created_at": t["created_at"],
                    "thread_link": f"https://discord.com/channels/{gid}/{t['thread_id']}",
                }
                for t in self.db.list_tickets(gid, 200)
            ],
            "transcripts": [
                {
                    "token": r["token"],
                    "number": r["number"],
                    "category": r["category_label"],
                    "opener": r["opener_name"],
                    "closed_by": r["closed_by_name"],
                    "closed_at": r["closed_at"],
                    "messages": r["message_count"],
                    "url": f"{self.base_url}/t/{r['token']}" if self.base_url else f"/t/{r['token']}",
                }
                for r in self.db.list_ticket_transcripts(gid, 100)
            ],
            "roles": self._assignable_roles(guild),
            "channels": channels,
        })

    async def api_tickets_config(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        role = str(data.get("support_role_id", "")).strip()
        log = str(data.get("log_channel_id", "")).strip()
        title = str(data.get("title", "")).strip()
        text = str(data.get("text", "")).strip()
        # Panel ist ein Embed → Titel/Beschreibung an Discord-Limits halten.
        self._require_len(title, EMBED_TITLE_MAX)
        self._require_len(text, EMBED_DESC_MAX)
        self.db.set_ticket_config(
            gid,
            support_role_id=int(role) if role.isdigit() else None,
            log_channel_id=int(log) if log.isdigit() else None,
            title=(title or self.db.DEFAULT_TICKET_TITLE),
            text=(text or self.db.DEFAULT_TICKET_TEXT),
        )
        guild = self.bot.get_guild(gid)
        cog = self.bot.get_cog("TicketCog")
        if guild and cog:
            await cog.refresh_panel(guild)
        return web.json_response({"ok": True})

    async def api_tickets_panel(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        guild = self.bot.get_guild(gid)
        cog = self.bot.get_cog("TicketCog")
        if guild is None or cog is None:
            raise self._err(web.HTTPBadRequest, "no_guild")
        raw = str(data.get("channel_id", "")).strip()
        channel = guild.get_channel(int(raw)) if raw.isdigit() else None
        if not isinstance(channel, discord.TextChannel):
            raise self._err(web.HTTPBadRequest, "bad_channel")
        try:
            await cog.post_panel(guild, channel)
        except discord.Forbidden:
            raise self._err(web.HTTPForbidden, "forbidden_channel")
        return web.json_response({"ok": True})

    async def api_tickets_disable(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        guild = self.bot.get_guild(gid)
        cfg = self.db.get_ticket_config(gid)
        if guild and cfg["panel_channel_id"] and cfg["panel_message_id"]:
            ch = guild.get_channel(cfg["panel_channel_id"])
            if isinstance(ch, discord.TextChannel):
                try:
                    msg = await ch.fetch_message(cfg["panel_message_id"])
                    await msg.delete()
                except discord.HTTPException:
                    pass
        self.db.set_ticket_panel(gid, None, None)
        self.db.set_ticket_config(gid, enabled=False)
        return web.json_response({"ok": True})

    async def api_tickets_cat_add(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        label = str(data.get("label", "")).strip()[:100]
        if not label:
            raise self._err(web.HTTPBadRequest, "fields")
        if len(self.db.list_ticket_categories(gid)) >= 25:
            raise self._err(web.HTTPBadRequest, "too_many")
        emoji = str(data.get("emoji", "")).strip() or None
        desc = str(data.get("description", "")).strip()[:100] or None
        self.db.add_ticket_category(gid, label, emoji, desc)
        guild = self.bot.get_guild(gid)
        cog = self.bot.get_cog("TicketCog")
        if guild and cog:
            await cog.refresh_panel(guild)
        return web.json_response({"ok": True})

    async def api_tickets_cat_remove(self, request: web.Request) -> web.Response:
        sess, gid = self._require_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        try:
            cat_id = int(data.get("id"))
        except (TypeError, ValueError):
            raise self._err(web.HTTPBadRequest, "fields")
        self.db.remove_ticket_category(gid, cat_id)
        guild = self.bot.get_guild(gid)
        cog = self.bot.get_cog("TicketCog")
        if guild and cog:
            await cog.refresh_panel(guild)
        return web.json_response({"ok": True})

    # --- Öffentliche Transcript-Ansicht (/t/<token>) --------------------------

    async def h_transcript(self, request: web.Request) -> web.Response:
        token = request.match_info.get("token", "")
        row = self.db.get_ticket_transcript(token)
        if not row:
            return web.Response(
                text=self._transcript_error_html(), status=404, content_type="text/html"
            )
        guild = self.bot.get_guild(row["guild_id"])
        page = self._render_transcript_html(row, guild.name if guild else "Server")
        return web.Response(text=page, content_type="text/html")

    @staticmethod
    def _md_inline(text: str) -> str:
        """HTML-sicheres Mini-Markdown: escapen, dann **fett**/*kursiv*/`code`/Links/Zeilen."""
        s = html.escape(text)
        s = re.sub(r"```([^`]+)```", r"<pre>\1</pre>", s, flags=re.S)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", s)
        s = re.sub(r"__([^_]+)__", r"<u>\1</u>", s)
        s = re.sub(
            r"(https?://[^\s<]+)",
            r'<a href="\1" target="_blank" rel="noreferrer noopener">\1</a>',
            s,
        )
        return s.replace("\n", "<br>")

    def _render_transcript_html(self, row: dict, guild_name: str) -> str:
        try:
            messages = json.loads(row["data"])
        except (ValueError, TypeError):
            messages = []
        when = time.strftime("%d.%m.%Y %H:%M", time.localtime(row["closed_at"]))
        rows_html: list[str] = []
        for m in messages:
            ts = time.strftime("%d.%m.%Y %H:%M", time.localtime(m.get("ts", 0)))
            name = html.escape(str(m.get("author_name", "?")))
            avatar = html.escape(str(m.get("avatar", "")))
            bot_tag = '<span class="bot">BOT</span>' if m.get("bot") else ""
            body = self._md_inline(m.get("content", "")) if m.get("content") else ""
            atts = []
            for a in m.get("attachments", []):
                url = html.escape(str(a.get("url", "")))
                if a.get("is_image"):
                    atts.append(f'<a href="{url}" target="_blank" rel="noreferrer noopener">'
                                f'<img class="att-img" src="{url}" alt=""></a>')
                else:
                    nm = html.escape(str(a.get("name", "Datei")))
                    atts.append(f'<a class="att-file" href="{url}" target="_blank" '
                                f'rel="noreferrer noopener">📎 {nm}</a>')
            atts_html = f'<div class="atts">{"".join(atts)}</div>' if atts else ""
            body_html = f'<div class="content">{body}</div>' if body else ""
            rows_html.append(
                f'<div class="msg"><img class="av" src="{avatar}" alt="">'
                f'<div class="mc"><div class="meta"><span class="name">{name}</span>'
                f'{bot_tag}<span class="ts">{ts}</span></div>{body_html}{atts_html}</div></div>'
            )
        body_block = "\n".join(rows_html) or '<div class="empty">Keine Nachrichten im Transcript.</div>'
        cat = html.escape(str(row["category_label"] or "Support"))
        opener = html.escape(str(row["opener_name"] or "?"))
        closer = html.escape(str(row["closed_by_name"] or "?"))
        server = html.escape(guild_name)
        num = f"{row['number']:04d}"
        return _TRANSCRIPT_PAGE.format(
            num=num, cat=cat, server=server, opener=opener, closer=closer,
            when=when, count=row["message_count"], body=body_block,
        )

    @staticmethod
    def _transcript_error_html() -> str:
        return (
            "<!doctype html><html lang='de'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Transcript nicht gefunden</title>"
            "<style>body{background:#0b0b12;color:#e8e8f0;font-family:system-ui,sans-serif;"
            "display:grid;place-items:center;height:100vh;margin:0;text-align:center}"
            "h1{font-size:1.4rem}p{color:#9a9ab0}</style></head><body><div>"
            "<h1>🎫 Transcript nicht gefunden</h1>"
            "<p>Der Link ist ungültig oder das Transcript wurde entfernt.</p>"
            "</div></body></html>"
        )

    # --- User-Dashboard (eigene Daten) ----------------------------------------

    async def api_user_dashboard(self, request: web.Request) -> web.Response:
        sess, gid = self._require_member_guild_api(request)
        uid = sess["user_id"]
        guild = self.bot.get_guild(gid)

        def _ri(rarity: str) -> int:
            return RARITY_ORDER.index(rarity) if rarity in RARITY_ORDER else 99

        # Spiel-Sammelkarten als vollständige Albumseiten. Anders als die alte
        # Grid-Ansicht enthält jede Seite auch unentdeckte Karten (count=0).
        by_game: dict[str, dict] = {}
        for cid, n, r, u, g in self.db.list_custom_cards(gid):
            by_game.setdefault(g or "", {})[cid] = (n, r, u)
        owned = self.db.get_collection(gid, uid)
        owned_packs = self.db.list_packs(gid, uid)
        games = []
        for g, cat in sorted(by_game.items(), key=lambda kv: (kv[0] == "", kv[0].lower())):
            cards = [
                self._web_card(cid, *meta, count=owned.get(cid, 0))
                for cid, meta in cat.items()
            ]
            cards.sort(key=lambda c: (_ri(c["rarity"]), c["name"].lower()))
            display_game = g or "Ohne Spiel"
            games.append({
                "game": display_game,
                "cards": cards,
                "fusable": fusable_counts(cat, owned),
                "booster_count": owned_packs.get(_game_pack_type(g), 0) if g else 0,
            })

        # Yami-Karten
        yami_cat = {cid: (n, r, u) for cid, n, r, u in self.db.list_server_cards(gid)}
        yami_owned = self.db.get_server_collection(gid, uid)
        yami_cards = [self._web_card(cid, *yami_cat.get(cid, (cid, "common", None)), count=cnt)
                      for cid, cnt in yami_owned.items()]
        yami_cards.sort(key=lambda c: (_ri(c["rarity"]), c["name"].lower()))

        # Stats
        from cogs.leveling import level_from_total, xp_needed
        row = self.db.get_user(gid, uid)
        total_xp = int(row["xp"])
        level, into = level_from_total(total_xp)
        coins = int(row["coins"])

        return web.json_response({
            "guild": {"id": str(gid), "name": guild.name if guild else ""},
            "username": sess["username"],
            "avatar": sess.get("avatar"),
            "is_admin": gid in sess.get("guilds", {}),
            "stats": {
                "level": level, "xp_into": into, "xp_needed": xp_needed(level),
                "total_xp": total_xp, "coins": coins,
            },
            "games": games,
            "card_album": {
                "shards": self.db.get_card_shards(gid, uid),
                "booster_cost": GAME_BOOSTER_SHARD_COST,
                "dismantle_rewards": CARD_SHARD_REWARDS,
            },
            "yami": {"cards": yami_cards, "fusable": fusable_counts(yami_cat, yami_owned)},
            "fusable_rarities": FUSABLE,
        })

    async def api_user_card_dismantle(self, request: web.Request) -> web.Response:
        """Zerlegt ein Spielkarten-Duplikat; das letzte Exemplar bleibt erhalten."""
        sess, gid = self._require_member_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        uid = int(sess["user_id"])
        card_id = str(data.get("card_id", "")).strip()
        catalog = {
            cid: (name, rarity, game)
            for cid, name, rarity, _url, game in self.db.list_custom_cards(gid)
        }
        if card_id not in catalog:
            raise self._err(web.HTTPNotFound, "card_not_found")
        name, rarity, game = catalog[card_id]
        reward = CARD_SHARD_REWARDS.get(rarity, 0)
        ok, shards, remaining = self.db.dismantle_card_duplicate(gid, uid, card_id, reward)
        if not ok:
            raise self._err(web.HTTPBadRequest, "no_duplicate")
        return web.json_response({
            "ok": True,
            "card": {"id": card_id, "name": name, "rarity": rarity, "game": game or ""},
            "reward": reward,
            "shards": shards,
            "remaining": remaining,
        })

    async def api_user_booster_exchange(self, request: web.Request) -> web.Response:
        """Tauscht Arkansplitter gegen ein vorhandenes Spiel-Booster-Inventaritem."""
        sess, gid = self._require_member_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        uid = int(sess["user_id"])
        game = str(data.get("game", "")).strip().lower()
        if not game or not self.db.list_custom_cards_for_game(gid, game):
            raise self._err(web.HTTPNotFound, "game_not_found")
        ok, shards, booster_count = self.db.exchange_card_shards_for_pack(
            gid, uid, _game_pack_type(game), GAME_BOOSTER_SHARD_COST,
        )
        if not ok:
            raise self._err(web.HTTPBadRequest, "not_enough_shards")
        return web.json_response({
            "ok": True,
            "game": game,
            "cost": GAME_BOOSTER_SHARD_COST,
            "shards": shards,
            "booster_count": booster_count,
        })

    async def api_user_achievements(self, request: web.Request) -> web.Response:
        """Eigene Achievements plus Vergleichsdaten bestätigter /friend-add-Freunde."""
        sess, gid = self._require_member_guild_api(request)
        uid = int(sess["user_id"])
        guild = self.bot.get_guild(gid)

        def _identity(user_id: int) -> tuple[str, str | None]:
            user = (guild.get_member(user_id) if guild else None) or self.bot.get_user(user_id)
            if user is None:
                return f"User {user_id}", None
            return user.display_name, user.display_avatar.url

        own_items = user_achievement_payload(self.db, gid, uid)
        friends = []
        for friend_id, friendship_xp in self.db.list_friends(gid, uid):
            name, avatar = _identity(friend_id)
            # Geheime Achievements sind privat – auch nach ihrer Freischaltung.
            items = friend_achievement_payload(self.db, gid, friend_id)
            friends.append({
                "id": str(friend_id),
                "username": name,
                "avatar": avatar,
                "friendship_xp": friendship_xp,
                "unlocked_count": sum(1 for item in items if item["unlocked"]),
                "achievements": items,
            })

        return web.json_response({
            "guild": {"id": str(gid), "name": guild.name if guild else ""},
            "user": {
                "id": str(uid),
                "username": sess["username"],
                "avatar": sess.get("avatar"),
                "unlocked_count": sum(1 for item in own_items if item["unlocked"]),
                "achievements": own_items,
            },
            "friends": friends,
        })

    async def api_user_fuse(self, request: web.Request) -> web.Response:
        sess, gid = self._require_member_guild_api(request)
        data = await request.json()
        self._check_csrf(sess, request, data)
        uid = sess["user_id"]
        kind = str(data.get("kind", ""))
        rarity = str(data.get("rarity", ""))
        if kind == "game":
            res = fuse_game(self.db, gid, uid, str(data.get("game", "")), rarity)
        elif kind == "yami":
            res = fuse_yami(self.db, gid, uid, rarity)
        else:
            raise self._err(web.HTTPBadRequest, "bad_kind")
        if not res["ok"]:
            raise self._err(web.HTTPBadRequest, res["error"])
        r = res["result"]
        r["rarity_label"] = _rarity_label(r["rarity"])
        r["color"] = _color(r["rarity"])
        return web.json_response({"ok": True, "result": r})

    # --- SPA-Auslieferung -----------------------------------------------------

    async def h_spa(self, request: web.Request) -> web.StreamResponse:
        """Liefert statische Frontend-Dateien bzw. index.html (Client-Routing).

        Unbekannte /api-Pfade dürfen NICHT die index.html bekommen — sonst würden
        Tippfehler in API-Aufrufen als HTML-200 zurückkommen.
        """
        rel = request.match_info.get("tail", "")
        if rel.startswith("api/"):
            raise self._err(web.HTTPNotFound, "not_found")
        # Fehlende Build-Assets (z. B. ein veralteter Chunk nach einem Deploy)
        # dürfen NICHT die index.html bekommen — sonst erhält der Browser HTML
        # statt JS und die Lazy-Imports brechen still. Lieber sauber 404.
        if rel.startswith("appassets/"):
            candidate = (FRONTEND_DIST / rel).resolve()
            if (FRONTEND_DIST in candidate.parents) and candidate.is_file():
                return web.FileResponse(candidate)
            raise self._err(web.HTTPNotFound, "not_found")

        if FRONTEND_DIST.is_dir():
            if rel:
                candidate = (FRONTEND_DIST / rel).resolve()
                # Path-Traversal verhindern: muss innerhalb von dist liegen.
                if (candidate == FRONTEND_DIST or FRONTEND_DIST in candidate.parents) \
                        and candidate.is_file():
                    return web.FileResponse(candidate)
            index = FRONTEND_DIST / "index.html"
            if index.is_file():
                return web.FileResponse(index)

        return web.Response(text=PLACEHOLDER_HTML, content_type="text/html")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WebPanelCog(bot))

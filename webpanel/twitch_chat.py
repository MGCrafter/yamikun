"""Independent Twitch login, owner-only dashboard and signed EventSub ingress."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
from datetime import datetime
from urllib.parse import urlencode

import aiohttp
from aiohttp import web

from twitch_chat.commands import COMMANDS, normalize_text
from twitch_chat.service import OAUTH, SCOPES, Service, TwitchError
from twitch_chat.store import DEFAULTS

SESSION = "yami_twitch_session"
STATE = "yami_twitch_state"
TTL = 7 * 86400


def error(status: int, code: str):
    return web.json_response({"error": code}, status=status)


def settings(data: dict) -> dict:
    """Strict whitelist; booleans must not pass as integers."""
    # Older browser tabs may omit the new field; save() preserves existing timers.
    if isinstance(data, dict) and "auto_messages" not in data:
        data = {**data, "auto_messages": []}
    if not isinstance(data, dict) or set(data) != set(DEFAULTS):
        raise ValueError("settings")
    for key in ("social_enabled", "gambling_enabled", "automod_enabled", "block_links", "block_caps", "block_spam"):
        if type(data[key]) is not bool:
            raise ValueError(key)
    for key, low, high in (("command_cooldown", 2, 120), ("max_bet", 1, 100000), ("daily_coins", 1, 10000), ("timeout_seconds", 0, 1209600)):
        if type(data[key]) is not int or not low <= data[key] <= high:
            raise ValueError(key)
    if not isinstance(data["prefix"], str) or not re.fullmatch(r"[!?.$]{1,3}", data["prefix"]):
        raise ValueError("prefix")
    words = data["blocked_words"]
    if not isinstance(words, list) or len(words) > 100 or any(not isinstance(w, str) or not 1 <= len(w.strip()) <= 80 or not normalize_text(w).strip() for w in words):
        raise ValueError("blocked_words")
    messages = data["auto_messages"]
    if not isinstance(messages, list) or len(messages) > 20:
        raise ValueError("auto_messages")
    cleaned, ids = [], set()
    for message in messages:
        if not isinstance(message, dict) or set(message) != {"id", "name", "text", "enabled", "interval_minutes", "min_messages", "live_only"}:
            raise ValueError("auto_messages")
        mid = message["id"]
        if not isinstance(mid, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", mid) or mid in ids:
            raise ValueError("auto_messages")
        ids.add(mid)
        for key in ("enabled", "live_only"):
            if type(message[key]) is not bool:
                raise ValueError("auto_messages")
        for key, low, high in (("interval_minutes", 1, 1440), ("min_messages", 0, 1000)):
            if type(message[key]) is not int or not low <= message[key] <= high:
                raise ValueError("auto_messages")
        for key, limit in (("name", 60), ("text", 500)):
            value = message[key]
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit or not normalize_text(value).strip():
                raise ValueError("auto_messages")
            if any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError("auto_messages")
        cleaned.append({**message, "name": message["name"].strip(), "text": message["text"].strip()})
    return {**data, "blocked_words": list(dict.fromkeys(w.strip() for w in words)), "auto_messages": cleaned}


class TwitchChatPanel:
    def __init__(self, webpanel):
        self.panel = webpanel
        self.service = Service(webpanel.db.conn, webpanel.base_url)
        self.store = self.service.store
        self.secure = webpanel.base_url.startswith("https://")

    def register(self, app):
        app.add_routes([
            web.get("/twitch/login", self.login), web.get("/twitch/callback", self.callback),
            web.post("/twitch/eventsub", self.eventsub),
            web.get("/api/twitch/me", self.me), web.post("/api/twitch/settings", self.save),
            web.post("/api/twitch/logout", self.logout),
            web.post("/api/twitch/discord-link", self.discord_link),
        ])

    def session(self, request, *, mutate=False):
        token = request.cookies.get(SESSION, "")
        row = self.store.conn.execute("SELECT * FROM twitch_chat_sessions WHERE token_hash=? AND expires>?", (self.store.digest(token), time.time())).fetchone() if token else None
        if not row or not self.store.account(row["user_id"]):
            raise web.HTTPUnauthorized(text='{"error":"unauthorized"}', content_type="application/json")
        if mutate and not secrets.compare_digest(request.headers.get("X-CSRF-Token", "").encode(), row["csrf"].encode()):
            raise web.HTTPForbidden(text='{"error":"bad_csrf"}', content_type="application/json")
        return dict(row)

    def redirect(self, path):
        response = web.HTTPFound(path, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
        response.del_cookie(STATE, path="/twitch")
        return response

    async def login(self, request):
        if self.service.missing or self.service.http is None:
            return self.redirect("/twitch?error=not_configured")
        role = "bot" if request.query.get("bot") == "1" else "channel"
        state = secrets.token_urlsafe(32)
        self.store.cleanup()
        with self.store.conn:
            self.store.conn.execute("INSERT INTO twitch_chat_oauth VALUES(?,?,?)", (self.store.digest(state), role, time.time() + 600))
        response = web.HTTPFound(OAUTH + "/authorize?" + urlencode({
            "client_id": self.service.client_id, "redirect_uri": self.service.base_url + "/twitch/callback",
            "response_type": "code", "scope": " ".join(sorted(SCOPES[role])), "state": state, "force_verify": "true",
        }), headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
        response.set_cookie(STATE, state, max_age=600, path="/twitch", httponly=True, secure=self.secure, samesite="Lax")
        return response

    async def callback(self, request):
        state = request.query.get("state", "")
        if not state or not secrets.compare_digest(state.encode(), request.cookies.get(STATE, "").encode()):
            return self.redirect("/twitch?error=state")
        with self.store.conn:
            row = self.store.conn.execute("SELECT * FROM twitch_chat_oauth WHERE state_hash=? AND expires>?", (self.store.digest(state), time.time())).fetchone()
            self.store.conn.execute("DELETE FROM twitch_chat_oauth WHERE state_hash=?", (self.store.digest(state),))
        if not row:
            return self.redirect("/twitch?error=state")
        if request.query.get("error") or not request.query.get("code"):
            return self.redirect("/twitch?error=denied")
        try:
            uid = await self.service.authorize(request.query["code"], row["role"])
        except TwitchError as exc:
            return self.redirect("/twitch?error=" + exc.code)
        except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, ValueError):
            return self.redirect("/twitch?error=twitch_unavailable")
        if row["role"] == "bot":
            return self.redirect("/twitch?connected=bot")
        token = secrets.token_urlsafe(32)
        with self.store.conn:
            # Rotate the browser session after every successful login.
            self.store.conn.execute("DELETE FROM twitch_chat_sessions WHERE token_hash=?", (self.store.digest(request.cookies.get(SESSION, "")),))
            self.store.conn.execute("INSERT INTO twitch_chat_sessions VALUES(?,?,?,?)", (self.store.digest(token), uid, secrets.token_urlsafe(24), time.time() + TTL))
        response = self.redirect("/twitch")
        response.set_cookie(SESSION, token, max_age=TTL, path="/", httponly=True, secure=self.secure, samesite="Lax")
        return response

    async def me(self, request):
        bot = self.store.account(self.service.bot_id, "bot")
        result = {"authenticated": False, "configured": not self.service.missing,
                  "bot_ready": bool(bot), "bot_login": bot["login"] if bot else None,
                  "can_setup_bot": False,
                  "commands": [{"usage": u, "description": d} for u, d in COMMANDS]}
        try:
            sess = self.session(request)
        except web.HTTPUnauthorized:
            return web.json_response(result)
        uid = sess["user_id"]
        account = self.store.account(uid)
        link = self.store.conn.execute("SELECT discord_id,discord_name FROM twitch_chat_links WHERE twitch_id=?", (uid,)).fetchone()
        discord = self.panel._session(request)
        result.update({"authenticated": True, "csrf": sess["csrf"],
                       "can_setup_bot": uid == self.service.bot_id,
                       "user": {"id": uid, "login": account["login"], "display_name": account["display_name"]},
                       "discord_link": {"id": str(link[0]), "name": link[1]} if link else None,
                       "discord_session": {"id": str(discord["user_id"]), "name": discord["username"]} if discord else None,
                       **self.store.dashboard(uid)})
        return web.json_response(result)

    async def save(self, request):
        sess = self.session(request, mutate=True)
        try:
            data = await request.json()
            if not isinstance(data, dict) or set(data) != {"enabled", "settings"} or type(data["enabled"]) is not bool:
                raise ValueError("fields")
            raw_settings = data["settings"]
            if isinstance(raw_settings, dict) and "auto_messages" not in raw_settings:
                raw_settings = {**raw_settings, "auto_messages": self.store.channel(sess["user_id"])["settings"]["auto_messages"]}
            cfg = settings(raw_settings)
        except (ValueError, TypeError):
            return error(400, "invalid_settings")
        if data["enabled"] and (self.service.missing or not self.store.account(self.service.bot_id, "bot")):
            return error(409, "bot_not_ready")
        uid = sess["user_id"]
        if not data["enabled"]:
            # Settle open hands and return pending invitations before detaching.
            self.service.engine.expire_games(channel_id=uid)
        self.store.configure(uid, data["enabled"], cfg)
        self.service.wakeup.set()
        return await self.me(request)

    async def logout(self, request):
        sess = self.session(request, mutate=True)
        with self.store.conn:
            self.store.conn.execute("DELETE FROM twitch_chat_sessions WHERE token_hash=?", (sess["token_hash"],))
        response = web.json_response({"ok": True})
        response.del_cookie(SESSION, path="/")
        return response

    async def discord_link(self, request):
        sess = self.session(request, mutate=True)
        uid = sess["user_id"]
        try:
            data = await request.json()
            if not isinstance(data, dict) or set(data) != {"linked"} or type(data["linked"]) is not bool:
                raise ValueError()
        except (ValueError, TypeError):
            return error(400, "invalid_settings")
        self.service.engine.expire_games()
        if self.store.conn.execute("SELECT 1 FROM twitch_chat_games WHERE user_id=?", (uid,)).fetchone() or self.store.conn.execute("SELECT 1 FROM twitch_chat_duels WHERE challenger=? OR target=?", (uid, uid)).fetchone():
            return error(409, "game_in_progress")
        if data["linked"]:
            discord = self.panel._session(request)
            if not discord:
                return error(401, "discord_login_required")
            try:
                with self.store.conn:
                    self.store.conn.execute("INSERT INTO twitch_chat_links VALUES(?,?,?)", (uid, discord["user_id"], discord["username"]))
            except sqlite3.IntegrityError:
                return error(409, "account_already_linked")
        else:
            with self.store.conn:
                self.store.conn.execute("DELETE FROM twitch_chat_links WHERE twitch_id=?", (uid,))
        return await self.me(request)

    async def eventsub(self, request):
        if self.service.missing:
            return error(503, "not_configured")
        if request.content_length is not None and request.content_length > 65536:
            return error(413, "too_large")
        raw = await request.clone(client_max_size=65536).read()
        if len(raw) > 65536:
            return error(413, "too_large")
        message_id = request.headers.get("Twitch-Eventsub-Message-Id", "")
        stamp = request.headers.get("Twitch-Eventsub-Message-Timestamp", "")
        signature = request.headers.get("Twitch-Eventsub-Message-Signature", "")
        try:
            timestamp = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if not timestamp.tzinfo or not message_id or not -60 <= time.time() - timestamp.timestamp() <= 600:
                raise ValueError()
        except ValueError:
            return error(403, "invalid_event")
        expected = "sha256=" + hmac.new(self.service.secret.encode(), (message_id + stamp).encode() + raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature.encode(), expected.encode()):
            return error(403, "invalid_signature")
        try:
            data = json.loads(raw)
            sub = data["subscription"]
            cid = sub["condition"]["broadcaster_user_id"]
            if sub["type"] != "channel.chat.message" or sub["condition"].get("user_id") != self.service.bot_id:
                raise ValueError()
            kind = request.headers.get("Twitch-Eventsub-Message-Type")
            if kind == "webhook_callback_verification":
                if not isinstance(data.get("challenge"), str):
                    raise ValueError()
                return web.Response(text=data["challenge"], content_type="text/plain")
            if kind == "revocation":
                self.store.status(cid, "error", "Twitch hat die Chat-Verbindung beendet. Bitte neu anmelden.")
                self.service.wakeup.set()
                return web.Response(status=204)
            event = data["event"]
            if kind != "notification" or event["broadcaster_user_id"] != cid:
                raise ValueError()
            if any(not isinstance(event.get(k), str) or not event[k] for k in ("message_id", "chatter_user_id", "chatter_user_login")) or not isinstance(event["message"]["text"], str):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            return error(400, "invalid_event")
        channel = self.store.channel(cid)
        # Shared-chat relays must not debit coins or moderate in another channel.
        if channel and channel["enabled"] and event.get("source_broadcaster_user_id") in {None, "", cid}:
            count = self.store.conn.execute("SELECT COUNT(*) FROM twitch_chat_events WHERE delivered=0").fetchone()[0]
            if count >= 5000:
                return error(503, "queue_full")
            self.store.enqueue(event, time.time())
        return web.Response(status=204)

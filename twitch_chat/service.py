"""Twitch OAuth, encrypted credentials and a persistent EventSub worker."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from contextlib import suppress
from urllib.parse import urlsplit

import aiohttp
from cryptography.fernet import Fernet, InvalidToken

from twitch_chat.commands import Engine
from twitch_chat.store import Store

logger = logging.getLogger("oaken-tower-bot")
OAUTH = "https://id.twitch.tv/oauth2"
HELIX = "https://api.twitch.tv/helix/"
SCOPES = {
    "bot": {"user:read:chat", "user:write:chat", "user:bot"},
    "channel": {"channel:bot", "moderator:manage:chat_messages", "moderator:manage:banned_users"},
}


class TwitchError(RuntimeError):
    def __init__(self, code: str, status: int = 502, *, reason: str = ""):
        super().__init__(code)
        self.code, self.status = code, status
        # Only machine-readable reasons; never retain upstream messages or tokens.
        self.reason = reason if isinstance(reason, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", reason) else ""

    @property
    def diagnostic(self):
        return f"code={self.code}, status={self.status}" + (f", reason={self.reason}" if self.reason else "")


def delivery_error(exc, moderation: bool) -> str:
    action = "AutoMod-Aktion" if moderation else "Chat-Antwort"
    if not isinstance(exc, TwitchError):
        return f"Die {action} konnte wegen eines Verbindungsfehlers zu Twitch nicht bestätigt werden ({type(exc).__name__})."
    hints = {
        "bot_authorization_missing": "Die Bot-Freigabe fehlt. Als Botkonto anmelden und unter „Yamis Botkonto“ die Freigabe erneuern.",
        "channel_authorization_missing": "Die Channel-Freigabe fehlt. Als Streamer erneut mit Twitch anmelden und die Freigabe bestätigen.",
        "automod_held": "Twitch AutoMod hält die Bot-Antwort zur Prüfung zurück. Prüfe die Moderationswarteschlange bei Twitch.",
        "msg_verified_email": "Twitch verlangt ein verifiziertes Botkonto. Bestätige die E-Mail-Adresse des Botkontos bei Twitch.",
        "msg_requires_verified_phone_number": "Twitch verlangt eine verifizierte Telefonnummer für das Botkonto. Prüfe dessen Twitch-Sicherheitseinstellungen.",
        "msg_banned": "Das Botkonto ist in diesem Channel gesperrt. Prüfe den Bann bei Twitch.",
        "msg_timedout": "Das Botkonto hat in diesem Channel einen Timeout. Prüfe den Timeout bei Twitch.",
        "msg_duplicate": "Twitch hat eine identische Bot-Antwort innerhalb kurzer Zeit abgelehnt.",
        "msg_ratelimit": "Twitch begrenzt gerade die Anzahl der Bot-Nachrichten. Bitte später erneut versuchen.",
        "msg_slowmode": "Der Slowmode dieses Channels begrenzt die Bot-Nachrichten.",
        "msg_subsonly": "Der Abonnentenmodus dieses Channels verhindert die Bot-Antwort.",
        "msg_emoteonly": "Der Emote-Modus dieses Channels verhindert die Bot-Antwort.",
    }
    hint = hints.get(exc.reason)
    if not hint and exc.reason.startswith("msg_followersonly"):
        hint = "Der Follower-Modus dieses Channels verhindert die Bot-Antwort. Prüfe die Chat-Einstellungen bei Twitch."
    if not hint:
        hint = {
            401: "Twitch hat die Anmeldung oder Freigabe abgelehnt. Botkonto- und Channel-Freigaben prüfen.",
            403: "Twitch verweigert diese Aktion. Freigaben, Sperren und Chat-Beschränkungen prüfen.",
            422: "Die Bot-Antwort überschreitet Twitchs Nachrichtenlimit.",
            429: "Twitch begrenzt gerade die Anfragen. Bitte später erneut versuchen.",
        }.get(exc.status, "Twitch konnte diese Aktion nicht bestätigen. Bitte den Fehlercode im Server-Log prüfen.")
    return f"{action} fehlgeschlagen: {hint} ({exc.diagnostic})"


class Service:
    def __init__(self, conn, base_url: str):
        self.store = Store(conn)
        self.base_url = base_url.rstrip("/")
        self.client_id = os.environ.get("TWITCH_CLIENT_ID", "")
        self.client_secret = os.environ.get("TWITCH_CLIENT_SECRET", "")
        self.bot_id = os.environ.get("TWITCH_BOT_USER_ID", "")
        self.secret = os.environ.get("TWITCH_EVENTSUB_SECRET", "")
        self.enabled = os.environ.get("TWITCH_CHAT_ENABLED") == "1"
        self.fernet = None
        try:
            self.fernet = Fernet(os.environ.get("TWITCH_TOKEN_KEY", "").encode())
        except (ValueError, TypeError):
            pass
        self.engine = Engine(self.store, self.bot_id)
        self.http: aiohttp.ClientSession | None = None
        self.tasks: list[asyncio.Task] = []
        self._app_token = ""
        self._app_expiry = 0.0
        self._app_lock = asyncio.Lock()
        self._account_lock = asyncio.Lock()
        self._validated: dict[tuple[str, str], float] = {}
        self.wakeup = asyncio.Event()
        self._send_at = 0.0
        self._live: dict[str, tuple[float, bool]] = {}

    @property
    def missing(self):
        items = []
        for key, value in (("TWITCH_CHAT_ENABLED=1", self.enabled), ("TWITCH_CLIENT_ID", self.client_id),
                           ("TWITCH_CLIENT_SECRET", self.client_secret), ("TWITCH_BOT_USER_ID", self.bot_id.isdigit()),
                           ("TWITCH_TOKEN_KEY", self.fernet),
                           ("TWITCH_EVENTSUB_SECRET (32–100 ASCII-Zeichen)", self.secret.isascii() and 32 <= len(self.secret) <= 100),
                           ("WEB_BASE_URL mit HTTPS", urlsplit(self.base_url).scheme == "https" and urlsplit(self.base_url).hostname)):
            if not value:
                items.append(key)
        return items

    async def start(self):
        if self.missing:
            if self.enabled:
                logger.warning("Twitch-Chat nicht gestartet: %s", ", ".join(self.missing))
            return
        self.http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        self.tasks = [asyncio.create_task(self.maintain(), name="twitch-chat-maintain"),
                      asyncio.create_task(self.process(), name="twitch-chat-process"),
                      asyncio.create_task(self.deliver(False), name="twitch-chat-send"),
                      asyncio.create_task(self.deliver(True), name="twitch-chat-moderate"),
                      asyncio.create_task(self.auto_messages(), name="twitch-chat-timers")]

    async def close(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.http:
            await self.http.close()

    async def request(self, method, url, **kwargs):
        if self.http is None:
            raise TwitchError("not_configured", 503)
        async with self.http.request(method, url, **kwargs) as response:
            if response.status >= 400:
                # Classify known permission errors without logging the response body.
                reason = ""
                try:
                    body = await response.json()
                    message = body.get("message", "") if isinstance(body, dict) else ""
                    if isinstance(message, str) and "must have authorized" in message.lower():
                        if "user:bot" in message or "user:write:chat" in message:
                            reason = "bot_authorization_missing"
                        elif "channel:bot" in message:
                            reason = "channel_authorization_missing"
                except (ValueError, aiohttp.ClientError, asyncio.TimeoutError):
                    pass
                raise TwitchError(f"twitch_{response.status}", response.status, reason=reason)
            if response.status == 204:
                return {}
            return await response.json()

    async def app_token(self, force=False):
        async with self._app_lock:
            if not force and self._app_token and time.time() < self._app_expiry - 60:
                return self._app_token
            data = await self.request("POST", OAUTH + "/token", data={"client_id": self.client_id, "client_secret": self.client_secret, "grant_type": "client_credentials"})
            self._app_token = data["access_token"]
            self._app_expiry = time.time() + data["expires_in"]
            return self._app_token

    async def api(self, method, path, *, account=None, **kwargs):
        for attempt in range(2):
            token = await self.user_token(*account, force=bool(attempt)) if account else await self.app_token(force=bool(attempt))
            try:
                return await self.request(method, HELIX + path, headers={"Client-Id": self.client_id, "Authorization": "Bearer " + token}, **kwargs)
            except TwitchError as exc:
                if exc.status != 401 or attempt:
                    raise

    def encrypt(self, data):
        if not self.fernet:
            raise TwitchError("not_configured", 503)
        return self.fernet.encrypt(json.dumps(data).encode()).decode()

    def decrypt(self, value):
        try:
            return json.loads(self.fernet.decrypt(value.encode()))
        except (InvalidToken, AttributeError, ValueError):
            raise TwitchError("token_key_changed", 503) from None

    async def validate(self, token):
        return await self.request("GET", OAUTH + "/validate", headers={"Authorization": "OAuth " + token})

    def check_identity(self, valid, uid, role):
        if valid.get("client_id") != self.client_id or valid.get("user_id") != uid or not SCOPES[role].issubset(valid.get("scopes", [])):
            raise TwitchError("missing_scopes", 403)

    async def authorize(self, code: str, role: str):
        data = await self.request("POST", OAUTH + "/token", data={
            "client_id": self.client_id, "client_secret": self.client_secret, "code": code,
            "grant_type": "authorization_code", "redirect_uri": self.base_url + "/twitch/callback",
        })
        valid = await self.validate(data["access_token"])
        uid = str(valid.get("user_id", ""))
        if not uid.isdigit() or (role == "bot" and uid != self.bot_id):
            raise TwitchError("wrong_bot_account", 403)
        self.check_identity(valid, uid, role)
        profile = await self.request("GET", HELIX + "users", headers={"Client-Id": self.client_id, "Authorization": "Bearer " + data["access_token"]})
        user = profile["data"][0]
        data["expires_at"] = time.time() + data["expires_in"]
        self.store.save_account(uid, role, user["login"], user["display_name"], self.encrypt(data))
        self._validated[(uid, role)] = time.time()
        self.wakeup.set()
        return uid

    async def user_token(self, uid, role="channel", force=False):
        # Refresh tokens rotate: serialize refresh and validation across workers.
        async with self._account_lock:
            row = self.store.account(uid, role)
            if not row:
                raise TwitchError("reauth", 401)
            data = self.decrypt(row["credentials"])
            if force or time.time() > data.get("expires_at", 0) - 90:
                try:
                    refreshed = await self.request("POST", OAUTH + "/token", data={
                        "client_id": self.client_id, "client_secret": self.client_secret,
                        "grant_type": "refresh_token", "refresh_token": data["refresh_token"],
                    })
                except TwitchError as exc:
                    if exc.status in {400, 401}:
                        self.store.forget_account(uid, role)
                    raise
                data.update(refreshed)
                data["expires_at"] = time.time() + refreshed["expires_in"]
                self.store.save_account(uid, role, row["login"], row["display_name"], self.encrypt(data))
                self._validated.pop((uid, role), None)
            if time.time() - self._validated.get((uid, role), 0) >= 3600:
                try:
                    valid = await self.validate(data["access_token"])
                    self.check_identity(valid, uid, role)
                except TwitchError as exc:
                    if exc.status in {401, 403}:
                        self.store.forget_account(uid, role)
                    raise
                self._validated[(uid, role)] = time.time()
            return data["access_token"]

    async def reconcile(self):
        self.engine.expire_games()
        self.store.cleanup()
        # Validate even inactive channel grants because browser sessions still exist.
        accounts = self.store.conn.execute("SELECT user_id,role FROM twitch_chat_accounts").fetchall()
        for uid, role in accounts:
            try:
                await self.user_token(uid, role)
            except (TwitchError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
                if role == "channel":
                    self.store.status(uid, "error", "Twitch-Freigabe prüfen oder erneut anmelden.")
                logger.warning("Twitch-Chat: Tokenprüfung fehlgeschlagen (%s).", exc.diagnostic if isinstance(exc, TwitchError) else type(exc).__name__)
        bot_ready = bool(self.store.account(self.bot_id, "bot"))
        desired = {c["user_id"]: c for c in self.store.channels() if c["enabled"] and bot_ready and self.store.account(c["user_id"])}
        subscriptions, cursor = [], ""
        while True:
            data = await self.api("GET", "eventsub/subscriptions", params={"first": "100", **({"after": cursor} if cursor else {})})
            subscriptions.extend(data.get("data", []))
            cursor = data.get("pagination", {}).get("cursor")
            if not cursor:
                break
        callback = self.base_url + "/twitch/eventsub"
        found = set()
        for sub in subscriptions:
            # Do not touch the existing Discord live notification integration or other apps.
            if sub["type"] != "channel.chat.message" or sub.get("transport", {}).get("callback") != callback or sub["condition"].get("user_id") != self.bot_id:
                continue
            cid = sub["condition"]["broadcaster_user_id"]
            good = sub["status"] in {"enabled", "webhook_callback_verification_pending"}
            if cid not in desired or not good:
                await self.api("DELETE", "eventsub/subscriptions", params={"id": sub["id"]})
            else:
                found.add(cid)
                self.store.status(cid, "connected" if sub["status"] == "enabled" else "connecting")
        for cid in desired.keys() - found:
            try:
                await self.api("POST", "eventsub/subscriptions", json={
                    "type": "channel.chat.message", "version": "1",
                    "condition": {"broadcaster_user_id": cid, "user_id": self.bot_id},
                    "transport": {"method": "webhook", "callback": callback, "secret": self.secret},
                })
                self.store.status(cid, "connecting")
            except TwitchError as exc:
                self.store.status(cid, "error", "Twitch konnte den Chat nicht verbinden. Freigaben und Botkonto prüfen.")
                logger.warning("Twitch-Chat: EventSub-Anmeldung fehlgeschlagen (%s).", exc.diagnostic)
        if not bot_ready:
            for channel in self.store.channels():
                if channel["enabled"]:
                    self.store.status(channel["user_id"], "error", "Das Botkonto muss erneut mit Twitch verbunden werden.")

    async def maintain(self):
        while True:
            self.wakeup.clear()
            try:
                await self.reconcile()
            except (TwitchError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
                logger.warning("Twitch-Chat: Abgleich fehlgeschlagen (%s).", exc.diagnostic if isinstance(exc, TwitchError) else type(exc).__name__)
            except Exception:
                logger.exception("Twitch-Chat: Unerwarteter Fehler beim Abgleich.")
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.wakeup.wait(), timeout=60)

    async def process(self):
        while True:
            rows = self.store.conn.execute("SELECT * FROM twitch_chat_events WHERE processed=0 ORDER BY created LIMIT 50").fetchall()
            for row in rows:
                try:
                    self.engine.process(dict(row))
                except Exception:
                    logger.exception("Twitch-Chat: Nachricht konnte nicht verarbeitet werden.")
                    # A broken event must not block the queue or mutate balances repeatedly.
                    with self.store.conn:
                        self.store.conn.execute("UPDATE twitch_chat_events SET processed=1,delivered=1,payload='{}' WHERE id=?", (row["id"],))
            await asyncio.sleep(.2)

    async def refresh_live(self, ids: set[str]):
        # Twitch accepts up to 100 user IDs per request. Cache for at most a minute.
        now = time.monotonic()
        stale = sorted(uid for uid in ids if self._live.get(uid, (0, False))[0] <= now)
        for start in range(0, len(stale), 100):
            batch = stale[start:start + 100]
            result = await self.api("GET", "streams", params=[("first", "100"), *[("user_id", uid) for uid in batch]])
            rows = result.get("data")
            if not isinstance(rows, list) or any(not isinstance(row, dict) or "user_id" not in row for row in rows):
                raise TwitchError("streams_response_invalid")
            live = {row["user_id"] for row in rows}
            for uid in batch:
                self._live[uid] = (time.monotonic() + 60, uid in live)

    async def schedule_auto_messages(self, now: float | None = None):
        if not self.store.account(self.bot_id, "bot"):
            return
        now = time.time() if now is None else now
        due = self.store.due_messages(now)
        await self.refresh_live({uid for uid, message in due if message["live_only"]})
        queued = set()
        # Re-read after the API await: settings or the bot's authorization may change.
        if not self.store.account(self.bot_id, "bot"):
            return
        for uid, message in self.store.due_messages(now):
            if uid in queued or not self.store.account(uid):
                continue
            checked_until, live = self._live.get(uid, (0, False))
            if message["live_only"] and (not live or checked_until <= time.monotonic()):
                continue
            if self.store.conn.execute("SELECT COUNT(*) FROM twitch_chat_events WHERE delivered=0").fetchone()[0] >= 5000:
                break
            self.store.queue_auto_message(uid, message, now)
            queued.add(uid)

    async def auto_messages(self):
        while True:
            try:
                await self.schedule_auto_messages()
            except (TwitchError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
                logger.warning("Twitch-Chat: Autonachrichten konnten nicht geplant werden (%s).",
                               exc.diagnostic if isinstance(exc, TwitchError) else type(exc).__name__)
            except Exception:
                logger.exception("Twitch-Chat: Unerwarteter Fehler bei Autonachrichten.")
            await asyncio.sleep(15)

    async def deliver(self, moderation: bool):
        action = "moderation" if moderation else "send"
        while True:
            row = self.store.conn.execute("""SELECT * FROM twitch_chat_events WHERE processed=1 AND delivered=0
                AND (instr(COALESCE(result,''),'\"moderate\":')>0)=? ORDER BY created LIMIT 1""", (int(moderation),)).fetchone()
            if not row:
                await asyncio.sleep(.2)
                continue
            cid = row["channel_id"]
            channel = self.store.channel(cid)
            result = json.loads(row["result"] or "{}")
            if not result or not channel or not channel["enabled"] or time.time() - row["created"] > 120:
                self.finish(row["id"])
                continue
            if not moderation:
                await asyncio.sleep(max(0, self._send_at - time.monotonic()))
                self._send_at = time.monotonic() + 1.6
            # Pause/removal can happen while awaiting the throttle.
            if not self.store.channel(cid)["enabled"]:
                self.finish(row["id"])
                continue
            try:
                automatic = result.get("auto_message")
                if automatic:
                    if automatic["live_only"]:
                        await self.refresh_live({cid})
                    if (not self.store.auto_message_active(cid, automatic)
                            or not self.store.account(self.bot_id, "bot") or not self.store.account(cid)
                            or not self.store.auto_message_can_send(cid, time.time())
                            or (automatic["live_only"] and not self._live[cid][1])):
                        self.finish(row["id"])
                        continue
                # Timer edits cancel pending copies, including one already waiting here.
                current = self.store.conn.execute("SELECT delivered FROM twitch_chat_events WHERE id=?", (row["id"],)).fetchone()
                if not current or current[0] or time.time() - row["created"] > 120:
                    self.finish(row["id"])
                    continue
                event = json.loads(row["payload"])
                if moderation:
                    mod = result["moderate"]
                    params = {"broadcaster_id": cid, "moderator_id": cid}
                    if mod["duration"]:
                        await self.api("POST", "moderation/bans", account=(cid, "channel"), params=params,
                                       json={"data": {"user_id": event["chatter_user_id"], "duration": mod["duration"], "reason": "Yami AutoMod: " + mod["reason"]}})
                    else:
                        await self.api("DELETE", "moderation/chat", account=(cid, "channel"), params={**params, "message_id": event["message_id"]})
                    with self.store.conn:
                        self.store.conn.execute("UPDATE twitch_chat_modlog SET outcome='ok' WHERE id=?", (mod["log_id"],))
                else:
                    sent = await self.api("POST", "chat/messages", json={"broadcaster_id": cid, "sender_id": self.bot_id,
                                               "message": result["reply"], "for_source_only": True})
                    items = sent.get("data")
                    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
                        raise TwitchError("chat_response_invalid", 200)
                    if not items[0].get("is_sent"):
                        dropped = items[0].get("drop_reason")
                        reason = dropped.get("code", "") if isinstance(dropped, dict) else ""
                        raise TwitchError("chat_message_dropped", 200, reason=reason)
                    if automatic:
                        self.store.auto_message_sent(cid, time.time())
                self.store.delivery_status(cid, action)
                self.finish(row["id"])
            except (TwitchError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
                retry = isinstance(exc, TwitchError) and (exc.status == 429 or exc.status >= 500) and row["attempts"] < 2
                # Network timeouts are ambiguous: do not send the same payout message
                # again. Its committed result remains in SQLite for diagnosis.
                with self.store.conn:
                    self.store.conn.execute("UPDATE twitch_chat_events SET attempts=attempts+1,delivered=? WHERE id=?", (0 if retry else 1, row["id"]))
                    if moderation:
                        self.store.conn.execute("UPDATE twitch_chat_modlog SET outcome=? WHERE id=?", ("retry" if retry else "failed", result["moderate"]["log_id"]))
                self.store.delivery_status(cid, action, delivery_error(exc, moderation))
                logger.warning("Twitch-Chat: Zustellung fehlgeschlagen (channel=%s, action=%s, %s).", cid, action,
                               exc.diagnostic if isinstance(exc, TwitchError) else type(exc).__name__)
                if retry:
                    await asyncio.sleep(5)
            except Exception:
                logger.exception("Twitch-Chat: Unerwarteter Zustellungsfehler.")
                self.finish(row["id"])

    def finish(self, event_id):
        with self.store.conn:
            # Keep only the deduplication key and result for 24 h, not chat text.
            self.store.conn.execute("UPDATE twitch_chat_events SET delivered=1,payload='{}' WHERE id=?", (event_id,))

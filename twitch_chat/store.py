"""Durable Twitch state on the bot's existing SQLite connection.

All chat command mutations run synchronously in one transaction. Twitch delivery
IDs and chat message IDs are deduplicated before any coins or social data change.
OAuth credentials are encrypted by the service before reaching this module.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid

DEFAULTS = {
    "prefix": "!", "social_enabled": True, "gambling_enabled": True,
    "automod_enabled": False, "block_links": False, "block_caps": False,
    "block_spam": True, "blocked_words": [], "timeout_seconds": 60,
    "command_cooldown": 5, "max_bet": 10000, "daily_coins": 500,
    "auto_messages": [], "custom_commands": [],
}

MAX_CHANNEL_REPLIES = 10
MAX_TOTAL_REPLIES = 50


class Store:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS twitch_chat_accounts (
                user_id TEXT NOT NULL, role TEXT NOT NULL, login TEXT NOT NULL,
                display_name TEXT NOT NULL, credentials TEXT NOT NULL,
                PRIMARY KEY(user_id, role)
            );
            CREATE TABLE IF NOT EXISTS twitch_chat_channels (
                user_id TEXT PRIMARY KEY, login TEXT NOT NULL, display_name TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0, settings TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'disabled', error TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS twitch_chat_sessions (
                token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                csrf TEXT NOT NULL, expires REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS twitch_chat_oauth (
                state_hash TEXT PRIMARY KEY, role TEXT NOT NULL, expires REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS twitch_chat_events (
                id TEXT PRIMARY KEY, channel_id TEXT NOT NULL, payload TEXT NOT NULL,
                created REAL NOT NULL, processed INTEGER NOT NULL DEFAULT 0,
                result TEXT, delivered INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS twitch_chat_pending ON twitch_chat_events(delivered, created);
            CREATE INDEX IF NOT EXISTS twitch_chat_channel_events ON twitch_chat_events(channel_id, created);
            CREATE TABLE IF NOT EXISTS twitch_chat_wallets (
                channel_id TEXT NOT NULL, user_id TEXT NOT NULL, login TEXT NOT NULL,
                coins INTEGER NOT NULL DEFAULT 0 CHECK(coins >= 0),
                daily_at REAL NOT NULL DEFAULT 0, command_at REAL NOT NULL DEFAULT 0,
                PRIMARY KEY(channel_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS twitch_chat_games (
                channel_id TEXT NOT NULL, user_id TEXT NOT NULL,
                state TEXT NOT NULL, expires REAL NOT NULL,
                PRIMARY KEY(channel_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS twitch_chat_relations (
                channel_id TEXT NOT NULL, kind TEXT NOT NULL,
                user_a TEXT NOT NULL, user_b TEXT NOT NULL, requester TEXT NOT NULL,
                accepted INTEGER NOT NULL DEFAULT 0, xp INTEGER NOT NULL DEFAULT 0,
                xp_at REAL NOT NULL DEFAULT 0,
                PRIMARY KEY(channel_id, kind, user_a, user_b)
            );
            CREATE TABLE IF NOT EXISTS twitch_chat_duels (
                channel_id TEXT NOT NULL, challenger TEXT NOT NULL, target TEXT NOT NULL,
                bet INTEGER NOT NULL, expires REAL NOT NULL, state TEXT,
                PRIMARY KEY(channel_id, challenger)
            );
            CREATE TABLE IF NOT EXISTS twitch_chat_links (
                twitch_id TEXT PRIMARY KEY, discord_id INTEGER NOT NULL UNIQUE,
                discord_name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS twitch_chat_modlog (
                id INTEGER PRIMARY KEY, channel_id TEXT NOT NULL, login TEXT NOT NULL,
                reason TEXT NOT NULL, action TEXT NOT NULL, created REAL NOT NULL,
                outcome TEXT NOT NULL DEFAULT 'pending'
            );
            CREATE TABLE IF NOT EXISTS twitch_chat_delivery_errors (
                channel_id TEXT NOT NULL, action TEXT NOT NULL, error TEXT NOT NULL,
                PRIMARY KEY(channel_id, action)
            );
            CREATE TABLE IF NOT EXISTS twitch_chat_timers (
                channel_id TEXT NOT NULL, message_id TEXT NOT NULL,
                next_due REAL NOT NULL, message_count INTEGER NOT NULL DEFAULT 0,
                last_queued REAL NOT NULL DEFAULT 0,
                PRIMARY KEY(channel_id, message_id)
            );
            CREATE TABLE IF NOT EXISTS twitch_chat_timer_sends (
                channel_id TEXT PRIMARY KEY, last_sent REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS twitch_chat_command_cooldowns (
                channel_id TEXT NOT NULL, command_id TEXT NOT NULL, user_id TEXT NOT NULL,
                until REAL NOT NULL, PRIMARY KEY(channel_id,command_id,user_id)
            );
            CREATE TABLE IF NOT EXISTS twitch_chat_activity (
                channel_id TEXT PRIMARY KEY, last_received REAL, last_sent REAL,
                last_moderated REAL, last_live_check REAL, live INTEGER, live_error TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS twitch_chat_dispatch (
                channel_id TEXT NOT NULL, action TEXT NOT NULL,
                last_attempt REAL NOT NULL DEFAULT 0, next_allowed REAL NOT NULL DEFAULT 0,
                PRIMARY KEY(channel_id,action)
            );
        """)
        columns = {r[1] for r in conn.execute("PRAGMA table_info(twitch_chat_events)")}
        with conn:
            if "next_attempt" not in columns:
                conn.execute("ALTER TABLE twitch_chat_events ADD COLUMN next_attempt REAL NOT NULL DEFAULT 0")
            if "outcome" not in columns:
                conn.execute("ALTER TABLE twitch_chat_events ADD COLUMN outcome TEXT NOT NULL DEFAULT ''")

    @staticmethod
    def digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def account(self, uid: str, role: str = "channel") -> dict | None:
        row = self.conn.execute("SELECT * FROM twitch_chat_accounts WHERE user_id=? AND role=?", (uid, role)).fetchone()
        return dict(row) if row else None

    def save_account(self, uid: str, role: str, login: str, name: str, credentials: str):
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO twitch_chat_accounts VALUES (?,?,?,?,?)", (uid, role, login, name, credentials))
            if role == "channel":
                self.conn.execute("""INSERT INTO twitch_chat_channels(user_id,login,display_name) VALUES(?,?,?)
                    ON CONFLICT(user_id) DO UPDATE SET login=excluded.login,display_name=excluded.display_name""", (uid, login, name))

    def channel(self, uid: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM twitch_chat_channels WHERE user_id=?", (uid,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["enabled"] = bool(result["enabled"])
        result["settings"] = {**DEFAULTS, **json.loads(result["settings"])}
        return result

    def channels(self) -> list[dict]:
        return [self.channel(r[0]) for r in self.conn.execute("SELECT user_id FROM twitch_chat_channels")]

    def status(self, uid: str, status: str, error: str = ""):
        with self.conn:
            self.conn.execute("UPDATE twitch_chat_channels SET status=?,error=? WHERE user_id=?", (status, error, uid))

    def configure(self, uid: str, enabled: bool, settings: dict, *, now: float | None = None):
        now = time.time() if now is None else now
        previous = self.channel(uid)
        old = {m["id"]: m for m in previous["settings"]["auto_messages"]} if previous else {}
        new = {m["id"]: m for m in settings.get("auto_messages", [])}
        with self.conn:
            old_commands = {c["id"]: c for c in previous["settings"]["custom_commands"]} if previous else {}
            new_commands = {c["id"]: c for c in settings.get("custom_commands", [])}
            for command_id in old_commands.keys() | new_commands.keys():
                if old_commands.get(command_id) != new_commands.get(command_id):
                    self.conn.execute("DELETE FROM twitch_chat_command_cooldowns WHERE channel_id=? AND command_id=?", (uid, command_id))
                    # Edits/removal must also cancel replies waiting for delivery.
                    self.conn.execute("""UPDATE twitch_chat_events SET delivered=1,payload='{}',outcome='cancelled'
                        WHERE channel_id=? AND delivered=0 AND json_extract(result,'$.custom_command_id')=?""", (uid, command_id))
            for mid in old.keys() | new.keys():
                changed = old.get(mid) != new.get(mid) or not previous or previous["enabled"] != enabled
                if not changed:
                    continue
                # Cancel queued copies as well as resetting the timer on edits/pause.
                self.conn.execute("UPDATE twitch_chat_events SET delivered=1,payload='{}',outcome='cancelled' WHERE id GLOB ? AND delivered=0",
                                  (f"auto:{uid}:{mid}:*",))
                self.conn.execute("DELETE FROM twitch_chat_timers WHERE channel_id=? AND message_id=?", (uid, mid))
                message = new.get(mid)
                if enabled and message and message["enabled"]:
                    self.conn.execute("INSERT INTO twitch_chat_timers(channel_id,message_id,next_due) VALUES(?,?,?)",
                                      (uid, mid, now + message["interval_minutes"] * 60))
            self.conn.execute("UPDATE twitch_chat_channels SET enabled=?,settings=?,status=?,error='' WHERE user_id=?",
                              (enabled, json.dumps(settings), "connecting" if enabled else "disabled", uid))
            if not enabled:
                self.conn.execute("DELETE FROM twitch_chat_delivery_errors WHERE channel_id=?", (uid,))
                self.conn.execute("""UPDATE twitch_chat_modlog SET outcome='cancelled' WHERE id IN
                    (SELECT json_extract(result,'$.moderate.log_id') FROM twitch_chat_events WHERE channel_id=? AND delivered=0)""", (uid,))
                self.conn.execute("""UPDATE twitch_chat_events SET delivered=1,processed=1,payload='{}',outcome='cancelled'
                    WHERE channel_id=? AND delivered=0""", (uid,))

    def timer_activity(self, uid: str):
        # Called inside the event-processing transaction, after deduplication/AutoMod.
        self.conn.execute("UPDATE twitch_chat_timers SET message_count=MIN(message_count+1,1000) WHERE channel_id=?", (uid,))

    def due_messages(self, now: float) -> list[tuple[str, dict]]:
        channels = {c["user_id"]: c for c in self.channels() if c["enabled"] and c["status"] == "connected"}
        due = []
        for row in self.conn.execute("""SELECT * FROM twitch_chat_timers t WHERE next_due<=?
                AND NOT EXISTS (SELECT 1 FROM twitch_chat_timers recent
                    WHERE recent.channel_id=t.channel_id AND recent.last_queued>?)
                ORDER BY next_due,channel_id,message_id""", (now, now - 60)):
            channel = channels.get(row["channel_id"])
            if not channel or not self.auto_message_can_send(row["channel_id"], now):
                continue
            message = next((m for m in channel["settings"]["auto_messages"] if m["id"] == row["message_id"]), None)
            if message and message["enabled"] and row["message_count"] >= message["min_messages"]:
                due.append((row["channel_id"], message))
        return due

    def queue_auto_message(self, uid: str, message: dict, now: float):
        with self.conn:
            self.conn.execute("""INSERT INTO twitch_chat_events(id,channel_id,payload,created,processed,result)
                VALUES(?,?,'{}',?,1,?)""", (f"auto:{uid}:{message['id']}:{uuid.uuid4().hex}", uid, now,
                json.dumps({"reply": message["text"], "auto_message": message})))
            self.conn.execute("UPDATE twitch_chat_timers SET next_due=?,message_count=0,last_queued=? WHERE channel_id=? AND message_id=?",
                              (now + message["interval_minutes"] * 60, now, uid, message["id"]))

    def auto_message_active(self, uid: str, message: dict) -> bool:
        channel = self.channel(uid)
        return bool(channel and channel["enabled"] and message["enabled"] and message in channel["settings"]["auto_messages"])

    def auto_message_can_send(self, uid: str, now: float) -> bool:
        row = self.conn.execute("SELECT last_sent FROM twitch_chat_timer_sends WHERE channel_id=?", (uid,)).fetchone()
        return not row or now - row[0] >= 60

    def auto_message_sent(self, uid: str, now: float):
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO twitch_chat_timer_sends VALUES(?,?)", (uid, now))

    def delivery_status(self, uid: str, action: str, error: str = ""):
        # Receiving EventSub events does not prove that sending/moderating works.
        # Keep both failures independently until that same action succeeds.
        with self.conn:
            if error:
                self.conn.execute("INSERT OR REPLACE INTO twitch_chat_delivery_errors VALUES(?,?,?)", (uid, action, error))
            else:
                self.conn.execute("DELETE FROM twitch_chat_delivery_errors WHERE channel_id=? AND action=?", (uid, action))

    def forget_account(self, uid: str, role: str):
        with self.conn:
            self.conn.execute("DELETE FROM twitch_chat_accounts WHERE user_id=? AND role=?", (uid, role))
            if role == "channel":
                self.conn.execute("DELETE FROM twitch_chat_sessions WHERE user_id=?", (uid,))
                self.conn.execute("UPDATE twitch_chat_channels SET enabled=0,status='reauth',error='Twitch-Freigabe erneuern.' WHERE user_id=?", (uid,))

    def enqueue(self, event: dict, now: float) -> None:
        # A shared chat can produce more than one delivery ID for a message.
        key = event["broadcaster_user_id"] + ":" + event["message_id"]
        with self.conn:
            inserted = self.conn.execute("INSERT OR IGNORE INTO twitch_chat_events(id,channel_id,payload,created) VALUES(?,?,?,?)",
                              (key, event["broadcaster_user_id"], json.dumps(event), now))
            if inserted.rowcount:
                self.conn.execute("""INSERT INTO twitch_chat_activity(channel_id,last_received) VALUES(?,?)
                    ON CONFLICT(channel_id) DO UPDATE SET last_received=excluded.last_received""", (event["broadcaster_user_id"], now))

    def reply_capacity(self, uid: str, now: float) -> bool:
        row = self.conn.execute("""SELECT COUNT(*),COALESCE(SUM(channel_id=?),0) FROM twitch_chat_events
            WHERE processed=1 AND delivered=0 AND created>? AND json_extract(result,'$.reply') IS NOT NULL""",
            (uid, now - 120)).fetchone()
        return row[0] < MAX_TOTAL_REPLIES and row[1] < MAX_CHANNEL_REPLIES

    def next_delivery(self, moderation: bool, now: float):
        action = "moderation" if moderation else "send"
        return self.conn.execute("""SELECT e.* FROM twitch_chat_events e
            LEFT JOIN twitch_chat_dispatch d ON d.channel_id=e.channel_id AND d.action=?
            WHERE e.processed=1 AND e.delivered=0 AND e.next_attempt<=?
            AND (json_extract(e.result,'$.moderate') IS NOT NULL)=?
            AND COALESCE(d.next_allowed,0)<=?
            AND COALESCE((SELECT next_allowed FROM twitch_chat_dispatch WHERE channel_id='*' AND action=?),0)<=?
            ORDER BY (e.id LIKE 'auto:%'),COALESCE(d.last_attempt,0),e.created,e.id LIMIT 1""",
            (action, now, int(moderation), now, action, now)).fetchone()

    def dispatch_attempt(self, uid: str, moderation: bool, now: float):
        action = "moderation" if moderation else "send"
        with self.conn:
            self.conn.execute("""INSERT INTO twitch_chat_dispatch(channel_id,action,last_attempt) VALUES(?,?,?)
                ON CONFLICT(channel_id,action) DO UPDATE SET last_attempt=excluded.last_attempt""", (uid, action, now))
            if not moderation:
                self.defer_dispatch("*", action, now + 1.6)

    def defer_dispatch(self, uid: str, action: str, until: float):
        # Also used inside delivery's transaction; no nested commit.
        self.conn.execute("""INSERT INTO twitch_chat_dispatch(channel_id,action,next_allowed) VALUES(?,?,?)
            ON CONFLICT(channel_id,action) DO UPDATE SET next_allowed=MAX(next_allowed,excluded.next_allowed)""", (uid, action, until))

    def finish(self, event_id: str, outcome: str):
        with self.conn:
            row = self.conn.execute("SELECT channel_id,result,delivered FROM twitch_chat_events WHERE id=?", (event_id,)).fetchone()
            if not row or row["delivered"]:
                return
            result = json.loads(row["result"] or "{}")
            self.conn.execute("UPDATE twitch_chat_events SET processed=1,delivered=1,payload='{}',outcome=? WHERE id=?", (outcome, event_id))
            if result.get("moderate"):
                self.conn.execute("UPDATE twitch_chat_modlog SET outcome=? WHERE id=?",
                                  ("ok" if outcome == "sent" else outcome, result["moderate"]["log_id"]))
            if outcome == "sent":
                field = "last_moderated" if "moderate" in result else "last_sent"
                self.conn.execute(f"""INSERT INTO twitch_chat_activity(channel_id,{field}) VALUES(?,?)
                    ON CONFLICT(channel_id) DO UPDATE SET {field}=excluded.{field}""", (row["channel_id"], time.time()))

    def expire_deliveries(self, now: float):
        for row in self.conn.execute("SELECT id FROM twitch_chat_events WHERE delivered=0 AND created<=?", (now - 120,)).fetchall():
            self.finish(row[0], "expired")

    def cleanup(self):
        now = time.time()
        with self.conn:
            self.conn.execute("DELETE FROM twitch_chat_sessions WHERE expires<?", (now,))
            self.conn.execute("DELETE FROM twitch_chat_oauth WHERE expires<?", (now,))
            self.conn.execute("DELETE FROM twitch_chat_command_cooldowns WHERE until<?", (now,))
            self.conn.execute("DELETE FROM twitch_chat_events WHERE created<? AND delivered=1", (now - 86400,))
            self.conn.execute("DELETE FROM twitch_chat_modlog WHERE created<?", (now - 30 * 86400,))

    def dashboard(self, uid: str) -> dict:
        channel = self.channel(uid)
        if channel:
            channel["connection_error"] = channel["error"]
            channel["connection_status"] = channel["status"]
        if channel and channel["enabled"]:
            errors = [r[0] for r in self.conn.execute("SELECT error FROM twitch_chat_delivery_errors WHERE channel_id=? ORDER BY action", (uid,))]
            if errors:
                channel["error"] = " ".join(filter(None, [channel["error"], *errors]))
                channel["status"] = "error"
        leaders = self.conn.execute("""SELECT w.login,
            CASE WHEN l.discord_id IS NOT NULL THEN COALESCE(d.coins,0) ELSE w.coins END AS coins
            FROM twitch_chat_wallets w LEFT JOIN twitch_chat_links l ON l.twitch_id=w.user_id
            LEFT JOIN levels d ON d.guild_id=0 AND d.user_id=l.discord_id
            WHERE channel_id=? ORDER BY coins DESC LIMIT 10""", (uid,)).fetchall()
        logs = self.conn.execute("SELECT login,reason,action,created,outcome FROM twitch_chat_modlog WHERE channel_id=? ORDER BY id DESC LIMIT 15", (uid,)).fetchall()
        activity = self.conn.execute("SELECT * FROM twitch_chat_activity WHERE channel_id=?", (uid,)).fetchone()
        queue = self.conn.execute("""SELECT COUNT(*) AS pending,MIN(created) AS oldest,
            COALESCE(SUM(id LIKE 'auto:%'),0) AS timers FROM twitch_chat_events WHERE channel_id=? AND delivered=0""", (uid,)).fetchone()
        outcomes = {r[0]: r[1] for r in self.conn.execute("""SELECT outcome,COUNT(*) FROM twitch_chat_events
            WHERE channel_id=? AND created>? GROUP BY outcome""", (uid, time.time() - 86400))}
        errors = {r[0]: r[1] for r in self.conn.execute("SELECT action,error FROM twitch_chat_delivery_errors WHERE channel_id=?", (uid,))}
        diagnostics = {**(dict(activity) if activity else {}), "pending": queue["pending"], "pending_timers": queue["timers"],
                       "oldest_age": max(0, time.time() - queue["oldest"]) if queue["oldest"] else 0,
                       "failed_24h": outcomes.get("failed", 0), "expired_24h": outcomes.get("expired", 0),
                       "overloaded_24h": outcomes.get("overloaded", 0), "send_error": errors.get("send", ""),
                       "moderation_error": errors.get("moderation", "")}
        return {"channel": channel, "leaderboard": [dict(r) for r in leaders], "moderation_log": [dict(r) for r in logs],
                "diagnostics": diagnostics}

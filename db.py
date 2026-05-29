"""SQLite-Datenzugriff für Leveling und Announcer.

Eine einzige Verbindung wird über den gesamten Bot geteilt. Da der Bot
single-threaded im Event-Loop läuft und die Queries winzig sind, sind synchrone
sqlite3-Aufrufe hier unproblematisch.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Optional

# Speicherort der Datenbank. Über DATA_DIR umlenkbar (z.B. /data in Containern),
# damit die DB einen persistenten Ordner bekommt. Lokal: aktuelles Verzeichnis.
DB_FILE: str = os.path.join(os.environ.get("DATA_DIR", "."), "bot.db")


class Database:
    """Dünner Wrapper um eine SQLite-Verbindung mit den nötigen Tabellen."""

    def __init__(self, path: str = DB_FILE) -> None:
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()
        self._migrate()

    def _create_tables(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS levels (
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                xp          INTEGER NOT NULL DEFAULT 0,
                level       INTEGER NOT NULL DEFAULT 0,
                coins       INTEGER NOT NULL DEFAULT 0,
                last_msg_ts REAL    NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id            INTEGER PRIMARY KEY,
                levelup_channel_id  INTEGER,
                announce_channel_id INTEGER
            );

            CREATE TABLE IF NOT EXISTS feeds (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id      INTEGER NOT NULL,
                feed_url      TEXT    NOT NULL,
                label         TEXT,
                kind          TEXT    NOT NULL DEFAULT 'rss',
                last_entry_id TEXT
            );

            CREATE TABLE IF NOT EXISTS cf_stats (
                guild_id INTEGER NOT NULL,
                user_id  INTEGER NOT NULL,
                games    INTEGER NOT NULL DEFAULT 0,
                wins     INTEGER NOT NULL DEFAULT 0,
                losses   INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS profiles (
                guild_id INTEGER NOT NULL,
                user_id  INTEGER NOT NULL,
                bio      TEXT,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS game_stats (
                guild_id INTEGER NOT NULL,
                user_id  INTEGER NOT NULL,
                game     TEXT    NOT NULL,
                games    INTEGER NOT NULL DEFAULT 0,
                wins     INTEGER NOT NULL DEFAULT 0,
                losses   INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, game)
            );

            CREATE TABLE IF NOT EXISTS daily (
                guild_id   INTEGER NOT NULL,
                user_id    INTEGER NOT NULL,
                last_claim REAL    NOT NULL DEFAULT 0,
                streak     INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS effects (
                guild_id INTEGER NOT NULL,
                user_id  INTEGER NOT NULL,
                effect   TEXT    NOT NULL,
                charges  INTEGER NOT NULL DEFAULT 0,
                expires  REAL    NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, effect)
            );

            CREATE TABLE IF NOT EXISTS friendships (
                guild_id  INTEGER NOT NULL,
                user_a    INTEGER NOT NULL,   -- immer die kleinere ID
                user_b    INTEGER NOT NULL,   -- immer die größere ID
                status    TEXT,               -- NULL, 'pending' oder 'accepted'
                requester INTEGER,            -- wer die Anfrage gestellt hat (bei pending)
                xp        INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_a, user_b)
            );

            CREATE TABLE IF NOT EXISTS interactions (
                guild_id  INTEGER NOT NULL,
                actor_id  INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                action    TEXT    NOT NULL,
                count     INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, actor_id, target_id, action)
            );

            CREATE TABLE IF NOT EXISTS marriages (
                guild_id INTEGER NOT NULL,
                user_a   INTEGER NOT NULL,   -- kleinere ID
                user_b   INTEGER NOT NULL,   -- größere ID
                since    REAL    NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_a, user_b)
            );

            CREATE TABLE IF NOT EXISTS titles (
                guild_id INTEGER NOT NULL,
                user_id  INTEGER NOT NULL,
                title    TEXT,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS card_inventory (
                guild_id INTEGER NOT NULL,
                user_id  INTEGER NOT NULL,
                card_id  TEXT    NOT NULL,
                count    INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, card_id)
            );

            CREATE TABLE IF NOT EXISTS reward_games (
                guild_id INTEGER NOT NULL,
                game     TEXT    NOT NULL,   -- kleingeschrieben für Matching
                PRIMARY KEY (guild_id, game)
            );

            CREATE TABLE IF NOT EXISTS playtime (
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                accumulated INTEGER NOT NULL DEFAULT 0,  -- Sekunden Richtung nächster Karte
                day         TEXT,                        -- YYYY-MM-DD (Tages-Cap)
                cards_today INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS custom_cards (
                guild_id  INTEGER NOT NULL,
                card_id   TEXT    NOT NULL,
                name      TEXT    NOT NULL,
                rarity    TEXT    NOT NULL,
                image_url TEXT,
                PRIMARY KEY (guild_id, card_id)
            );

            CREATE TABLE IF NOT EXISTS server_cards (
                guild_id  INTEGER NOT NULL,
                card_id   TEXT    NOT NULL,
                name      TEXT    NOT NULL,
                rarity    TEXT    NOT NULL,
                image_url TEXT,
                PRIMARY KEY (guild_id, card_id)
            );

            CREATE TABLE IF NOT EXISTS server_inventory (
                guild_id INTEGER NOT NULL,
                user_id  INTEGER NOT NULL,
                card_id  TEXT    NOT NULL,
                count    INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, card_id)
            );

            CREATE TABLE IF NOT EXISTS packs (
                guild_id  INTEGER NOT NULL,
                user_id   INTEGER NOT NULL,
                pack_type TEXT    NOT NULL,
                count     INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, pack_type)
            );
            """
        )
        self.conn.commit()

    def _migrate(self) -> None:
        """Einmalige Schema-Anpassungen / Datenübernahmen."""
        self.conn.execute(
            "INSERT OR IGNORE INTO game_stats (guild_id, user_id, game, games, wins, losses) "
            "SELECT guild_id, user_id, 'coinflip', games, wins, losses FROM cf_stats"
        )
        # Spalte für die LFG-Rolle nachrüsten (falls noch nicht vorhanden).
        try:
            self.conn.execute("ALTER TABLE guild_settings ADD COLUMN lfg_role_id INTEGER")
        except sqlite3.OperationalError:
            pass
        # Spalte für die selbst gewählte Profilfarbe nachrüsten.
        try:
            self.conn.execute("ALTER TABLE profiles ADD COLUMN color INTEGER")
        except sqlite3.OperationalError:
            pass
        # Spalte für den Spiel-Bezug eigener Karten nachrüsten.
        try:
            self.conn.execute("ALTER TABLE custom_cards ADD COLUMN game TEXT")
        except sqlite3.OperationalError:
            pass
        # Spalte für den Karten-Drop-Channel nachrüsten.
        try:
            self.conn.execute("ALTER TABLE guild_settings ADD COLUMN card_channel_id INTEGER")
        except sqlite3.OperationalError:
            pass
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # --- Leveling -------------------------------------------------------------

    def get_user(self, guild_id: int, user_id: int) -> sqlite3.Row:
        """Gibt die Level-Zeile zurück; legt sie bei Bedarf mit Defaults an."""
        self.conn.execute(
            "INSERT OR IGNORE INTO levels (guild_id, user_id) VALUES (?, ?)",
            (guild_id, user_id),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT * FROM levels WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        return row

    def update_user(
        self,
        guild_id: int,
        user_id: int,
        *,
        xp: int,
        level: int,
        coins: int,
        last_msg_ts: Optional[float] = None,
    ) -> None:
        if last_msg_ts is None:
            self.conn.execute(
                "UPDATE levels SET xp = ?, level = ?, coins = ? "
                "WHERE guild_id = ? AND user_id = ?",
                (xp, level, coins, guild_id, user_id),
            )
        else:
            self.conn.execute(
                "UPDATE levels SET xp = ?, level = ?, coins = ?, last_msg_ts = ? "
                "WHERE guild_id = ? AND user_id = ?",
                (xp, level, coins, last_msg_ts, guild_id, user_id),
            )
        self.conn.commit()

    def add_coins(self, guild_id: int, user_id: int, amount: int) -> int:
        """Schreibt Coins gut und gibt den neuen Kontostand zurück."""
        self.get_user(guild_id, user_id)
        self.conn.execute(
            "UPDATE levels SET coins = coins + ? WHERE guild_id = ? AND user_id = ?",
            (amount, guild_id, user_id),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT coins FROM levels WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        return int(row["coins"])

    def leaderboard(self, guild_id: int, limit: int = 10) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT user_id, xp, level, coins FROM levels WHERE guild_id = ? "
            "ORDER BY xp DESC LIMIT ?",
            (guild_id, limit),
        ).fetchall()

    # --- Guild-Settings -------------------------------------------------------

    def _ensure_settings(self, guild_id: int) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)", (guild_id,)
        )
        self.conn.commit()

    def set_levelup_channel(self, guild_id: int, channel_id: Optional[int]) -> None:
        self._ensure_settings(guild_id)
        self.conn.execute(
            "UPDATE guild_settings SET levelup_channel_id = ? WHERE guild_id = ?",
            (channel_id, guild_id),
        )
        self.conn.commit()

    def get_levelup_channel(self, guild_id: int) -> Optional[int]:
        row = self.conn.execute(
            "SELECT levelup_channel_id FROM guild_settings WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()
        return int(row["levelup_channel_id"]) if row and row["levelup_channel_id"] else None

    def set_announce_channel(self, guild_id: int, channel_id: Optional[int]) -> None:
        self._ensure_settings(guild_id)
        self.conn.execute(
            "UPDATE guild_settings SET announce_channel_id = ? WHERE guild_id = ?",
            (channel_id, guild_id),
        )
        self.conn.commit()

    def get_announce_channel(self, guild_id: int) -> Optional[int]:
        row = self.conn.execute(
            "SELECT announce_channel_id FROM guild_settings WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()
        return int(row["announce_channel_id"]) if row and row["announce_channel_id"] else None

    def set_card_channel(self, guild_id: int, channel_id: Optional[int]) -> None:
        self._ensure_settings(guild_id)
        self.conn.execute(
            "UPDATE guild_settings SET card_channel_id = ? WHERE guild_id = ?",
            (channel_id, guild_id),
        )
        self.conn.commit()

    def get_card_channel(self, guild_id: int) -> Optional[int]:
        row = self.conn.execute(
            "SELECT card_channel_id FROM guild_settings WHERE guild_id = ?", (guild_id,)
        ).fetchone()
        return int(row["card_channel_id"]) if row and row["card_channel_id"] else None

    # --- Feeds ----------------------------------------------------------------

    def add_feed(
        self, guild_id: int, feed_url: str, label: Optional[str], kind: str, last_entry_id: Optional[str]
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO feeds (guild_id, feed_url, label, kind, last_entry_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (guild_id, feed_url, label, kind, last_entry_id),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def remove_feed(self, guild_id: int, feed_id: int) -> bool:
        cur = self.conn.execute(
            "DELETE FROM feeds WHERE guild_id = ? AND id = ?", (guild_id, feed_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def list_feeds(self, guild_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM feeds WHERE guild_id = ? ORDER BY id", (guild_id,)
        ).fetchall()

    def all_feeds(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM feeds").fetchall()

    def update_feed_last_id(self, feed_id: int, last_entry_id: str) -> None:
        self.conn.execute(
            "UPDATE feeds SET last_entry_id = ? WHERE id = ?", (last_entry_id, feed_id)
        )
        self.conn.commit()

    # --- Profil / Rang --------------------------------------------------------

    def rank_position(self, guild_id: int, user_id: int) -> tuple[int, int]:
        """Gibt (Platz, Gesamtanzahl) des Users nach XP zurück (Platz 1 = beste)."""
        row = self.conn.execute(
            "SELECT xp FROM levels WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        total = self.conn.execute(
            "SELECT COUNT(*) AS c FROM levels WHERE guild_id = ?", (guild_id,)
        ).fetchone()["c"]
        if row is None:
            return total + 1, total
        ahead = self.conn.execute(
            "SELECT COUNT(*) AS c FROM levels WHERE guild_id = ? AND xp > ?",
            (guild_id, int(row["xp"])),
        ).fetchone()["c"]
        return ahead + 1, total

    def set_bio(self, guild_id: int, user_id: int, bio: Optional[str]) -> None:
        self.conn.execute(
            "INSERT INTO profiles (guild_id, user_id, bio) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET bio = excluded.bio",
            (guild_id, user_id, bio),
        )
        self.conn.commit()

    def get_bio(self, guild_id: int, user_id: int) -> Optional[str]:
        row = self.conn.execute(
            "SELECT bio FROM profiles WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        return row["bio"] if row else None

    def set_profile_color(self, guild_id: int, user_id: int, color: Optional[int]) -> None:
        self.conn.execute(
            "INSERT INTO profiles (guild_id, user_id, color) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET color = excluded.color",
            (guild_id, user_id, color),
        )
        self.conn.commit()

    def get_profile_color(self, guild_id: int, user_id: int) -> Optional[int]:
        row = self.conn.execute(
            "SELECT color FROM profiles WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        return int(row["color"]) if row and row["color"] is not None else None

    # --- Spiel-Statistik (Coinflip, Blackjack, Slots, …) ----------------------

    def record_game(self, guild_id: int, user_id: int, game: str, outcome: str) -> None:
        """Zählt ein Spiel. outcome ist 'win', 'loss' oder 'push' (Push zählt nur als Spiel)."""
        win = 1 if outcome == "win" else 0
        loss = 1 if outcome == "loss" else 0
        self.conn.execute(
            "INSERT INTO game_stats (guild_id, user_id, game, games, wins, losses) "
            "VALUES (?, ?, ?, 1, ?, ?) "
            "ON CONFLICT(guild_id, user_id, game) DO UPDATE SET "
            "games = games + 1, wins = wins + ?, losses = losses + ?",
            (guild_id, user_id, game, win, loss, win, loss),
        )
        self.conn.commit()

    def get_game_stats(self, guild_id: int, user_id: int, game: str) -> tuple[int, int, int]:
        """Gibt (Spiele, Gewinne, Verluste) für ein Spiel zurück."""
        row = self.conn.execute(
            "SELECT games, wins, losses FROM game_stats "
            "WHERE guild_id = ? AND user_id = ? AND game = ?",
            (guild_id, user_id, game),
        ).fetchone()
        if row is None:
            return 0, 0, 0
        return int(row["games"]), int(row["wins"]), int(row["losses"])

    # --- Daily ----------------------------------------------------------------

    def get_daily(self, guild_id: int, user_id: int) -> tuple[float, int]:
        """Gibt (letzter Claim als Unix-Zeit, Streak) zurück."""
        row = self.conn.execute(
            "SELECT last_claim, streak FROM daily WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        if row is None:
            return 0.0, 0
        return float(row["last_claim"]), int(row["streak"])

    def set_daily(self, guild_id: int, user_id: int, last_claim: float, streak: int) -> None:
        self.conn.execute(
            "INSERT INTO daily (guild_id, user_id, last_claim, streak) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
            "last_claim = excluded.last_claim, streak = excluded.streak",
            (guild_id, user_id, last_claim, streak),
        )
        self.conn.commit()

    # --- Effekte (Shop-Boosts) ------------------------------------------------

    def add_charges(self, guild_id: int, user_id: int, effect: str, amount: int) -> None:
        self.conn.execute(
            "INSERT INTO effects (guild_id, user_id, effect, charges) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id, user_id, effect) DO UPDATE SET charges = charges + ?",
            (guild_id, user_id, effect, amount, amount),
        )
        self.conn.commit()

    def get_charges(self, guild_id: int, user_id: int, effect: str) -> int:
        row = self.conn.execute(
            "SELECT charges FROM effects WHERE guild_id = ? AND user_id = ? AND effect = ?",
            (guild_id, user_id, effect),
        ).fetchone()
        return int(row["charges"]) if row else 0

    def consume_charge(self, guild_id: int, user_id: int, effect: str) -> bool:
        """Verbraucht eine Ladung; gibt True zurück, wenn eine vorhanden war."""
        if self.get_charges(guild_id, user_id, effect) <= 0:
            return False
        self.conn.execute(
            "UPDATE effects SET charges = charges - 1 "
            "WHERE guild_id = ? AND user_id = ? AND effect = ?",
            (guild_id, user_id, effect),
        )
        self.conn.commit()
        return True

    def extend_expires(self, guild_id: int, user_id: int, effect: str, now: float, seconds: float) -> float:
        """Verlängert einen zeitbasierten Effekt (ab jetzt oder ab Restlaufzeit). Gibt neues Ende zurück."""
        current = self.get_expires(guild_id, user_id, effect)
        base = max(current, now)
        new_expiry = base + seconds
        self.conn.execute(
            "INSERT INTO effects (guild_id, user_id, effect, expires) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id, user_id, effect) DO UPDATE SET expires = ?",
            (guild_id, user_id, effect, new_expiry, new_expiry),
        )
        self.conn.commit()
        return new_expiry

    def get_expires(self, guild_id: int, user_id: int, effect: str) -> float:
        row = self.conn.execute(
            "SELECT expires FROM effects WHERE guild_id = ? AND user_id = ? AND effect = ?",
            (guild_id, user_id, effect),
        ).fetchone()
        return float(row["expires"]) if row else 0.0

    # --- LFG-Rolle ------------------------------------------------------------

    def set_lfg_role(self, guild_id: int, role_id: int | None) -> None:
        self._ensure_settings(guild_id)
        self.conn.execute(
            "UPDATE guild_settings SET lfg_role_id = ? WHERE guild_id = ?", (role_id, guild_id)
        )
        self.conn.commit()

    def get_lfg_role(self, guild_id: int) -> int | None:
        row = self.conn.execute(
            "SELECT lfg_role_id FROM guild_settings WHERE guild_id = ?", (guild_id,)
        ).fetchone()
        return int(row["lfg_role_id"]) if row and row["lfg_role_id"] else None

    # --- Interactions (Zähler) ------------------------------------------------

    def add_interaction(self, guild_id: int, actor_id: int, target_id: int, action: str) -> int:
        """Erhöht den Zähler 'actor hat target X-mal <action>' und gibt den neuen Wert zurück."""
        self.conn.execute(
            "INSERT INTO interactions (guild_id, actor_id, target_id, action, count) "
            "VALUES (?, ?, ?, ?, 1) "
            "ON CONFLICT(guild_id, actor_id, target_id, action) DO UPDATE SET count = count + 1",
            (guild_id, actor_id, target_id, action),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT count FROM interactions WHERE guild_id = ? AND actor_id = ? "
            "AND target_id = ? AND action = ?",
            (guild_id, actor_id, target_id, action),
        ).fetchone()
        return int(row["count"])

    # --- Freundschaften -------------------------------------------------------

    @staticmethod
    def _pair(a: int, b: int) -> tuple[int, int]:
        return (a, b) if a < b else (b, a)

    def get_friend_row(self, guild_id: int, a: int, b: int):
        lo, hi = self._pair(a, b)
        return self.conn.execute(
            "SELECT * FROM friendships WHERE guild_id = ? AND user_a = ? AND user_b = ?",
            (guild_id, lo, hi),
        ).fetchone()

    def _ensure_pair(self, guild_id: int, a: int, b: int) -> None:
        lo, hi = self._pair(a, b)
        self.conn.execute(
            "INSERT OR IGNORE INTO friendships (guild_id, user_a, user_b) VALUES (?, ?, ?)",
            (guild_id, lo, hi),
        )

    def _set_status(self, guild_id: int, a: int, b: int, status: str | None, requester: int | None) -> None:
        lo, hi = self._pair(a, b)
        self.conn.execute(
            "UPDATE friendships SET status = ?, requester = ? "
            "WHERE guild_id = ? AND user_a = ? AND user_b = ?",
            (status, requester, guild_id, lo, hi),
        )
        self.conn.commit()

    def add_friend_xp(self, guild_id: int, a: int, b: int, amount: int) -> int:
        self._ensure_pair(guild_id, a, b)
        lo, hi = self._pair(a, b)
        self.conn.execute(
            "UPDATE friendships SET xp = xp + ? WHERE guild_id = ? AND user_a = ? AND user_b = ?",
            (amount, guild_id, lo, hi),
        )
        self.conn.commit()
        row = self.get_friend_row(guild_id, a, b)
        return int(row["xp"]) if row else 0

    def friendship_xp(self, guild_id: int, a: int, b: int) -> int:
        row = self.get_friend_row(guild_id, a, b)
        return int(row["xp"]) if row else 0

    def send_friend_request(self, guild_id: int, requester: int, target: int) -> str:
        """Verarbeitet eine Freundschaftsanfrage. Rückgabe-Code für die UI."""
        row = self.get_friend_row(guild_id, requester, target)
        if row and row["status"] == "accepted":
            return "already_friends"
        if row and row["status"] == "pending":
            if row["requester"] == requester:
                return "already_pending"
            # Gegenseitige Anfrage → direkt befreundet.
            self._set_status(guild_id, requester, target, "accepted", None)
            return "accepted_now"
        self._ensure_pair(guild_id, requester, target)
        self._set_status(guild_id, requester, target, "pending", requester)
        return "requested"

    def accept_friend(self, guild_id: int, user: int, other: int) -> bool:
        """Nimmt eine eingehende Anfrage an (user darf nicht der Anfragende sein)."""
        row = self.get_friend_row(guild_id, user, other)
        if not row or row["status"] != "pending" or row["requester"] == user:
            return False
        self._set_status(guild_id, user, other, "accepted", None)
        return True

    def remove_friend(self, guild_id: int, user: int, other: int) -> bool:
        """Entfernt Freundschaft/offene Anfrage (XP-Historie bleibt erhalten)."""
        row = self.get_friend_row(guild_id, user, other)
        if not row or row["status"] is None:
            return False
        self._set_status(guild_id, user, other, None, None)
        return True

    def list_friends(self, guild_id: int, user: int) -> list[tuple[int, int]]:
        """Akzeptierte Freunde: Liste von (andere_user_id, xp), nach XP sortiert."""
        rows = self.conn.execute(
            "SELECT user_a, user_b, xp FROM friendships "
            "WHERE guild_id = ? AND status = 'accepted' AND (user_a = ? OR user_b = ?) "
            "ORDER BY xp DESC",
            (guild_id, user, user),
        ).fetchall()
        result = []
        for r in rows:
            other = r["user_b"] if r["user_a"] == user else r["user_a"]
            result.append((int(other), int(r["xp"])))
        return result

    def list_incoming_requests(self, guild_id: int, user: int) -> list[int]:
        """IDs der User, die user eine offene Anfrage geschickt haben."""
        rows = self.conn.execute(
            "SELECT requester FROM friendships "
            "WHERE guild_id = ? AND status = 'pending' AND requester IS NOT NULL "
            "AND requester != ? AND (user_a = ? OR user_b = ?)",
            (guild_id, user, user, user),
        ).fetchall()
        return [int(r["requester"]) for r in rows]

    # --- Ehen -----------------------------------------------------------------

    def are_married(self, guild_id: int, a: int, b: int) -> bool:
        return self.get_marriage_row(guild_id, a, b) is not None

    def get_marriage_row(self, guild_id: int, a: int, b: int):
        lo, hi = self._pair(a, b)
        return self.conn.execute(
            "SELECT * FROM marriages WHERE guild_id = ? AND user_a = ? AND user_b = ?",
            (guild_id, lo, hi),
        ).fetchone()

    def add_marriage(self, guild_id: int, a: int, b: int, since: float) -> None:
        lo, hi = self._pair(a, b)
        self.conn.execute(
            "INSERT OR IGNORE INTO marriages (guild_id, user_a, user_b, since) VALUES (?, ?, ?, ?)",
            (guild_id, lo, hi, since),
        )
        self.conn.commit()

    def remove_marriage(self, guild_id: int, a: int, b: int) -> bool:
        lo, hi = self._pair(a, b)
        cur = self.conn.execute(
            "DELETE FROM marriages WHERE guild_id = ? AND user_a = ? AND user_b = ?",
            (guild_id, lo, hi),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def list_marriages(self, guild_id: int, user: int) -> list[tuple[int, float]]:
        rows = self.conn.execute(
            "SELECT user_a, user_b, since FROM marriages "
            "WHERE guild_id = ? AND (user_a = ? OR user_b = ?) ORDER BY since",
            (guild_id, user, user),
        ).fetchall()
        out = []
        for r in rows:
            other = r["user_b"] if r["user_a"] == user else r["user_a"]
            out.append((int(other), float(r["since"])))
        return out

    # --- Titel ----------------------------------------------------------------

    def set_title(self, guild_id: int, user_id: int, title: str | None) -> None:
        self.conn.execute(
            "INSERT INTO titles (guild_id, user_id, title) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET title = excluded.title",
            (guild_id, user_id, title),
        )
        self.conn.commit()

    def get_title(self, guild_id: int, user_id: int) -> str | None:
        row = self.conn.execute(
            "SELECT title FROM titles WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        return row["title"] if row else None

    # --- Sammelkarten ---------------------------------------------------------

    def add_card(self, guild_id: int, user_id: int, card_id: str, amount: int = 1) -> int:
        self.conn.execute(
            "INSERT INTO card_inventory (guild_id, user_id, card_id, count) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id, user_id, card_id) DO UPDATE SET count = count + ?",
            (guild_id, user_id, card_id, amount, amount),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT count FROM card_inventory WHERE guild_id = ? AND user_id = ? AND card_id = ?",
            (guild_id, user_id, card_id),
        ).fetchone()
        return int(row["count"])

    def get_collection(self, guild_id: int, user_id: int) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT card_id, count FROM card_inventory WHERE guild_id = ? AND user_id = ? AND count > 0",
            (guild_id, user_id),
        ).fetchall()
        return {r["card_id"]: int(r["count"]) for r in rows}

    def _card_count(self, guild_id: int, user_id: int, card_id: str) -> int:
        row = self.conn.execute(
            "SELECT count FROM card_inventory WHERE guild_id = ? AND user_id = ? AND card_id = ?",
            (guild_id, user_id, card_id),
        ).fetchone()
        return int(row["count"]) if row else 0

    def trade_cards(
        self, guild_id: int, user_a: int, card_a: str, user_b: int, card_b: str
    ) -> bool:
        """Tauscht je eine Karte zwischen zwei Usern atomar. False, wenn jemand die Karte nicht (mehr) hat."""
        if self._card_count(guild_id, user_a, card_a) < 1:
            return False
        if self._card_count(guild_id, user_b, card_b) < 1:
            return False
        # Eine Transaktion: beide Karten weg, beide neuen Karten dazu.
        self.conn.execute(
            "UPDATE card_inventory SET count = count - 1 WHERE guild_id = ? AND user_id = ? AND card_id = ?",
            (guild_id, user_a, card_a),
        )
        self.conn.execute(
            "UPDATE card_inventory SET count = count - 1 WHERE guild_id = ? AND user_id = ? AND card_id = ?",
            (guild_id, user_b, card_b),
        )
        for uid, cid in ((user_b, card_a), (user_a, card_b)):
            self.conn.execute(
                "INSERT INTO card_inventory (guild_id, user_id, card_id, count) VALUES (?, ?, ?, 1) "
                "ON CONFLICT(guild_id, user_id, card_id) DO UPDATE SET count = count + 1",
                (guild_id, uid, cid),
            )
        self.conn.commit()
        return True

    def add_custom_card(
        self, guild_id: int, card_id: str, name: str, rarity: str, image_url: str | None, game: str
    ) -> None:
        self.conn.execute(
            "INSERT INTO custom_cards (guild_id, card_id, name, rarity, image_url, game) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(guild_id, card_id) DO UPDATE SET "
            "name = excluded.name, rarity = excluded.rarity, "
            "image_url = excluded.image_url, game = excluded.game",
            (guild_id, card_id, name, rarity, image_url, game.lower()),
        )
        self.conn.commit()

    def remove_custom_card(self, guild_id: int, card_id: str) -> bool:
        cur = self.conn.execute(
            "DELETE FROM custom_cards WHERE guild_id = ? AND card_id = ?", (guild_id, card_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def list_custom_cards(self, guild_id: int) -> list[tuple[str, str, str, str | None, str | None]]:
        rows = self.conn.execute(
            "SELECT card_id, name, rarity, image_url, game FROM custom_cards WHERE guild_id = ?",
            (guild_id,),
        ).fetchall()
        return [(r["card_id"], r["name"], r["rarity"], r["image_url"], r["game"]) for r in rows]

    def list_custom_cards_for_game(self, guild_id: int, game: str) -> list[tuple[str, str, str, str | None]]:
        rows = self.conn.execute(
            "SELECT card_id, name, rarity, image_url FROM custom_cards WHERE guild_id = ? AND game = ?",
            (guild_id, game.lower()),
        ).fetchall()
        return [(r["card_id"], r["name"], r["rarity"], r["image_url"]) for r in rows]

    # --- Server-Sammelkarten (Booster) ----------------------------------------

    def add_server_card(self, guild_id: int, card_id: str, name: str, rarity: str, image_url: str | None) -> None:
        self.conn.execute(
            "INSERT INTO server_cards (guild_id, card_id, name, rarity, image_url) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(guild_id, card_id) DO UPDATE SET "
            "name = excluded.name, rarity = excluded.rarity, image_url = excluded.image_url",
            (guild_id, card_id, name, rarity, image_url),
        )
        self.conn.commit()

    def remove_server_card(self, guild_id: int, card_id: str) -> bool:
        cur = self.conn.execute(
            "DELETE FROM server_cards WHERE guild_id = ? AND card_id = ?", (guild_id, card_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def list_server_cards(self, guild_id: int) -> list[tuple[str, str, str, str | None]]:
        rows = self.conn.execute(
            "SELECT card_id, name, rarity, image_url FROM server_cards WHERE guild_id = ?",
            (guild_id,),
        ).fetchall()
        return [(r["card_id"], r["name"], r["rarity"], r["image_url"]) for r in rows]

    def add_server_card_owned(self, guild_id: int, user_id: int, card_id: str, amount: int = 1) -> None:
        self.conn.execute(
            "INSERT INTO server_inventory (guild_id, user_id, card_id, count) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id, user_id, card_id) DO UPDATE SET count = count + ?",
            (guild_id, user_id, card_id, amount, amount),
        )
        self.conn.commit()

    def get_server_collection(self, guild_id: int, user_id: int) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT card_id, count FROM server_inventory WHERE guild_id = ? AND user_id = ? AND count > 0",
            (guild_id, user_id),
        ).fetchall()
        return {r["card_id"]: int(r["count"]) for r in rows}

    # --- Booster-Packs --------------------------------------------------------

    def add_packs(self, guild_id: int, user_id: int, pack_type: str, amount: int) -> int:
        self.conn.execute(
            "INSERT INTO packs (guild_id, user_id, pack_type, count) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id, user_id, pack_type) DO UPDATE SET count = count + ?",
            (guild_id, user_id, pack_type, amount, amount),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT count FROM packs WHERE guild_id = ? AND user_id = ? AND pack_type = ?",
            (guild_id, user_id, pack_type),
        ).fetchone()
        return int(row["count"])

    def get_pack_count(self, guild_id: int, user_id: int, pack_type: str) -> int:
        row = self.conn.execute(
            "SELECT count FROM packs WHERE guild_id = ? AND user_id = ? AND pack_type = ?",
            (guild_id, user_id, pack_type),
        ).fetchone()
        return int(row["count"]) if row else 0

    def list_packs(self, guild_id: int, user_id: int) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT pack_type, count FROM packs WHERE guild_id = ? AND user_id = ? AND count > 0",
            (guild_id, user_id),
        ).fetchall()
        return {r["pack_type"]: int(r["count"]) for r in rows}

    def consume_pack(self, guild_id: int, user_id: int, pack_type: str) -> bool:
        if self.get_pack_count(guild_id, user_id, pack_type) <= 0:
            return False
        self.conn.execute(
            "UPDATE packs SET count = count - 1 WHERE guild_id = ? AND user_id = ? AND pack_type = ?",
            (guild_id, user_id, pack_type),
        )
        self.conn.commit()
        return True

    # --- Belohnungs-Spiele ----------------------------------------------------

    def add_reward_game(self, guild_id: int, game: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO reward_games (guild_id, game) VALUES (?, ?)",
            (guild_id, game.lower()),
        )
        self.conn.commit()

    def remove_reward_game(self, guild_id: int, game: str) -> bool:
        cur = self.conn.execute(
            "DELETE FROM reward_games WHERE guild_id = ? AND game = ?", (guild_id, game.lower())
        )
        self.conn.commit()
        return cur.rowcount > 0

    def list_reward_games(self, guild_id: int) -> list[str]:
        rows = self.conn.execute(
            "SELECT game FROM reward_games WHERE guild_id = ? ORDER BY game", (guild_id,)
        ).fetchall()
        return [r["game"] for r in rows]

    def is_reward_game(self, guild_id: int, game: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM reward_games WHERE guild_id = ? AND game = ?",
            (guild_id, game.lower()),
        ).fetchone() is not None

    # --- Spielzeit (Karten-Rewards) -------------------------------------------

    def get_playtime(self, guild_id: int, user_id: int) -> tuple[int, str | None, int]:
        row = self.conn.execute(
            "SELECT accumulated, day, cards_today FROM playtime WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        if row is None:
            return 0, None, 0
        return int(row["accumulated"]), row["day"], int(row["cards_today"])

    def set_playtime(
        self, guild_id: int, user_id: int, accumulated: int, day: str, cards_today: int
    ) -> None:
        self.conn.execute(
            "INSERT INTO playtime (guild_id, user_id, accumulated, day, cards_today) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
            "accumulated = excluded.accumulated, day = excluded.day, cards_today = excluded.cards_today",
            (guild_id, user_id, accumulated, day, cards_today),
        )
        self.conn.commit()

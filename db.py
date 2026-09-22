"""SQLite-Datenzugriff für Leveling und Announcer.

Eine einzige Verbindung wird über den gesamten Bot geteilt. Da der Bot
single-threaded im Event-Loop läuft und die Queries winzig sind, sind synchrone
sqlite3-Aufrufe hier unproblematisch.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Optional

# Speicherort der Datenbank. Über DATA_DIR umlenkbar (z.B. /data in Containern),
# damit die DB einen persistenten Ordner bekommt. Lokal: aktuelles Verzeichnis.
DB_FILE: str = os.path.join(os.environ.get("DATA_DIR", "."), "bot.db")

# Server-übergreifende ("globale") Daten werden unter dieser Pseudo-Guild-ID
# gespeichert: Coins, XP, Level, Karten, Inventare, Packs, Daily und Shop-Effekte
# gehören dem User über alle Server hinweg. Die Cogs übergeben weiterhin ihre echte
# guild_id; die betroffenen Methoden normalisieren sie intern auf GLOBAL_GID.
# Pro Server bleiben dagegen: Channels/Settings, getrackte Reward-Spiele, Feeds
# sowie Profil- und Statistik-Tabellen. Freundschaften und Friendship-XP sind global.
GLOBAL_GID: int = 0


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
            -- Leaderboard sortiert nach xp DESC (globales Brett, eine guild_id):
            -- ohne diesen Index müsste SQLite bei jedem Aufruf alle Zeilen sortieren.
            CREATE INDEX IF NOT EXISTS idx_levels_xp ON levels (guild_id, xp DESC);

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

            -- Eine Lieblingskarte je Spiel (zum Durchblättern im /profile).
            CREATE TABLE IF NOT EXISTS fav_game_cards (
                guild_id INTEGER NOT NULL,
                user_id  INTEGER NOT NULL,
                game     TEXT    NOT NULL,
                card_id  TEXT    NOT NULL,
                PRIMARY KEY (guild_id, user_id, game)
            );

            -- Per Dashboard gesendete Nachrichten (zum späteren Bearbeiten).
            CREATE TABLE IF NOT EXISTS announcements (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id   INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                as_embed   INTEGER NOT NULL DEFAULT 0,
                title      TEXT,
                content    TEXT,
                color      TEXT,
                image_url  TEXT,
                ping_roles TEXT,
                created_at INTEGER NOT NULL
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

            -- Arkansplitter aus zerlegten Spielkarten. Wie Karten und Packs ist
            -- das Guthaben global pro Discord-User, unabhängig vom Server.
            CREATE TABLE IF NOT EXISTS card_shards (
                guild_id INTEGER NOT NULL,
                user_id  INTEGER NOT NULL,
                balance  INTEGER NOT NULL DEFAULT 0 CHECK (balance >= 0),
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS reward_games (
                guild_id     INTEGER NOT NULL,
                game         TEXT    NOT NULL,   -- kleingeschrieben für Matching
                interval_min INTEGER NOT NULL DEFAULT 30,  -- Minuten pro Karte
                daily_cap    INTEGER NOT NULL DEFAULT 12,   -- max. Karten/Tag
                PRIMARY KEY (guild_id, game)
            );

            CREATE TABLE IF NOT EXISTS reward_game_aliases (
                guild_id INTEGER NOT NULL,
                alias    TEXT    NOT NULL,   -- Discord-Presence-Name, z.B. Tracker-App
                game     TEXT    NOT NULL,   -- kanonisches Reward-Spiel
                PRIMARY KEY (guild_id, alias)
            );

            CREATE TABLE IF NOT EXISTS reward_notify (
                user_id  INTEGER PRIMARY KEY,   -- global pro User
                guild_id INTEGER NOT NULL       -- Wunsch-Server für Drop-Meldungen
            );

            CREATE TABLE IF NOT EXISTS playtime (
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                game        TEXT    NOT NULL DEFAULT '',  -- Tracking pro Spiel
                accumulated INTEGER NOT NULL DEFAULT 0,  -- Sekunden Richtung nächster Karte
                day         TEXT,                        -- YYYY-MM-DD (Tages-Cap)
                cards_today INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, game)
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

            CREATE TABLE IF NOT EXISTS reaction_roles (
                guild_id   INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                emoji      TEXT    NOT NULL,   -- Unicode-Emoji oder Custom "name:id"
                role_id    INTEGER NOT NULL,
                required_role_id INTEGER,       -- optionale Voraussetzungs-Rolle (NULL = jeder)
                PRIMARY KEY (guild_id, message_id, emoji)
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id   INTEGER NOT NULL,
                ts         REAL    NOT NULL,
                category   TEXT    NOT NULL,   -- messages|voice|members|roles|channels
                event_type TEXT    NOT NULL,   -- z.B. message_delete
                actor_id   INTEGER,
                target_id  INTEGER,
                channel_id INTEGER,
                summary    TEXT    NOT NULL,
                detail     TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_audit_guild ON audit_log (guild_id, id DESC);

            CREATE TABLE IF NOT EXISTS audit_settings (
                guild_id INTEGER NOT NULL,
                category TEXT    NOT NULL,
                enabled  INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (guild_id, category)
            );

            -- Manuelle Verwarnungen bleiben pro Server dauerhaft nachvollziehbar.
            CREATE TABLE IF NOT EXISTS warnings (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id     INTEGER NOT NULL,
                user_id      INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason       TEXT    NOT NULL,
                created_at   REAL    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_warnings_guild_user
                ON warnings (guild_id, user_id, id DESC);

            -- Dynamische Join-to-Create-Voice-Channels und ihre Besitzer.
            CREATE TABLE IF NOT EXISTS temp_voice_channels (
                channel_id INTEGER PRIMARY KEY,
                guild_id   INTEGER NOT NULL,
                owner_id   INTEGER NOT NULL,
                created_at REAL    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_temp_voice_guild
                ON temp_voice_channels (guild_id);

            -- Ticket-System: pro Server konfigurierbare Themen (Panel-Buttons).
            CREATE TABLE IF NOT EXISTS ticket_categories (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                label       TEXT    NOT NULL,
                emoji       TEXT,
                description TEXT,
                position    INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_ticket_cat_guild
                ON ticket_categories (guild_id, position);

            -- Offene/geschlossene Tickets (je ein privater Thread).
            CREATE TABLE IF NOT EXISTS tickets (
                thread_id      INTEGER PRIMARY KEY,
                guild_id       INTEGER NOT NULL,
                channel_id     INTEGER NOT NULL,   -- Eltern-Channel des Threads
                opener_id      INTEGER NOT NULL,
                category_id    INTEGER,
                category_label TEXT    NOT NULL DEFAULT 'Support',
                claimed_by     INTEGER,
                status         TEXT    NOT NULL DEFAULT 'open',  -- open|closed
                number         INTEGER NOT NULL,
                created_at     REAL    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tickets_guild
                ON tickets (guild_id, status);

            -- Gespeicherte Ticket-Transcripts (für die Web-Ansicht unter /t/<token>).
            CREATE TABLE IF NOT EXISTS ticket_transcripts (
                token          TEXT PRIMARY KEY,
                thread_id      INTEGER,
                guild_id       INTEGER NOT NULL,
                number         INTEGER NOT NULL,
                category_label TEXT,
                opener_id      INTEGER,
                opener_name    TEXT,
                closed_by_id   INTEGER,
                closed_by_name TEXT,
                closed_at      REAL    NOT NULL,
                message_count  INTEGER NOT NULL DEFAULT 0,
                data           TEXT    NOT NULL   -- JSON: Liste der Nachrichten
            );
            CREATE INDEX IF NOT EXISTS idx_transcripts_guild
                ON ticket_transcripts (guild_id, closed_at DESC);

            -- WebPanel-Sessions: bleiben über Bot-Neustarts erhalten, bis exp erreicht ist.
            CREATE TABLE IF NOT EXISTS web_sessions (
                token   TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                exp     REAL    NOT NULL,
                data    TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_web_sessions_exp
                ON web_sessions (exp);

            -- Globale Steam-artige Achievements. Definitionen leben im Cog;
            -- SQLite speichert nur Freischaltungen und den Backfill-Status.
            CREATE TABLE IF NOT EXISTS achievements (
                user_id        INTEGER NOT NULL,
                achievement_id TEXT    NOT NULL,
                unlocked_at    REAL    NOT NULL,
                PRIMARY KEY (user_id, achievement_id)
            );
            CREATE INDEX IF NOT EXISTS idx_achievements_user
                ON achievements (user_id, unlocked_at);

            CREATE TABLE IF NOT EXISTS achievement_users (
                user_id        INTEGER PRIMARY KEY,
                initialized_at REAL NOT NULL
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
        # Spalte für die Lieblingskarte (Karten-ID) nachrüsten.
        try:
            self.conn.execute("ALTER TABLE profiles ADD COLUMN fav_card TEXT")
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
        # Willkommensnachrichten (an/aus, Channel, Text mit Platzhaltern) nachrüsten.
        for col, ddl in (
            ("welcome_enabled", "INTEGER NOT NULL DEFAULT 0"),
            ("welcome_channel_id", "INTEGER"),
            ("welcome_message", "TEXT"),
            ("welcome_image", "TEXT"),
            ("audit_channel_id", "INTEGER"),
            # Ticket-System
            ("ticket_enabled", "INTEGER NOT NULL DEFAULT 0"),
            ("ticket_panel_channel_id", "INTEGER"),
            ("ticket_panel_message_id", "INTEGER"),
            ("ticket_support_role_id", "INTEGER"),
            ("ticket_log_channel_id", "INTEGER"),
            ("ticket_panel_title", "TEXT"),
            ("ticket_panel_text", "TEXT"),
            ("ticket_counter", "INTEGER NOT NULL DEFAULT 0"),
            # Level-Up: eigener Text (leer = Standard-Embed) + Ping an/aus.
            ("levelup_message", "TEXT"),
            ("levelup_ping", "INTEGER NOT NULL DEFAULT 1"),
            # Bot-Serverprofil: Nickname + (server-spezifischer) Avatar-URL.
            ("bot_nick", "TEXT"),
            ("bot_avatar", "TEXT"),
            # Auto-Rollen: beim Join automatisch vergebene Rollen.
            ("autoroles_enabled", "INTEGER NOT NULL DEFAULT 0"),
            ("autoroles_role_ids", "TEXT"),
            # Boost-Nachrichten: beim Server-Boost eines Mitglieds posten.
            ("boost_enabled", "INTEGER NOT NULL DEFAULT 0"),
            ("boost_channel_id", "INTEGER"),
            ("boost_message", "TEXT"),
            ("boost_mention", "INTEGER NOT NULL DEFAULT 1"),
            ("boost_image", "TEXT"),
            # Twitch-Live-Benachrichtigungen: Kanal, Discord-Ziel und optionaler Rollen-Ping.
            ("twitch_enabled", "INTEGER NOT NULL DEFAULT 0"),
            ("twitch_login", "TEXT"),
            ("twitch_channel_id", "INTEGER"),
            ("twitch_message", "TEXT"),
            ("twitch_mention_role_id", "INTEGER"),
            ("twitch_last_stream_id", "TEXT"),
            # AutoMod: Anti-Spam, neue User, @everyone/@here-Unterdrückung.
            ("automod_enabled", "INTEGER NOT NULL DEFAULT 0"),
            ("automod_delete_mass_mentions", "INTEGER NOT NULL DEFAULT 1"),
            ("automod_exempt_role_ids", "TEXT"),
            ("automod_honeypot_channel_ids", "TEXT"),
            ("automod_honeypot_ban", "INTEGER NOT NULL DEFAULT 1"),
            ("automod_honeypot_delete_seconds", "INTEGER NOT NULL DEFAULT 604800"),
            # Join-to-Create Voice-System.
            ("voice_enabled", "INTEGER NOT NULL DEFAULT 0"),
            ("voice_lobby_id", "INTEGER"),
            ("voice_category_id", "INTEGER"),
        ):
            try:
                self.conn.execute(f"ALTER TABLE guild_settings ADD COLUMN {col} {ddl}")
            except sqlite3.OperationalError:
                pass
        # Pro-Spiel-Einstellungen für Karten-Rewards nachrüsten.
        for col, default in (("interval_min", 30), ("daily_cap", 12)):
            try:
                self.conn.execute(
                    f"ALTER TABLE reward_games ADD COLUMN {col} INTEGER NOT NULL DEFAULT {default}"
                )
            except sqlite3.OperationalError:
                pass
        # Pro-Spiel-Booster-Emote (Name eines Server-Emojis oder direkter Wert) nachrüsten.
        try:
            self.conn.execute("ALTER TABLE reward_games ADD COLUMN booster_emoji TEXT")
        except sqlite3.OperationalError:
            pass
        # Optionale Voraussetzungs-Rolle für Reaction Roles nachrüsten:
        # nur Mitglieder mit dieser Rolle bekommen die Reaction Role (NULL = jeder).
        try:
            self.conn.execute("ALTER TABLE reaction_roles ADD COLUMN required_role_id INTEGER")
        except sqlite3.OperationalError:
            pass
        # Playtime auf Pro-Spiel-Tracking umstellen (game-Spalte + neuer PK).
        # Die Tabelle hält nur transiente Tages-Zähler, daher gefahrlos neu aufbaubar.
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(playtime)").fetchall()]
        if cols and "game" not in cols:
            self.conn.execute("DROP TABLE playtime")
            self.conn.execute(
                "CREATE TABLE playtime ("
                "guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, game TEXT NOT NULL DEFAULT '', "
                "accumulated INTEGER NOT NULL DEFAULT 0, day TEXT, cards_today INTEGER NOT NULL DEFAULT 0, "
                "PRIMARY KEY (guild_id, user_id, game))"
            )
        self._migrate_global()
        self.conn.commit()

    def _migrate_card_definitions(self, table: str, inventory: str) -> None:
        """Erhält unterschiedliche Karten mit derselben bisherigen Server-ID."""
        fields = ["name", "rarity", "image_url"]
        if table == "custom_cards":
            fields.append("game")
        rows = self.conn.execute(
            f"SELECT * FROM {table} ORDER BY guild_id, card_id"
        ).fetchall()
        # Auch verwaiste Inventar-/Favoriten-IDs dürfen nicht neu vergeben werden.
        reserved = {r["card_id"] for r in rows}
        references = [(inventory, "card_id")]
        if table == "custom_cards":
            references.extend([("fav_game_cards", "card_id"), ("profiles", "fav_card")])
        for ref_table, column in references:
            reserved.update(r[0] for r in self.conn.execute(
                f"SELECT DISTINCT {column} FROM {ref_table}"
            ) if r[0] is not None)
        definitions = {
            r["card_id"]: tuple(r[f] for f in fields)
            for r in rows if r["guild_id"] == GLOBAL_GID
        }
        for row in rows:
            gid, original = row["guild_id"], row["card_id"]
            if gid == GLOBAL_GID:
                continue
            values = tuple(row[f] for f in fields)
            target = original
            if original in definitions and definitions[original] != values:
                base = f"{original}-guild-{gid}"
                target = base
                suffix = 2
                while target in reserved:
                    target = f"{base}-{suffix}"
                    suffix += 1
                reserved.add(target)
                self.conn.execute(
                    f"UPDATE {inventory} SET card_id = ? WHERE guild_id = ? AND card_id = ?",
                    (target, gid, original),
                )
                if table == "custom_cards":
                    self.conn.execute(
                        "UPDATE fav_game_cards SET card_id = ? WHERE guild_id = ? AND card_id = ?",
                        (target, gid, original),
                    )
                    self.conn.execute(
                        "UPDATE profiles SET fav_card = ? WHERE guild_id = ? AND fav_card = ?",
                        (target, gid, original),
                    )
            if target not in definitions:
                columns = ", ".join(fields)
                placeholders = ", ".join("?" for _ in range(2 + len(fields)))
                self.conn.execute(
                    f"INSERT INTO {table} (guild_id, card_id, {columns}) VALUES ({placeholders})",
                    (GLOBAL_GID, target, *values),
                )
                definitions[target] = values
        self.conn.execute(f"DELETE FROM {table} WHERE guild_id != ?", (GLOBAL_GID,))

    def _migrate_global(self) -> None:
        """Faltet die server-übergreifenden Tabellen auf guild_id = GLOBAL_GID zusammen.

        Idempotent: nach dem ersten Lauf existieren keine Zeilen mehr mit
        guild_id != GLOBAL_GID, ein erneuter Lauf ist ein No-Op. Bei mehreren
        Servern werden Coins/XP/Counts aufsummiert (relevant erst beim Mehr-Server-
        Betrieb; bei einem Server ist es ein reiner Umzug der Zeilen).
        """
        g = GLOBAL_GID

        # Levels: XP & Coins summieren, Level anschließend aus Gesamt-XP ableiten.
        self.conn.execute(
            "INSERT INTO levels (guild_id, user_id, xp, level, coins, last_msg_ts) "
            "SELECT ?, user_id, SUM(xp), MAX(level), SUM(coins), MAX(last_msg_ts) "
            "FROM levels WHERE guild_id != ? GROUP BY user_id "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
            "xp = xp + excluded.xp, coins = coins + excluded.coins, "
            "level = max(level, excluded.level), last_msg_ts = max(last_msg_ts, excluded.last_msg_ts)",
            (g, g),
        )
        self.conn.execute("DELETE FROM levels WHERE guild_id != ?", (g,))

        # Auch bereits global migrierte Datensätze mit veraltetem Level reparieren.
        # Dieselbe XP-Kurve wie leveling.level_from_total, ohne Discord-Abhängigkeit.
        for row in self.conn.execute(
            "SELECT user_id, xp, level FROM levels WHERE guild_id = ?", (g,)
        ).fetchall():
            level, remaining = 0, int(row["xp"])
            while remaining >= 5 * level ** 2 + 50 * level + 100:
                remaining -= 5 * level ** 2 + 50 * level + 100
                level += 1
            if level != row["level"]:
                self.conn.execute(
                    "UPDATE levels SET level = ? WHERE guild_id = ? AND user_id = ?",
                    (level, g, row["user_id"]),
                )

        # Daily: letzten Claim & Streak maximieren.
        self.conn.execute(
            "INSERT INTO daily (guild_id, user_id, last_claim, streak) "
            "SELECT ?, user_id, MAX(last_claim), MAX(streak) FROM daily WHERE guild_id != ? GROUP BY user_id "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
            "last_claim = max(last_claim, excluded.last_claim), streak = max(streak, excluded.streak)",
            (g, g),
        )
        self.conn.execute("DELETE FROM daily WHERE guild_id != ?", (g,))

        # Effekte: Ladungen summieren, Ablauf maximieren.
        self.conn.execute(
            "INSERT INTO effects (guild_id, user_id, effect, charges, expires) "
            "SELECT ?, user_id, effect, SUM(charges), MAX(expires) FROM effects WHERE guild_id != ? "
            "GROUP BY user_id, effect "
            "ON CONFLICT(guild_id, user_id, effect) DO UPDATE SET "
            "charges = charges + excluded.charges, expires = max(expires, excluded.expires)",
            (g, g),
        )
        self.conn.execute("DELETE FROM effects WHERE guild_id != ?", (g,))

        # Freundschaften: Status und Friendship-XP serverübergreifend vereinen.
        # Eine akzeptierte Freundschaft gewinnt vor einer offenen Anfrage; XP aus
        # allen bisherigen Server-Zeilen wird für das Paar aufsummiert.
        self.conn.execute(
            "INSERT INTO friendships (guild_id, user_a, user_b, status, requester, xp) "
            "SELECT ?, user_a, user_b, "
            "CASE MAX(CASE status WHEN 'accepted' THEN 2 WHEN 'pending' THEN 1 ELSE 0 END) "
            "WHEN 2 THEN 'accepted' WHEN 1 THEN 'pending' ELSE NULL END, "
            "CASE WHEN MAX(CASE status WHEN 'accepted' THEN 2 WHEN 'pending' THEN 1 ELSE 0 END) = 1 "
            "THEN MIN(CASE WHEN status = 'pending' THEN requester END) ELSE NULL END, "
            "SUM(xp) FROM friendships WHERE guild_id != ? GROUP BY user_a, user_b "
            "ON CONFLICT(guild_id, user_a, user_b) DO UPDATE SET "
            "xp = friendships.xp + excluded.xp, "
            "status = CASE "
            "WHEN friendships.status = 'accepted' OR excluded.status = 'accepted' THEN 'accepted' "
            "WHEN friendships.status = 'pending' OR excluded.status = 'pending' THEN 'pending' "
            "ELSE NULL END, "
            "requester = CASE "
            "WHEN friendships.status = 'accepted' OR excluded.status = 'accepted' THEN NULL "
            "WHEN friendships.status = 'pending' THEN friendships.requester "
            "ELSE excluded.requester END",
            (g, g),
        )
        self.conn.execute("DELETE FROM friendships WHERE guild_id != ?", (g,))

        # Definitionen und Referenzen vor dem Zusammenführen der Inventare umstellen.
        self._migrate_card_definitions("custom_cards", "card_inventory")
        self._migrate_card_definitions("server_cards", "server_inventory")

        # Inventare & Packs: Counts pro Schlüssel summieren.
        for table, key in (
            ("card_inventory", "user_id, card_id"),
            ("server_inventory", "user_id, card_id"),
            ("packs", "user_id, pack_type"),
        ):
            cols = key
            self.conn.execute(
                f"INSERT INTO {table} (guild_id, {cols}, count) "
                f"SELECT ?, {cols}, SUM(count) FROM {table} WHERE guild_id != ? GROUP BY {cols} "
                f"ON CONFLICT(guild_id, {cols}) DO UPDATE SET count = count + excluded.count",
                (g, g),
            )
            self.conn.execute(f"DELETE FROM {table} WHERE guild_id != ?", (g,))

        # Playtime (transiente Tages-Zähler) global zusammenführen.
        self.conn.execute(
            "INSERT INTO playtime (guild_id, user_id, game, accumulated, day, cards_today) "
            "SELECT ?, user_id, game, SUM(accumulated), MAX(day), MAX(cards_today) "
            "FROM playtime WHERE guild_id != ? GROUP BY user_id, game "
            "ON CONFLICT(guild_id, user_id, game) DO UPDATE SET "
            "accumulated = accumulated + excluded.accumulated, "
            "day = max(day, excluded.day), cards_today = max(cards_today, excluded.cards_today)",
            (g, g),
        )
        self.conn.execute("DELETE FROM playtime WHERE guild_id != ?", (g,))

        # Lieblingskarten gehören wie das Karteninventar dem User global.
        # Existiert bereits eine globale Auswahl, bleibt sie erhalten; andernfalls
        # gewinnt deterministisch die Auswahl der kleinsten bisherigen Guild-ID.
        self.conn.execute(
            "INSERT OR IGNORE INTO fav_game_cards (guild_id, user_id, game, card_id) "
            "SELECT ?, user_id, game, card_id FROM fav_game_cards WHERE guild_id != ? "
            "ORDER BY guild_id",
            (g, g),
        )
        self.conn.execute("DELETE FROM fav_game_cards WHERE guild_id != ?", (g,))

    def close(self) -> None:
        self.conn.close()

    # --- WebPanel-Sessions ----------------------------------------------------

    @staticmethod
    def _session_guilds_from_json(raw: dict) -> dict[int, str]:
        """JSON speichert Dict-Keys als Strings; intern nutzen wir Discord-IDs als int."""
        return {int(k): str(v) for k, v in raw.items()}

    def save_web_session(self, token: str, session: dict) -> None:
        """Speichert eine WebPanel-Session persistent in SQLite."""
        payload = dict(session)
        payload["guilds"] = {str(k): v for k, v in session.get("guilds", {}).items()}
        payload["member_guilds"] = {
            str(k): v for k, v in session.get("member_guilds", {}).items()
        }
        self.conn.execute(
            "INSERT INTO web_sessions (token, user_id, exp, data) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(token) DO UPDATE SET user_id = excluded.user_id, "
            "exp = excluded.exp, data = excluded.data",
            (
                token,
                int(session["user_id"]),
                float(session["exp"]),
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        self.conn.commit()

    def get_web_session(self, token: str) -> dict | None:
        """Lädt eine nicht abgelaufene WebPanel-Session oder None."""
        row = self.conn.execute(
            "SELECT data, exp FROM web_sessions WHERE token = ?", (token,)
        ).fetchone()
        if row is None:
            return None
        if float(row["exp"]) < time.time():
            self.delete_web_session(token)
            return None
        data = json.loads(row["data"])
        data["guilds"] = self._session_guilds_from_json(data.get("guilds", {}))
        data["member_guilds"] = self._session_guilds_from_json(
            data.get("member_guilds", {})
        )
        return data

    def delete_web_session(self, token: str) -> None:
        """Entfernt eine WebPanel-Session."""
        self.conn.execute("DELETE FROM web_sessions WHERE token = ?", (token,))
        self.conn.commit()

    def cleanup_web_sessions(self) -> int:
        """Löscht abgelaufene WebPanel-Sessions und gibt die Anzahl zurück."""
        cur = self.conn.execute("DELETE FROM web_sessions WHERE exp < ?", (time.time(),))
        self.conn.commit()
        return cur.rowcount

    # --- Achievements ---------------------------------------------------------

    def achievement_snapshot(self, guild_id: int, user_id: int) -> dict[str, int]:
        """Liefert die messbaren, überwiegend globalen Quest-Fortschritte eines Users."""
        level_row = self.get_user(guild_id, user_id)
        game_row = self.conn.execute(
            "SELECT COALESCE(SUM(games), 0) AS games, COALESCE(SUM(wins), 0) AS wins "
            "FROM game_stats WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        cards_row = self.conn.execute(
            "SELECT COALESCE(SUM(count), 0) AS total FROM card_inventory "
            "WHERE guild_id = ? AND user_id = ? AND count > 0",
            (GLOBAL_GID, user_id),
        ).fetchone()
        yami_row = self.conn.execute(
            "SELECT COALESCE(SUM(count), 0) AS total FROM server_inventory "
            "WHERE guild_id = ? AND user_id = ? AND count > 0",
            (GLOBAL_GID, user_id),
        ).fetchone()
        friend_row = self.conn.execute(
            "SELECT COUNT(*) AS total, COALESCE(MAX(xp), 0) AS best_xp FROM friendships "
            "WHERE guild_id = ? AND status = 'accepted' AND (user_a = ? OR user_b = ?)",
            (GLOBAL_GID, user_id, user_id),
        ).fetchone()
        marriage_row = self.conn.execute(
            "SELECT COUNT(*) AS total FROM marriages WHERE user_a = ? OR user_b = ?",
            (user_id, user_id),
        ).fetchone()
        _last_daily, streak = self.get_daily(guild_id, user_id)

        return {
            "level": int(level_row["level"]),
            "coins": max(0, int(level_row["coins"])),
            "games": int(game_row["games"]),
            "wins": int(game_row["wins"]),
            "cards": int(cards_row["total"]),
            "yami_cards": int(yami_row["total"]),
            "friends": int(friend_row["total"]),
            "friend_xp": int(friend_row["best_xp"]),
            "daily_streak": streak,
            "marriages": int(marriage_row["total"]),
        }

    def unlock_achievement(
        self, user_id: int, achievement_id: str, *, unlocked_at: float | None = None
    ) -> bool:
        """Schaltet idempotent frei; True bedeutet eine tatsächlich neue Freischaltung."""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO achievements (user_id, achievement_id, unlocked_at) "
            "VALUES (?, ?, ?)",
            (user_id, achievement_id, time.time() if unlocked_at is None else unlocked_at),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def get_unlocked_achievements(self, user_id: int) -> dict[str, float]:
        rows = self.conn.execute(
            "SELECT achievement_id, unlocked_at FROM achievements "
            "WHERE user_id = ? ORDER BY unlocked_at, achievement_id",
            (user_id,),
        ).fetchall()
        return {str(row["achievement_id"]): float(row["unlocked_at"]) for row in rows}

    def achievements_initialized(self, user_id: int) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM achievement_users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row is not None

    def mark_achievements_initialized(self, user_id: int) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO achievement_users (user_id, initialized_at) VALUES (?, ?)",
            (user_id, time.time()),
        )
        self.conn.commit()

    # --- Leveling -------------------------------------------------------------

    def get_user(self, guild_id: int, user_id: int) -> sqlite3.Row:
        """Gibt die Level-Zeile zurück; legt sie bei Bedarf mit Defaults an."""
        guild_id = GLOBAL_GID  # global: eine Level-/Coin-Zeile pro User
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
        guild_id = GLOBAL_GID
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
        guild_id = GLOBAL_GID
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

    def spend_coins(self, guild_id: int, user_id: int, amount: int) -> bool:
        """Bucht `amount` Coins atomar ab – aber nur, wenn das Guthaben reicht.

        Gibt True zurück, wenn abgebucht wurde, sonst False (zu wenig Coins).
        Verhindert Races (Doppelklick/parallele Interaktionen), bei denen ein
        separater Kontostand-Check und ein blindes ``coins = coins - x`` zu
        negativen Salden führen könnten.
        """
        guild_id = GLOBAL_GID
        self.get_user(guild_id, user_id)
        cur = self.conn.execute(
            "UPDATE levels SET coins = coins - ? "
            "WHERE guild_id = ? AND user_id = ? AND coins >= ?",
            (amount, guild_id, user_id, amount),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def leaderboard(self, guild_id: int, limit: int = 10) -> list[sqlite3.Row]:
        guild_id = GLOBAL_GID  # global: ein serverübergreifendes Leaderboard
        return self.conn.execute(
            "SELECT user_id, xp, level, coins FROM levels WHERE guild_id = ? "
            "ORDER BY xp DESC LIMIT ?",
            (guild_id, limit),
        ).fetchall()

    def leaderboard_members(
        self, user_ids: list[int], limit: int = 50
    ) -> list[sqlite3.Row]:
        """Leaderboard nur für die übergebenen User-IDs (z. B. Server-Mitglieder).

        Filtert direkt in SQL statt 1000 Zeilen zu laden und in Python zu filtern.
        Respektiert das SQLite-Parameterlimit (~999), indem in Blöcken abgefragt
        und anschließend zusammengeführt wird.
        """
        guild_id = GLOBAL_GID
        ids = list({int(u) for u in user_ids})
        if not ids:
            return []
        rows: list[sqlite3.Row] = []
        chunk_size = 900
        for i in range(0, len(ids), chunk_size):
            chunk = ids[i : i + chunk_size]
            placeholders = ",".join("?" * len(chunk))
            rows.extend(
                self.conn.execute(
                    "SELECT user_id, xp, level, coins FROM levels "
                    f"WHERE guild_id = ? AND user_id IN ({placeholders}) "
                    "ORDER BY xp DESC LIMIT ?",
                    (guild_id, *chunk, limit),
                ).fetchall()
            )
        rows.sort(key=lambda r: int(r["xp"]), reverse=True)
        return rows[:limit]

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

    def get_levelup_config(self, guild_id: int) -> dict:
        """Komplette Level-Up-Konfiguration: Channel, eigener Text, Ping-Flag."""
        row = self.conn.execute(
            "SELECT levelup_channel_id, levelup_message, levelup_ping "
            "FROM guild_settings WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()
        if row is None:
            return {"channel_id": None, "message": None, "ping": True}
        return {
            "channel_id": int(row["levelup_channel_id"]) if row["levelup_channel_id"] else None,
            "message": row["levelup_message"],
            "ping": bool(row["levelup_ping"]),
        }

    def set_levelup_message(self, guild_id: int, message: Optional[str]) -> None:
        self._ensure_settings(guild_id)
        self.conn.execute(
            "UPDATE guild_settings SET levelup_message = ? WHERE guild_id = ?",
            (message, guild_id),
        )
        self.conn.commit()

    def set_levelup_ping(self, guild_id: int, ping: bool) -> None:
        self._ensure_settings(guild_id)
        self.conn.execute(
            "UPDATE guild_settings SET levelup_ping = ? WHERE guild_id = ?",
            (1 if ping else 0, guild_id),
        )
        self.conn.commit()

    def set_levelup_config(
        self, guild_id: int, channel_id: Optional[int], message: Optional[str], ping: bool
    ) -> None:
        self._ensure_settings(guild_id)
        self.conn.execute(
            "UPDATE guild_settings SET levelup_channel_id = ?, levelup_message = ?, "
            "levelup_ping = ? WHERE guild_id = ?",
            (channel_id, message, 1 if ping else 0, guild_id),
        )
        self.conn.commit()

    # --- Bot-Serverprofil (Nickname + Avatar pro Server) ----------------------

    def get_bot_profile(self, guild_id: int) -> dict:
        row = self.conn.execute(
            "SELECT bot_nick, bot_avatar FROM guild_settings WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()
        if row is None:
            return {"nick": None, "avatar": None}
        return {"nick": row["bot_nick"], "avatar": row["bot_avatar"]}

    def set_bot_nick(self, guild_id: int, nick: Optional[str]) -> None:
        self._ensure_settings(guild_id)
        self.conn.execute(
            "UPDATE guild_settings SET bot_nick = ? WHERE guild_id = ?", (nick, guild_id)
        )
        self.conn.commit()

    def set_bot_avatar(self, guild_id: int, url: Optional[str]) -> None:
        self._ensure_settings(guild_id)
        self.conn.execute(
            "UPDATE guild_settings SET bot_avatar = ? WHERE guild_id = ?", (url, guild_id)
        )
        self.conn.commit()

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

    # --- Per Dashboard gesendete Nachrichten ----------------------------------

    def add_announcement(
        self, guild_id: int, channel_id: int, message_id: int, as_embed: bool,
        title: Optional[str], content: Optional[str], color: Optional[str],
        image_url: Optional[str], ping_roles: Optional[str], created_at: int,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO announcements (guild_id, channel_id, message_id, as_embed, title, "
            "content, color, image_url, ping_roles, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (guild_id, channel_id, message_id, 1 if as_embed else 0, title, content, color,
             image_url, ping_roles, created_at),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_announcements(self, guild_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM announcements WHERE guild_id = ? ORDER BY created_at DESC, id DESC",
            (guild_id,),
        ).fetchall()

    def get_announcement(self, guild_id: int, ann_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM announcements WHERE guild_id = ? AND id = ?",
            (guild_id, ann_id),
        ).fetchone()

    def update_announcement(
        self, guild_id: int, ann_id: int, as_embed: bool, title: Optional[str],
        content: Optional[str], color: Optional[str], image_url: Optional[str],
        ping_roles: Optional[str],
    ) -> None:
        self.conn.execute(
            "UPDATE announcements SET as_embed = ?, title = ?, content = ?, color = ?, "
            "image_url = ?, ping_roles = ? WHERE guild_id = ? AND id = ?",
            (1 if as_embed else 0, title, content, color, image_url, ping_roles, guild_id, ann_id),
        )
        self.conn.commit()

    def delete_announcement(self, guild_id: int, ann_id: int) -> None:
        self.conn.execute(
            "DELETE FROM announcements WHERE guild_id = ? AND id = ?", (guild_id, ann_id)
        )
        self.conn.commit()

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

    # --- Willkommensnachrichten -----------------------------------------------

    def get_welcome(self, guild_id: int) -> dict:
        row = self.conn.execute(
            "SELECT welcome_enabled, welcome_channel_id, welcome_message, welcome_image "
            "FROM guild_settings WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()
        if row is None:
            return {"enabled": False, "channel_id": None, "message": None, "image": None}
        return {
            "enabled": bool(row["welcome_enabled"]),
            "channel_id": int(row["welcome_channel_id"]) if row["welcome_channel_id"] else None,
            "message": row["welcome_message"],
            "image": row["welcome_image"],
        }

    def set_welcome_image(self, guild_id: int, url: Optional[str]) -> None:
        self._ensure_settings(guild_id)
        self.conn.execute(
            "UPDATE guild_settings SET welcome_image = ? WHERE guild_id = ?", (url, guild_id)
        )
        self.conn.commit()

    def set_welcome(
        self, guild_id: int, enabled: bool, channel_id: Optional[int], message: Optional[str]
    ) -> None:
        self._ensure_settings(guild_id)
        self.conn.execute(
            "UPDATE guild_settings SET welcome_enabled = ?, welcome_channel_id = ?, "
            "welcome_message = ? WHERE guild_id = ?",
            (1 if enabled else 0, channel_id, message, guild_id),
        )
        self.conn.commit()

    # --- Boost-Nachrichten ----------------------------------------------------

    def get_boost(self, guild_id: int) -> dict:
        """Boost-Konfiguration: aktiviert, Channel, Text, Erwähnung, Bild."""
        row = self.conn.execute(
            "SELECT boost_enabled, boost_channel_id, boost_message, boost_mention, boost_image "
            "FROM guild_settings WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()
        if row is None:
            return {"enabled": False, "channel_id": None, "message": None, "mention": True, "image": None}
        return {
            "enabled": bool(row["boost_enabled"]),
            "channel_id": int(row["boost_channel_id"]) if row["boost_channel_id"] else None,
            "message": row["boost_message"],
            "mention": bool(row["boost_mention"]),
            "image": row["boost_image"],
        }

    def set_boost(
        self,
        guild_id: int,
        enabled: bool,
        channel_id: Optional[int],
        message: Optional[str],
        mention: bool,
    ) -> None:
        self._ensure_settings(guild_id)
        self.conn.execute(
            "UPDATE guild_settings SET boost_enabled = ?, boost_channel_id = ?, "
            "boost_message = ?, boost_mention = ? WHERE guild_id = ?",
            (1 if enabled else 0, channel_id, message, 1 if mention else 0, guild_id),
        )
        self.conn.commit()

    def set_boost_image(self, guild_id: int, url: Optional[str]) -> None:
        self._ensure_settings(guild_id)
        self.conn.execute(
            "UPDATE guild_settings SET boost_image = ? WHERE guild_id = ?", (url, guild_id)
        )
        self.conn.commit()

    # --- Twitch Live ----------------------------------------------------------

    def get_twitch_config(self, guild_id: int) -> dict:
        """Gibt die Twitch-Live-Konfiguration eines Discord-Servers zurück."""
        row = self.conn.execute(
            "SELECT twitch_enabled, twitch_login, twitch_channel_id, twitch_message, "
            "twitch_mention_role_id, twitch_last_stream_id FROM guild_settings WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()
        if row is None:
            return {"enabled": False, "login": None, "channel_id": None, "message": None,
                    "mention_role_id": None, "last_stream_id": None}
        return {
            "enabled": bool(row["twitch_enabled"]), "login": row["twitch_login"],
            "channel_id": int(row["twitch_channel_id"]) if row["twitch_channel_id"] else None,
            "message": row["twitch_message"],
            "mention_role_id": int(row["twitch_mention_role_id"]) if row["twitch_mention_role_id"] else None,
            "last_stream_id": row["twitch_last_stream_id"],
        }

    def set_twitch_config(
        self, guild_id: int, enabled: bool, login: Optional[str], channel_id: Optional[int],
        message: Optional[str], mention_role_id: Optional[int],
    ) -> None:
        self._ensure_settings(guild_id)
        self.conn.execute(
            "UPDATE guild_settings SET twitch_enabled = ?, twitch_login = ?, twitch_channel_id = ?, "
            "twitch_message = ?, twitch_mention_role_id = ?, twitch_last_stream_id = NULL WHERE guild_id = ?",
            (1 if enabled else 0, login, channel_id, message, mention_role_id, guild_id),
        )
        self.conn.commit()

    def list_twitch_configs(self) -> list[dict]:
        """Nur tatsächlich aktivierte, vollständige Einträge für den Poller."""
        rows = self.conn.execute(
            "SELECT guild_id, twitch_login, twitch_channel_id, twitch_message, twitch_mention_role_id, "
            "twitch_last_stream_id FROM guild_settings "
            "WHERE twitch_enabled = 1 AND twitch_login IS NOT NULL AND twitch_channel_id IS NOT NULL"
        ).fetchall()
        return [{"guild_id": int(r["guild_id"]), "login": r["twitch_login"],
                 "channel_id": int(r["twitch_channel_id"]), "message": r["twitch_message"],
                 "mention_role_id": r["twitch_mention_role_id"], "last_stream_id": r["twitch_last_stream_id"]}
                for r in rows]

    def set_twitch_last_stream_id(self, guild_id: int, stream_id: Optional[str]) -> None:
        self._ensure_settings(guild_id)
        self.conn.execute("UPDATE guild_settings SET twitch_last_stream_id = ? WHERE guild_id = ?", (stream_id, guild_id))
        self.conn.commit()

    # --- Auto-Rollen ----------------------------------------------------------

    def get_autoroles(self, guild_id: int) -> dict:
        """Gibt die Auto-Rollen-Konfiguration zurück: aktiviert + Liste der Rollen-IDs."""
        row = self.conn.execute(
            "SELECT autoroles_enabled, autoroles_role_ids FROM guild_settings WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()
        if row is None:
            return {"enabled": False, "role_ids": []}
        raw = row["autoroles_role_ids"] or ""
        role_ids = [int(x) for x in raw.split(",") if x.strip().isdigit()]
        return {
            "enabled": bool(row["autoroles_enabled"]),
            "role_ids": role_ids,
        }

    def set_autoroles(self, guild_id: int, enabled: bool, role_ids: list[int]) -> None:
        """Speichert die Auto-Rollen-Konfiguration. Duplikate werden entfernt."""
        self._ensure_settings(guild_id)
        # Duplikate entfernen, Reihenfolge beibehalten.
        seen: set[int] = set()
        deduped = []
        for rid in role_ids:
            if rid not in seen:
                seen.add(rid)
                deduped.append(rid)
        csv = ",".join(str(r) for r in deduped)
        self.conn.execute(
            "UPDATE guild_settings SET autoroles_enabled = ?, autoroles_role_ids = ? "
            "WHERE guild_id = ?",
            (1 if enabled else 0, csv or None, guild_id),
        )
        self.conn.commit()

    # --- AutoMod --------------------------------------------------------------

    @staticmethod
    def _dedupe_ints(values: list[int]) -> list[int]:
        seen: set[int] = set()
        deduped: list[int] = []
        for value in values:
            value = int(value)
            if value not in seen:
                seen.add(value)
                deduped.append(value)
        return deduped

    @staticmethod
    def _parse_id_csv(raw: Optional[str]) -> list[int]:
        return [int(x) for x in (raw or "").split(",") if x.strip().isdigit()]

    AUTOMOD_DEFAULTS = {
        "new_member_join_minutes": 10,
        "new_member_account_hours": 24,
        "repeat_threshold": 3,
        "repeat_window_seconds": 20,
        "burst_threshold": 5,
        "burst_window_seconds": 10,
    }

    def get_automod_config(self, guild_id: int) -> dict:
        """Gibt die AutoMod-Konfiguration zurück."""
        row = self.conn.execute(
            "SELECT automod_enabled, automod_delete_mass_mentions, automod_exempt_role_ids, "
            "automod_honeypot_channel_ids, automod_honeypot_ban, "
            "automod_honeypot_delete_seconds "
            "FROM guild_settings WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()
        if row is None:
            return {
                "enabled": False,
                "delete_mass_mentions": True,
                "exempt_role_ids": [],
                "honeypot_channel_ids": [],
                "honeypot_ban": True,
                "honeypot_delete_seconds": 604800,
                **self.AUTOMOD_DEFAULTS,
            }
        return {
            "enabled": bool(row["automod_enabled"]),
            "delete_mass_mentions": bool(row["automod_delete_mass_mentions"]),
            "exempt_role_ids": self._parse_id_csv(row["automod_exempt_role_ids"]),
            "honeypot_channel_ids": self._parse_id_csv(row["automod_honeypot_channel_ids"]),
            "honeypot_ban": bool(row["automod_honeypot_ban"]),
            "honeypot_delete_seconds": min(604800, max(0, int(row["automod_honeypot_delete_seconds"] or 0))),
            **self.AUTOMOD_DEFAULTS,
        }

    def set_automod_config(
        self,
        guild_id: int,
        *,
        enabled: bool,
        delete_mass_mentions: bool,
        exempt_role_ids: list[int],
        honeypot_channel_ids: list[int] | None = None,
        honeypot_ban: bool | None = None,
        honeypot_delete_seconds: int | None = None,
    ) -> None:
        """Speichert AutoMod-Einstellungen und dedupliziert Rollen/Channels."""
        self._ensure_settings(guild_id)
        current = self.get_automod_config(guild_id)
        roles = self._dedupe_ints(exempt_role_ids)
        role_csv = ",".join(str(role_id) for role_id in roles)
        channels = self._dedupe_ints(
            list(current["honeypot_channel_ids"] if honeypot_channel_ids is None else honeypot_channel_ids)
        )
        channel_csv = ",".join(str(channel_id) for channel_id in channels)
        if honeypot_ban is None:
            honeypot_ban = bool(current["honeypot_ban"])
        if honeypot_delete_seconds is None:
            honeypot_delete_seconds = int(current["honeypot_delete_seconds"])
        delete_seconds = min(604800, max(0, int(honeypot_delete_seconds)))
        self.conn.execute(
            "UPDATE guild_settings SET automod_enabled = ?, "
            "automod_delete_mass_mentions = ?, automod_exempt_role_ids = ?, "
            "automod_honeypot_channel_ids = ?, automod_honeypot_ban = ?, "
            "automod_honeypot_delete_seconds = ? WHERE guild_id = ?",
            (
                1 if enabled else 0,
                1 if delete_mass_mentions else 0,
                role_csv or None,
                channel_csv or None,
                1 if honeypot_ban else 0,
                delete_seconds,
                guild_id,
            ),
        )
        self.conn.commit()

    def set_automod_enabled(self, guild_id: int, enabled: bool) -> None:
        config = self.get_automod_config(guild_id)
        self.set_automod_config(
            guild_id,
            enabled=enabled,
            delete_mass_mentions=bool(config["delete_mass_mentions"]),
            exempt_role_ids=list(config["exempt_role_ids"]),
        )

    def set_automod_mass_mentions(self, guild_id: int, enabled: bool) -> None:
        config = self.get_automod_config(guild_id)
        self.set_automod_config(
            guild_id,
            enabled=bool(config["enabled"]),
            delete_mass_mentions=enabled,
            exempt_role_ids=list(config["exempt_role_ids"]),
        )


    def set_automod_honeypot(
        self,
        guild_id: int,
        *,
        channel_ids: list[int],
        ban: bool,
        delete_seconds: int,
    ) -> None:
        config = self.get_automod_config(guild_id)
        self.set_automod_config(
            guild_id,
            enabled=bool(config["enabled"]),
            delete_mass_mentions=bool(config["delete_mass_mentions"]),
            exempt_role_ids=list(config["exempt_role_ids"]),
            honeypot_channel_ids=channel_ids,
            honeypot_ban=ban,
            honeypot_delete_seconds=delete_seconds,
        )

    def add_automod_honeypot_channel(self, guild_id: int, channel_id: int) -> list[int]:
        config = self.get_automod_config(guild_id)
        channels = list(config["honeypot_channel_ids"])
        channels.append(int(channel_id))
        self.set_automod_honeypot(
            guild_id,
            channel_ids=channels,
            ban=bool(config["honeypot_ban"]),
            delete_seconds=int(config["honeypot_delete_seconds"]),
        )
        return self.get_automod_config(guild_id)["honeypot_channel_ids"]

    def remove_automod_honeypot_channel(self, guild_id: int, channel_id: int) -> list[int]:
        config = self.get_automod_config(guild_id)
        channels = [cid for cid in config["honeypot_channel_ids"] if cid != int(channel_id)]
        self.set_automod_honeypot(
            guild_id,
            channel_ids=channels,
            ban=bool(config["honeypot_ban"]),
            delete_seconds=int(config["honeypot_delete_seconds"]),
        )
        return self.get_automod_config(guild_id)["honeypot_channel_ids"]

    def add_automod_exempt_role(self, guild_id: int, role_id: int) -> list[int]:
        config = self.get_automod_config(guild_id)
        roles = list(config["exempt_role_ids"])
        roles.append(int(role_id))
        self.set_automod_config(
            guild_id,
            enabled=bool(config["enabled"]),
            delete_mass_mentions=bool(config["delete_mass_mentions"]),
            exempt_role_ids=roles,
        )
        return self.get_automod_config(guild_id)["exempt_role_ids"]

    def remove_automod_exempt_role(self, guild_id: int, role_id: int) -> list[int]:
        config = self.get_automod_config(guild_id)
        roles = [rid for rid in config["exempt_role_ids"] if rid != int(role_id)]
        self.set_automod_config(
            guild_id,
            enabled=bool(config["enabled"]),
            delete_mass_mentions=bool(config["delete_mass_mentions"]),
            exempt_role_ids=roles,
        )
        return self.get_automod_config(guild_id)["exempt_role_ids"]

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
        guild_id = GLOBAL_GID
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

    def set_fav_card(self, guild_id: int, user_id: int, card_id: Optional[str]) -> None:
        self.conn.execute(
            "INSERT INTO profiles (guild_id, user_id, fav_card) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET fav_card = excluded.fav_card",
            (guild_id, user_id, card_id),
        )
        self.conn.commit()

    def get_fav_card(self, guild_id: int, user_id: int) -> Optional[str]:
        row = self.conn.execute(
            "SELECT fav_card FROM profiles WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        return row["fav_card"] if row and row["fav_card"] else None

    def set_fav_game_card(
        self, guild_id: int, user_id: int, game: str, card_id: Optional[str]
    ) -> None:
        """Setzt die globale Lieblingskarte für ein Spiel. None entfernt sie."""
        guild_id = GLOBAL_GID
        if card_id is None:
            self.conn.execute(
                "DELETE FROM fav_game_cards WHERE guild_id = ? AND user_id = ? AND game = ?",
                (guild_id, user_id, game),
            )
        else:
            self.conn.execute(
                "INSERT INTO fav_game_cards (guild_id, user_id, game, card_id) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(guild_id, user_id, game) DO UPDATE SET card_id = excluded.card_id",
                (guild_id, user_id, game, card_id),
            )
        self.conn.commit()

    def get_fav_game_cards(self, guild_id: int, user_id: int) -> dict[str, str]:
        """Alle globalen Lieblingskarten als {spiel: card_id}."""
        guild_id = GLOBAL_GID
        rows = self.conn.execute(
            "SELECT game, card_id FROM fav_game_cards WHERE guild_id = ? AND user_id = ? "
            "ORDER BY game COLLATE NOCASE",
            (guild_id, user_id),
        ).fetchall()
        return {r["game"]: r["card_id"] for r in rows}

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
        guild_id = GLOBAL_GID  # global: Daily zählt serverübergreifend (sonst mehrfach abgreifbar)
        row = self.conn.execute(
            "SELECT last_claim, streak FROM daily WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        if row is None:
            return 0.0, 0
        return float(row["last_claim"]), int(row["streak"])

    def set_daily(self, guild_id: int, user_id: int, last_claim: float, streak: int) -> None:
        guild_id = GLOBAL_GID
        self.conn.execute(
            "INSERT INTO daily (guild_id, user_id, last_claim, streak) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
            "last_claim = excluded.last_claim, streak = excluded.streak",
            (guild_id, user_id, last_claim, streak),
        )
        self.conn.commit()

    # --- Effekte (Shop-Boosts) ------------------------------------------------

    def add_charges(self, guild_id: int, user_id: int, effect: str, amount: int) -> None:
        guild_id = GLOBAL_GID  # global: Shop-Effekte gehören dem User serverübergreifend
        self.conn.execute(
            "INSERT INTO effects (guild_id, user_id, effect, charges) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id, user_id, effect) DO UPDATE SET charges = charges + ?",
            (guild_id, user_id, effect, amount, amount),
        )
        self.conn.commit()

    def get_charges(self, guild_id: int, user_id: int, effect: str) -> int:
        guild_id = GLOBAL_GID
        row = self.conn.execute(
            "SELECT charges FROM effects WHERE guild_id = ? AND user_id = ? AND effect = ?",
            (guild_id, user_id, effect),
        ).fetchone()
        return int(row["charges"]) if row else 0

    def consume_charge(self, guild_id: int, user_id: int, effect: str) -> bool:
        """Verbraucht eine Ladung; gibt True zurück, wenn eine vorhanden war."""
        guild_id = GLOBAL_GID
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
        guild_id = GLOBAL_GID
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
        guild_id = GLOBAL_GID
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
        guild_id = GLOBAL_GID
        lo, hi = self._pair(a, b)
        return self.conn.execute(
            "SELECT * FROM friendships WHERE guild_id = ? AND user_a = ? AND user_b = ?",
            (guild_id, lo, hi),
        ).fetchone()

    def _ensure_pair(self, guild_id: int, a: int, b: int) -> None:
        guild_id = GLOBAL_GID
        lo, hi = self._pair(a, b)
        self.conn.execute(
            "INSERT OR IGNORE INTO friendships (guild_id, user_a, user_b) VALUES (?, ?, ?)",
            (guild_id, lo, hi),
        )

    def _set_status(self, guild_id: int, a: int, b: int, status: str | None, requester: int | None) -> None:
        guild_id = GLOBAL_GID
        lo, hi = self._pair(a, b)
        self.conn.execute(
            "UPDATE friendships SET status = ?, requester = ? "
            "WHERE guild_id = ? AND user_a = ? AND user_b = ?",
            (status, requester, guild_id, lo, hi),
        )
        self.conn.commit()

    def add_friend_xp(self, guild_id: int, a: int, b: int, amount: int) -> int:
        guild_id = GLOBAL_GID
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
        guild_id = GLOBAL_GID
        row = self.get_friend_row(guild_id, a, b)
        return int(row["xp"]) if row else 0

    def send_friend_request(self, guild_id: int, requester: int, target: int) -> str:
        """Verarbeitet eine Freundschaftsanfrage. Rückgabe-Code für die UI."""
        guild_id = GLOBAL_GID
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
        guild_id = GLOBAL_GID
        row = self.get_friend_row(guild_id, user, other)
        if not row or row["status"] != "pending" or row["requester"] == user:
            return False
        self._set_status(guild_id, user, other, "accepted", None)
        return True

    def remove_friend(self, guild_id: int, user: int, other: int) -> bool:
        """Entfernt Freundschaft/offene Anfrage (XP-Historie bleibt erhalten)."""
        guild_id = GLOBAL_GID
        row = self.get_friend_row(guild_id, user, other)
        if not row or row["status"] is None:
            return False
        self._set_status(guild_id, user, other, None, None)
        return True

    def list_friends(self, guild_id: int, user: int) -> list[tuple[int, int]]:
        """Akzeptierte Freunde: Liste von (andere_user_id, xp), nach XP sortiert."""
        guild_id = GLOBAL_GID
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
        guild_id = GLOBAL_GID
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
        guild_id = GLOBAL_GID  # global: ein Karten-Inventar pro User
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
        guild_id = GLOBAL_GID
        rows = self.conn.execute(
            "SELECT card_id, count FROM card_inventory WHERE guild_id = ? AND user_id = ? AND count > 0",
            (guild_id, user_id),
        ).fetchall()
        return {r["card_id"]: int(r["count"]) for r in rows}

    def remove_card(self, guild_id: int, user_id: int, card_id: str, amount: int | None = None) -> int:
        """Entfernt Karten aus einem Inventar. amount=None entfernt alle Exemplare.
        Gibt den verbleibenden Bestand zurück."""
        guild_id = GLOBAL_GID
        have = self._card_count(guild_id, user_id, card_id)
        if have <= 0:
            return 0
        if amount is None or amount >= have:
            self.conn.execute(
                "DELETE FROM card_inventory WHERE guild_id = ? AND user_id = ? AND card_id = ?",
                (guild_id, user_id, card_id),
            )
            self.conn.commit()
            return 0
        self.conn.execute(
            "UPDATE card_inventory SET count = count - ? WHERE guild_id = ? AND user_id = ? AND card_id = ?",
            (amount, guild_id, user_id, card_id),
        )
        self.conn.commit()
        return have - amount

    def list_card_collectors(self, guild_id: int) -> list[tuple[int, int]]:
        """(user_id, Gesamtzahl Karten) aller Sammler, nach Anzahl sortiert."""
        guild_id = GLOBAL_GID
        rows = self.conn.execute(
            "SELECT user_id, SUM(count) AS s FROM card_inventory WHERE guild_id = ? AND count > 0 "
            "GROUP BY user_id ORDER BY s DESC",
            (guild_id,),
        ).fetchall()
        return [(int(r["user_id"]), int(r["s"])) for r in rows]

    def _card_count(self, guild_id: int, user_id: int, card_id: str) -> int:
        guild_id = GLOBAL_GID
        row = self.conn.execute(
            "SELECT count FROM card_inventory WHERE guild_id = ? AND user_id = ? AND card_id = ?",
            (guild_id, user_id, card_id),
        ).fetchone()
        return int(row["count"]) if row else 0

    def trade_cards(
        self, guild_id: int, user_a: int, card_a: str, user_b: int, card_b: str
    ) -> bool:
        """Tauscht je eine Karte zwischen zwei Usern atomar. False, wenn jemand die Karte nicht (mehr) hat."""
        guild_id = GLOBAL_GID
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

    def trade_with_coins(
        self, guild_id: int, user_a: int, card_a: str | None,
        user_b: int, card_b: str | None, coins_a_to_b: int = 0,
    ) -> bool:
        """Flexibler Handel: A gibt optional card_a, B gibt optional card_b, und A zahlt
        coins_a_to_b Coins an B (0 = keine). Atomar. False, wenn jemandem Karte/Coins fehlen."""
        guild_id = GLOBAL_GID
        if card_a and self._card_count(guild_id, user_a, card_a) < 1:
            return False
        if card_b and self._card_count(guild_id, user_b, card_b) < 1:
            return False
        if coins_a_to_b > 0:
            row = self.conn.execute(
                "SELECT coins FROM levels WHERE guild_id = ? AND user_id = ?", (guild_id, user_a)
            ).fetchone()
            if row is None or int(row["coins"]) < coins_a_to_b:
                return False

        def _dec(uid: int, cid: str) -> None:
            self.conn.execute(
                "UPDATE card_inventory SET count = count - 1 "
                "WHERE guild_id = ? AND user_id = ? AND card_id = ?", (guild_id, uid, cid),
            )

        def _inc(uid: int, cid: str) -> None:
            self.conn.execute(
                "INSERT INTO card_inventory (guild_id, user_id, card_id, count) VALUES (?, ?, ?, 1) "
                "ON CONFLICT(guild_id, user_id, card_id) DO UPDATE SET count = count + 1",
                (guild_id, uid, cid),
            )

        if card_a:
            _dec(user_a, card_a)
            _inc(user_b, card_a)
        if card_b:
            _dec(user_b, card_b)
            _inc(user_a, card_b)
        if coins_a_to_b > 0:
            self.conn.execute("INSERT OR IGNORE INTO levels (guild_id, user_id) VALUES (?, ?)", (guild_id, user_a))
            self.conn.execute("INSERT OR IGNORE INTO levels (guild_id, user_id) VALUES (?, ?)", (guild_id, user_b))
            self.conn.execute(
                "UPDATE levels SET coins = coins - ? WHERE guild_id = ? AND user_id = ?",
                (coins_a_to_b, guild_id, user_a),
            )
            self.conn.execute(
                "UPDATE levels SET coins = coins + ? WHERE guild_id = ? AND user_id = ?",
                (coins_a_to_b, guild_id, user_b),
            )
        self.conn.commit()
        return True

    def add_custom_card(
        self, guild_id: int, card_id: str, name: str, rarity: str, image_url: str | None, game: str
    ) -> None:
        guild_id = GLOBAL_GID  # global: ein gemeinsamer Karten-Katalog
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
        guild_id = GLOBAL_GID
        cur = self.conn.execute(
            "DELETE FROM custom_cards WHERE guild_id = ? AND card_id = ?", (guild_id, card_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def rename_custom_card(self, guild_id: int, card_id: str, name: str) -> bool:
        """Ändert nur den Anzeigenamen — card_id bleibt stabil (Inventare bleiben gültig)."""
        guild_id = GLOBAL_GID
        cur = self.conn.execute(
            "UPDATE custom_cards SET name = ? WHERE guild_id = ? AND card_id = ?",
            (name, guild_id, card_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def list_custom_cards(self, guild_id: int) -> list[tuple[str, str, str, str | None, str | None]]:
        guild_id = GLOBAL_GID
        rows = self.conn.execute(
            "SELECT card_id, name, rarity, image_url, game FROM custom_cards WHERE guild_id = ?",
            (guild_id,),
        ).fetchall()
        return [(r["card_id"], r["name"], r["rarity"], r["image_url"], r["game"]) for r in rows]

    def list_custom_cards_for_game(self, guild_id: int, game: str) -> list[tuple[str, str, str, str | None]]:
        guild_id = GLOBAL_GID
        rows = self.conn.execute(
            "SELECT card_id, name, rarity, image_url FROM custom_cards WHERE guild_id = ? AND game = ?",
            (guild_id, game.lower()),
        ).fetchall()
        return [(r["card_id"], r["name"], r["rarity"], r["image_url"]) for r in rows]

    # --- Server-Sammelkarten (Booster) ----------------------------------------

    def add_server_card(self, guild_id: int, card_id: str, name: str, rarity: str, image_url: str | None) -> None:
        guild_id = GLOBAL_GID  # global: gemeinsamer Yami-Karten-Katalog
        self.conn.execute(
            "INSERT INTO server_cards (guild_id, card_id, name, rarity, image_url) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(guild_id, card_id) DO UPDATE SET "
            "name = excluded.name, rarity = excluded.rarity, image_url = excluded.image_url",
            (guild_id, card_id, name, rarity, image_url),
        )
        self.conn.commit()

    def remove_server_card(self, guild_id: int, card_id: str) -> bool:
        guild_id = GLOBAL_GID
        cur = self.conn.execute(
            "DELETE FROM server_cards WHERE guild_id = ? AND card_id = ?", (guild_id, card_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def list_server_cards(self, guild_id: int) -> list[tuple[str, str, str, str | None]]:
        guild_id = GLOBAL_GID
        rows = self.conn.execute(
            "SELECT card_id, name, rarity, image_url FROM server_cards WHERE guild_id = ?",
            (guild_id,),
        ).fetchall()
        return [(r["card_id"], r["name"], r["rarity"], r["image_url"]) for r in rows]

    def add_server_card_owned(self, guild_id: int, user_id: int, card_id: str, amount: int = 1) -> None:
        guild_id = GLOBAL_GID
        self.conn.execute(
            "INSERT INTO server_inventory (guild_id, user_id, card_id, count) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id, user_id, card_id) DO UPDATE SET count = count + ?",
            (guild_id, user_id, card_id, amount, amount),
        )
        self.conn.commit()

    def get_server_collection(self, guild_id: int, user_id: int) -> dict[str, int]:
        guild_id = GLOBAL_GID
        rows = self.conn.execute(
            "SELECT card_id, count FROM server_inventory WHERE guild_id = ? AND user_id = ? AND count > 0",
            (guild_id, user_id),
        ).fetchall()
        return {r["card_id"]: int(r["count"]) for r in rows}

    def remove_server_card_owned(self, guild_id: int, user_id: int, card_id: str, amount: int | None = None) -> int:
        """Entfernt Yami-Karten aus einem Inventar. amount=None entfernt alle. Gibt Rest zurück."""
        guild_id = GLOBAL_GID
        row = self.conn.execute(
            "SELECT count FROM server_inventory WHERE guild_id = ? AND user_id = ? AND card_id = ?",
            (guild_id, user_id, card_id),
        ).fetchone()
        have = int(row["count"]) if row else 0
        if have <= 0:
            return 0
        if amount is None or amount >= have:
            self.conn.execute(
                "DELETE FROM server_inventory WHERE guild_id = ? AND user_id = ? AND card_id = ?",
                (guild_id, user_id, card_id),
            )
            self.conn.commit()
            return 0
        self.conn.execute(
            "UPDATE server_inventory SET count = count - ? WHERE guild_id = ? AND user_id = ? AND card_id = ?",
            (amount, guild_id, user_id, card_id),
        )
        self.conn.commit()
        return have - amount

    def list_server_collectors(self, guild_id: int) -> list[tuple[int, int]]:
        """(user_id, Gesamtzahl Yami-Karten) aller Sammler, nach Anzahl sortiert."""
        guild_id = GLOBAL_GID
        rows = self.conn.execute(
            "SELECT user_id, SUM(count) AS s FROM server_inventory WHERE guild_id = ? AND count > 0 "
            "GROUP BY user_id ORDER BY s DESC",
            (guild_id,),
        ).fetchall()
        return [(int(r["user_id"]), int(r["s"])) for r in rows]

    # --- Arkansplitter / Spielkarten-Booster ---------------------------------

    def get_card_shards(self, guild_id: int, user_id: int) -> int:
        """Globales Arkansplitter-Guthaben eines Users."""
        guild_id = GLOBAL_GID
        row = self.conn.execute(
            "SELECT balance FROM card_shards WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        return int(row["balance"]) if row else 0

    def dismantle_card_duplicate(
        self, guild_id: int, user_id: int, card_id: str, reward: int,
    ) -> tuple[bool, int, int]:
        """Zerlegt genau ein Duplikat atomar und schreibt Arkansplitter gut.

        Das letzte Exemplar bleibt stets im Album. Rückgabe:
        ``(erfolgreich, neuer_splitterstand, verbleibende_karten)``.
        """
        guild_id = GLOBAL_GID
        if reward <= 0:
            return False, self.get_card_shards(guild_id, user_id), self._card_count(guild_id, user_id, card_id)
        try:
            cur = self.conn.execute(
                "UPDATE card_inventory SET count = count - 1 "
                "WHERE guild_id = ? AND user_id = ? AND card_id = ? AND count > 1",
                (guild_id, user_id, card_id),
            )
            if cur.rowcount != 1:
                self.conn.rollback()
                return False, self.get_card_shards(guild_id, user_id), self._card_count(guild_id, user_id, card_id)
            self.conn.execute(
                "INSERT INTO card_shards (guild_id, user_id, balance) VALUES (?, ?, ?) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET balance = balance + excluded.balance",
                (guild_id, user_id, reward),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return True, self.get_card_shards(guild_id, user_id), self._card_count(guild_id, user_id, card_id)

    def exchange_card_shards_for_pack(
        self, guild_id: int, user_id: int, pack_type: str, cost: int,
    ) -> tuple[bool, int, int]:
        """Tauscht Arkansplitter atomar gegen genau einen Booster."""
        guild_id = GLOBAL_GID
        if cost <= 0 or not pack_type:
            return False, self.get_card_shards(guild_id, user_id), self.get_pack_count(guild_id, user_id, pack_type)
        try:
            cur = self.conn.execute(
                "UPDATE card_shards SET balance = balance - ? "
                "WHERE guild_id = ? AND user_id = ? AND balance >= ?",
                (cost, guild_id, user_id, cost),
            )
            if cur.rowcount != 1:
                self.conn.rollback()
                return False, self.get_card_shards(guild_id, user_id), self.get_pack_count(guild_id, user_id, pack_type)
            self.conn.execute(
                "INSERT INTO packs (guild_id, user_id, pack_type, count) VALUES (?, ?, ?, 1) "
                "ON CONFLICT(guild_id, user_id, pack_type) DO UPDATE SET count = count + 1",
                (guild_id, user_id, pack_type),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return True, self.get_card_shards(guild_id, user_id), self.get_pack_count(guild_id, user_id, pack_type)

    # --- Booster-Packs --------------------------------------------------------

    def add_packs(self, guild_id: int, user_id: int, pack_type: str, amount: int) -> int:
        guild_id = GLOBAL_GID  # global: Packs gehören dem User serverübergreifend
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
        guild_id = GLOBAL_GID
        row = self.conn.execute(
            "SELECT count FROM packs WHERE guild_id = ? AND user_id = ? AND pack_type = ?",
            (guild_id, user_id, pack_type),
        ).fetchone()
        return int(row["count"]) if row else 0

    def list_packs(self, guild_id: int, user_id: int) -> dict[str, int]:
        guild_id = GLOBAL_GID
        rows = self.conn.execute(
            "SELECT pack_type, count FROM packs WHERE guild_id = ? AND user_id = ? AND count > 0",
            (guild_id, user_id),
        ).fetchall()
        return {r["pack_type"]: int(r["count"]) for r in rows}

    def consume_pack(self, guild_id: int, user_id: int, pack_type: str) -> bool:
        guild_id = GLOBAL_GID
        if self.get_pack_count(guild_id, user_id, pack_type) <= 0:
            return False
        self.conn.execute(
            "UPDATE packs SET count = count - 1 WHERE guild_id = ? AND user_id = ? AND pack_type = ?",
            (guild_id, user_id, pack_type),
        )
        self.conn.commit()
        return True

    # --- Belohnungs-Spiele ----------------------------------------------------

    def add_reward_game(
        self, guild_id: int, game: str, interval_min: int = 30, daily_cap: int = 12
    ) -> None:
        """Legt ein Belohnungs-Spiel an oder aktualisiert dessen Einstellungen."""
        self.conn.execute(
            "INSERT INTO reward_games (guild_id, game, interval_min, daily_cap) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id, game) DO UPDATE SET "
            "interval_min = excluded.interval_min, daily_cap = excluded.daily_cap",
            (guild_id, game.lower(), interval_min, daily_cap),
        )
        self.conn.commit()

    def get_reward_game(self, guild_id: int, game: str) -> tuple[int, int]:
        """(interval_min, daily_cap) eines Spiels; Defaults (30, 12), falls unbekannt."""
        row = self.conn.execute(
            "SELECT interval_min, daily_cap FROM reward_games WHERE guild_id = ? AND game = ?",
            (guild_id, game.lower()),
        ).fetchone()
        if row is None:
            return 30, 12
        return int(row["interval_min"]), int(row["daily_cap"])

    def list_reward_games_full(self, guild_id: int) -> list[tuple[str, int, int, str | None]]:
        """[(game, interval_min, daily_cap, booster_emoji), …]."""
        rows = self.conn.execute(
            "SELECT game, interval_min, daily_cap, booster_emoji FROM reward_games "
            "WHERE guild_id = ? ORDER BY game",
            (guild_id,),
        ).fetchall()
        return [
            (r["game"], int(r["interval_min"]), int(r["daily_cap"]), r["booster_emoji"])
            for r in rows
        ]

    def set_reward_game_emoji(self, guild_id: int, game: str, emoji: str | None) -> None:
        """Setzt (oder löscht mit None) das Booster-Emote eines Spiels."""
        self.conn.execute(
            "UPDATE reward_games SET booster_emoji = ? WHERE guild_id = ? AND game = ?",
            (emoji or None, guild_id, game.lower()),
        )
        self.conn.commit()

    def get_reward_game_emoji(self, guild_id: int, game: str) -> str | None:
        """Booster-Emote eines Spiels (Emoji-Name oder direkter Wert); None falls keins."""
        row = self.conn.execute(
            "SELECT booster_emoji FROM reward_games WHERE guild_id = ? AND game = ?",
            (guild_id, game.lower()),
        ).fetchone()
        return row["booster_emoji"] if row else None

    def remove_reward_game(self, guild_id: int, game: str) -> bool:
        cur = self.conn.execute(
            "DELETE FROM reward_games WHERE guild_id = ? AND game = ?", (guild_id, game.lower())
        )
        self.conn.execute(
            "DELETE FROM reward_game_aliases WHERE guild_id = ? AND game = ?",
            (guild_id, game.lower()),
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

    def add_reward_game_alias(self, guild_id: int, game: str, alias: str) -> None:
        """Ordnet einen Discord-Presence-Namen einem vorhandenen Reward-Spiel zu."""
        self.conn.execute(
            "INSERT INTO reward_game_aliases (guild_id, alias, game) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, alias) DO UPDATE SET game = excluded.game",
            (guild_id, alias.lower(), game.lower()),
        )
        self.conn.commit()

    def remove_reward_game_alias(self, guild_id: int, alias: str) -> bool:
        cur = self.conn.execute(
            "DELETE FROM reward_game_aliases WHERE guild_id = ? AND alias = ?",
            (guild_id, alias.lower()),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def list_reward_game_aliases(self, guild_id: int) -> list[tuple[str, str]]:
        """[(alias, game), …] für die Anzeige der Presence-Aliase."""
        rows = self.conn.execute(
            "SELECT alias, game FROM reward_game_aliases WHERE guild_id = ? ORDER BY game, alias",
            (guild_id,),
        ).fetchall()
        return [(r["alias"], r["game"]) for r in rows]

    def match_reward_game(self, guild_id: int, activity_name: str) -> str | None:
        """Löst einen Discord-Aktivitätsnamen auf das echte Reward-Spiel auf."""
        name = activity_name.lower()
        row = self.conn.execute(
            "SELECT game FROM reward_games WHERE guild_id = ? AND game = ?",
            (guild_id, name),
        ).fetchone()
        if row is not None:
            return row["game"]
        row = self.conn.execute(
            "SELECT a.game FROM reward_game_aliases a "
            "JOIN reward_games g ON g.guild_id = a.guild_id AND g.game = a.game "
            "WHERE a.guild_id = ? AND a.alias = ?",
            (guild_id, name),
        ).fetchone()
        return row["game"] if row else None

    # --- Benachrichtigungs-Server (Karten-Drops) ------------------------------

    def set_reward_notify_guild(self, user_id: int, guild_id: int | None) -> None:
        """Wunsch-Server eines Users für Drop-Meldungen; None = automatisch."""
        if guild_id is None:
            self.conn.execute("DELETE FROM reward_notify WHERE user_id = ?", (user_id,))
        else:
            self.conn.execute(
                "INSERT INTO reward_notify (user_id, guild_id) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET guild_id = excluded.guild_id",
                (user_id, guild_id),
            )
        self.conn.commit()

    def get_reward_notify_guild(self, user_id: int) -> int | None:
        row = self.conn.execute(
            "SELECT guild_id FROM reward_notify WHERE user_id = ?", (user_id,)
        ).fetchone()
        return int(row["guild_id"]) if row else None

    # --- Spielzeit (Karten-Rewards) -------------------------------------------

    def get_playtime(self, guild_id: int, user_id: int, game: str = "") -> tuple[int, str | None, int]:
        guild_id = GLOBAL_GID  # global: ein Spielzeit-Zähler + Tageslimit pro User & Spiel
        row = self.conn.execute(
            "SELECT accumulated, day, cards_today FROM playtime "
            "WHERE guild_id = ? AND user_id = ? AND game = ?",
            (guild_id, user_id, game),
        ).fetchone()
        if row is None:
            return 0, None, 0
        return int(row["accumulated"]), row["day"], int(row["cards_today"])

    def set_playtime(
        self, guild_id: int, user_id: int, accumulated: int, day: str, cards_today: int,
        game: str = "",
    ) -> None:
        guild_id = GLOBAL_GID
        self.conn.execute(
            "INSERT INTO playtime (guild_id, user_id, game, accumulated, day, cards_today) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(guild_id, user_id, game) DO UPDATE SET "
            "accumulated = excluded.accumulated, day = excluded.day, cards_today = excluded.cards_today",
            (guild_id, user_id, game, accumulated, day, cards_today),
        )
        self.conn.commit()

    # --- Reaction Roles -------------------------------------------------------
    # Emoji wird als String gespeichert: Unicode-Emoji direkt ("🎮") oder für
    # Server-Emojis die Form "name:id" (siehe cogs/reactionroles.py _emoji_key).

    def add_reaction_role(
        self,
        guild_id: int,
        channel_id: int,
        message_id: int,
        emoji: str,
        role_id: int,
        required_role_id: Optional[int] = None,
    ) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO reaction_roles "
            "(guild_id, channel_id, message_id, emoji, role_id, required_role_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, channel_id, message_id, emoji, role_id, required_role_id),
        )
        self.conn.commit()

    def remove_reaction_role(self, guild_id: int, message_id: int, emoji: str) -> bool:
        cur = self.conn.execute(
            "DELETE FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND emoji = ?",
            (guild_id, message_id, emoji),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def get_reaction_role(
        self, guild_id: int, message_id: int, emoji: str
    ) -> Optional[tuple[int, Optional[int]]]:
        """Liefert (role_id, required_role_id) oder None, wenn keine Bindung existiert."""
        row = self.conn.execute(
            "SELECT role_id, required_role_id FROM reaction_roles "
            "WHERE guild_id = ? AND message_id = ? AND emoji = ?",
            (guild_id, message_id, emoji),
        ).fetchone()
        if not row:
            return None
        req = row["required_role_id"]
        return (int(row["role_id"]), int(req) if req is not None else None)

    def list_reaction_roles(
        self, guild_id: int
    ) -> list[tuple[int, int, str, int, Optional[int]]]:
        rows = self.conn.execute(
            "SELECT channel_id, message_id, emoji, role_id, required_role_id FROM reaction_roles "
            "WHERE guild_id = ? ORDER BY message_id, emoji",
            (guild_id,),
        ).fetchall()
        return [
            (
                int(r["channel_id"]),
                int(r["message_id"]),
                r["emoji"],
                int(r["role_id"]),
                int(r["required_role_id"]) if r["required_role_id"] is not None else None,
            )
            for r in rows
        ]

    # --- Join-to-Create Voice -------------------------------------------------

    def get_voice_config(self, guild_id: int) -> dict:
        row = self.conn.execute(
            "SELECT voice_enabled, voice_lobby_id, voice_category_id "
            "FROM guild_settings WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()
        if row is None:
            return {"enabled": False, "lobby_id": None, "category_id": None}
        return {
            "enabled": bool(row["voice_enabled"]),
            "lobby_id": int(row["voice_lobby_id"]) if row["voice_lobby_id"] else None,
            "category_id": int(row["voice_category_id"]) if row["voice_category_id"] else None,
        }

    def set_voice_config(
        self,
        guild_id: int,
        *,
        enabled: bool,
        lobby_id: int | None,
        category_id: int | None,
    ) -> None:
        self._ensure_settings(guild_id)
        self.conn.execute(
            "UPDATE guild_settings SET voice_enabled = ?, voice_lobby_id = ?, "
            "voice_category_id = ? WHERE guild_id = ?",
            (1 if enabled else 0, lobby_id, category_id, guild_id),
        )
        self.conn.commit()

    def add_temp_voice_channel(
        self,
        guild_id: int,
        channel_id: int,
        owner_id: int,
        *,
        created_at: float | None = None,
    ) -> None:
        self.conn.execute(
            "INSERT INTO temp_voice_channels (channel_id, guild_id, owner_id, created_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(channel_id) DO UPDATE SET "
            "guild_id = excluded.guild_id, owner_id = excluded.owner_id",
            (channel_id, guild_id, owner_id, time.time() if created_at is None else created_at),
        )
        self.conn.commit()

    def get_temp_voice_channel(self, channel_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM temp_voice_channels WHERE channel_id = ?", (channel_id,)
        ).fetchone()

    def list_temp_voice_channels(self, guild_id: int | None = None) -> list[sqlite3.Row]:
        if guild_id is None:
            return self.conn.execute(
                "SELECT * FROM temp_voice_channels ORDER BY channel_id"
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM temp_voice_channels WHERE guild_id = ? ORDER BY channel_id",
            (guild_id,),
        ).fetchall()

    def set_temp_voice_owner(self, channel_id: int, owner_id: int) -> bool:
        cur = self.conn.execute(
            "UPDATE temp_voice_channels SET owner_id = ? WHERE channel_id = ?",
            (owner_id, channel_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def remove_temp_voice_channel(self, channel_id: int) -> bool:
        cur = self.conn.execute(
            "DELETE FROM temp_voice_channels WHERE channel_id = ?", (channel_id,)
        )
        self.conn.commit()
        return cur.rowcount > 0

    # --- Verwarnungen ---------------------------------------------------------

    def add_warning(
        self,
        guild_id: int,
        user_id: int,
        moderator_id: int,
        reason: str,
        *,
        created_at: float | None = None,
    ) -> sqlite3.Row:
        """Speichert eine Verwarnung und gibt den vollständigen Datensatz zurück."""
        cleaned_reason = reason.strip()
        if not cleaned_reason:
            raise ValueError("reason must not be empty")
        cur = self.conn.execute(
            "INSERT INTO warnings (guild_id, user_id, moderator_id, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                int(guild_id),
                int(user_id),
                int(moderator_id),
                cleaned_reason[:1000],
                time.time() if created_at is None else float(created_at),
            ),
        )
        self.conn.commit()
        return self.conn.execute(
            "SELECT * FROM warnings WHERE id = ?", (cur.lastrowid,)
        ).fetchone()

    def list_warnings(self, guild_id: int, user_id: int) -> list[sqlite3.Row]:
        """Listet alle Verwarnungen eines Mitglieds, neueste zuerst."""
        return self.conn.execute(
            "SELECT * FROM warnings WHERE guild_id = ? AND user_id = ? "
            "ORDER BY id DESC",
            (guild_id, user_id),
        ).fetchall()

    def remove_warning(self, guild_id: int, warning_id: int) -> sqlite3.Row | None:
        """Entfernt eine einzelne Verwarnung servergebunden und gibt sie zurück."""
        row = self.conn.execute(
            "SELECT * FROM warnings WHERE guild_id = ? AND id = ?",
            (guild_id, warning_id),
        ).fetchone()
        if row is None:
            return None
        self.conn.execute(
            "DELETE FROM warnings WHERE guild_id = ? AND id = ?",
            (guild_id, warning_id),
        )
        self.conn.commit()
        return row

    def clear_warnings(self, guild_id: int, user_id: int) -> int:
        """Entfernt alle Verwarnungen eines Mitglieds und gibt deren Anzahl zurück."""
        cur = self.conn.execute(
            "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        self.conn.commit()
        return cur.rowcount

    # --- Audit-Log ------------------------------------------------------------

    AUDIT_RETENTION = 2000  # max. gespeicherte Einträge pro Server

    def set_audit_channel(self, guild_id: int, channel_id: Optional[int]) -> None:
        self._ensure_settings(guild_id)
        self.conn.execute(
            "UPDATE guild_settings SET audit_channel_id = ? WHERE guild_id = ?",
            (channel_id, guild_id),
        )
        self.conn.commit()

    def get_audit_channel(self, guild_id: int) -> Optional[int]:
        row = self.conn.execute(
            "SELECT audit_channel_id FROM guild_settings WHERE guild_id = ?", (guild_id,)
        ).fetchone()
        return int(row["audit_channel_id"]) if row and row["audit_channel_id"] else None

    def get_audit_settings(self, guild_id: int) -> dict[str, bool]:
        rows = self.conn.execute(
            "SELECT category, enabled FROM audit_settings WHERE guild_id = ?", (guild_id,)
        ).fetchall()
        return {r["category"]: bool(r["enabled"]) for r in rows}

    def set_audit_setting(self, guild_id: int, category: str, enabled: bool) -> None:
        self.conn.execute(
            "INSERT INTO audit_settings (guild_id, category, enabled) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, category) DO UPDATE SET enabled = excluded.enabled",
            (guild_id, category, 1 if enabled else 0),
        )
        self.conn.commit()

    def is_audit_enabled(self, guild_id: int, category: str) -> bool:
        row = self.conn.execute(
            "SELECT enabled FROM audit_settings WHERE guild_id = ? AND category = ?",
            (guild_id, category),
        ).fetchone()
        return bool(row["enabled"]) if row is not None else True  # Default: an

    def add_audit_log(
        self, guild_id: int, category: str, event_type: str, summary: str,
        actor_id: Optional[int] = None, target_id: Optional[int] = None,
        channel_id: Optional[int] = None, detail: Optional[str] = None,
    ) -> None:
        import time as _time
        self.conn.execute(
            "INSERT INTO audit_log "
            "(guild_id, ts, category, event_type, actor_id, target_id, channel_id, summary, detail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (guild_id, _time.time(), category, event_type, actor_id, target_id,
             channel_id, summary, detail),
        )
        # Auf die letzten AUDIT_RETENTION Einträge je Server begrenzen.
        self.conn.execute(
            "DELETE FROM audit_log WHERE guild_id = ? AND id NOT IN "
            "(SELECT id FROM audit_log WHERE guild_id = ? ORDER BY id DESC LIMIT ?)",
            (guild_id, guild_id, self.AUDIT_RETENTION),
        )
        self.conn.commit()

    def list_audit_log(
        self, guild_id: int, category: Optional[str] = None, limit: int = 100
    ) -> list[dict]:
        if category:
            rows = self.conn.execute(
                "SELECT * FROM audit_log WHERE guild_id = ? AND category = ? "
                "ORDER BY id DESC LIMIT ?",
                (guild_id, category, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM audit_log WHERE guild_id = ? ORDER BY id DESC LIMIT ?",
                (guild_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def clear_audit_log(self, guild_id: int) -> None:
        self.conn.execute("DELETE FROM audit_log WHERE guild_id = ?", (guild_id,))
        self.conn.commit()

    # --- Ticket-System --------------------------------------------------------

    DEFAULT_TICKET_TITLE = "🎫 Support-Tickets"
    DEFAULT_TICKET_TEXT = (
        "Du brauchst Hilfe oder hast ein Anliegen? Wähle unten ein Thema — wir "
        "öffnen dann einen privaten Ticket-Thread nur für dich und unser Team."
    )

    def get_ticket_config(self, guild_id: int) -> dict:
        row = self.conn.execute(
            "SELECT ticket_enabled, ticket_panel_channel_id, ticket_panel_message_id, "
            "ticket_support_role_id, ticket_log_channel_id, ticket_panel_title, "
            "ticket_panel_text FROM guild_settings WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()
        if row is None:
            return {
                "enabled": False, "panel_channel_id": None, "panel_message_id": None,
                "support_role_id": None, "log_channel_id": None,
                "title": self.DEFAULT_TICKET_TITLE, "text": self.DEFAULT_TICKET_TEXT,
            }
        return {
            "enabled": bool(row["ticket_enabled"]),
            "panel_channel_id": int(row["ticket_panel_channel_id"]) if row["ticket_panel_channel_id"] else None,
            "panel_message_id": int(row["ticket_panel_message_id"]) if row["ticket_panel_message_id"] else None,
            "support_role_id": int(row["ticket_support_role_id"]) if row["ticket_support_role_id"] else None,
            "log_channel_id": int(row["ticket_log_channel_id"]) if row["ticket_log_channel_id"] else None,
            "title": row["ticket_panel_title"] or self.DEFAULT_TICKET_TITLE,
            "text": row["ticket_panel_text"] or self.DEFAULT_TICKET_TEXT,
        }

    def set_ticket_config(
        self, guild_id: int, *, enabled: Optional[bool] = None,
        support_role_id: Optional[int] = -1, log_channel_id: Optional[int] = -1,
        title: Optional[str] = -1, text: Optional[str] = -1,  # type: ignore[assignment]
    ) -> None:
        """Aktualisiert nur die übergebenen Felder (Sentinel -1 = unverändert)."""
        self._ensure_settings(guild_id)
        sets, vals = [], []
        if enabled is not None:
            sets.append("ticket_enabled = ?"); vals.append(1 if enabled else 0)
        if support_role_id != -1:
            sets.append("ticket_support_role_id = ?"); vals.append(support_role_id)
        if log_channel_id != -1:
            sets.append("ticket_log_channel_id = ?"); vals.append(log_channel_id)
        if title != -1:
            sets.append("ticket_panel_title = ?"); vals.append(title)
        if text != -1:
            sets.append("ticket_panel_text = ?"); vals.append(text)
        if not sets:
            return
        vals.append(guild_id)
        self.conn.execute(
            f"UPDATE guild_settings SET {', '.join(sets)} WHERE guild_id = ?", vals
        )
        self.conn.commit()

    def set_ticket_panel(
        self, guild_id: int, channel_id: Optional[int], message_id: Optional[int]
    ) -> None:
        self._ensure_settings(guild_id)
        self.conn.execute(
            "UPDATE guild_settings SET ticket_panel_channel_id = ?, "
            "ticket_panel_message_id = ? WHERE guild_id = ?",
            (channel_id, message_id, guild_id),
        )
        self.conn.commit()

    def next_ticket_number(self, guild_id: int) -> int:
        self._ensure_settings(guild_id)
        self.conn.execute(
            "UPDATE guild_settings SET ticket_counter = ticket_counter + 1 WHERE guild_id = ?",
            (guild_id,),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT ticket_counter FROM guild_settings WHERE guild_id = ?", (guild_id,)
        ).fetchone()
        return int(row["ticket_counter"]) if row else 1

    # --- Ticket-Kategorien (Panel-Themen) -------------------------------------

    def add_ticket_category(
        self, guild_id: int, label: str, emoji: Optional[str], description: Optional[str]
    ) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 AS p FROM ticket_categories WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()
        pos = int(row["p"]) if row else 1
        cur = self.conn.execute(
            "INSERT INTO ticket_categories (guild_id, label, emoji, description, position) "
            "VALUES (?, ?, ?, ?, ?)",
            (guild_id, label, emoji, description, pos),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def remove_ticket_category(self, guild_id: int, cat_id: int) -> bool:
        cur = self.conn.execute(
            "DELETE FROM ticket_categories WHERE guild_id = ? AND id = ?", (guild_id, cat_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def list_ticket_categories(self, guild_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, label, emoji, description FROM ticket_categories "
            "WHERE guild_id = ? ORDER BY position, id",
            (guild_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_ticket_category(self, guild_id: int, cat_id: int) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT id, label, emoji, description FROM ticket_categories "
            "WHERE guild_id = ? AND id = ?",
            (guild_id, cat_id),
        ).fetchone()
        return dict(row) if row else None

    # --- Einzelne Tickets -----------------------------------------------------

    def create_ticket(
        self, thread_id: int, guild_id: int, channel_id: int, opener_id: int,
        category_id: Optional[int], category_label: str, number: int, created_at: float,
    ) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO tickets (thread_id, guild_id, channel_id, opener_id, "
            "category_id, category_label, claimed_by, status, number, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL, 'open', ?, ?)",
            (thread_id, guild_id, channel_id, opener_id, category_id, category_label,
             number, created_at),
        )
        self.conn.commit()

    def get_ticket(self, thread_id: int) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM tickets WHERE thread_id = ?", (thread_id,)
        ).fetchone()
        return dict(row) if row else None

    def set_ticket_claimed(self, thread_id: int, user_id: Optional[int]) -> None:
        self.conn.execute(
            "UPDATE tickets SET claimed_by = ? WHERE thread_id = ?", (user_id, thread_id)
        )
        self.conn.commit()

    def close_ticket(self, thread_id: int) -> None:
        self.conn.execute(
            "UPDATE tickets SET status = 'closed' WHERE thread_id = ?", (thread_id,)
        )
        self.conn.commit()

    def count_open_tickets(self, guild_id: int, opener_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM tickets "
            "WHERE guild_id = ? AND opener_id = ? AND status = 'open'",
            (guild_id, opener_id),
        ).fetchone()
        return int(row["n"]) if row else 0

    def list_open_tickets(self, guild_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM tickets WHERE guild_id = ? AND status = 'open' "
            "ORDER BY number DESC",
            (guild_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_tickets(self, guild_id: int, limit: int = 200) -> list[dict]:
        """Alle Tickets (offen + geschlossen), neueste zuerst — fürs Admin-Panel."""
        rows = self.conn.execute(
            "SELECT * FROM tickets WHERE guild_id = ? ORDER BY number DESC LIMIT ?",
            (guild_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Ticket-Transcripts ---------------------------------------------------

    def save_ticket_transcript(
        self, *, token: str, thread_id: int, guild_id: int, number: int,
        category_label: str, opener_id: int, opener_name: str,
        closed_by_id: int, closed_by_name: str, closed_at: float,
        message_count: int, data: str,
    ) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO ticket_transcripts "
            "(token, thread_id, guild_id, number, category_label, opener_id, opener_name, "
            "closed_by_id, closed_by_name, closed_at, message_count, data) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (token, thread_id, guild_id, number, category_label, opener_id, opener_name,
             closed_by_id, closed_by_name, closed_at, message_count, data),
        )
        self.conn.commit()

    def get_ticket_transcript(self, token: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM ticket_transcripts WHERE token = ?", (token,)
        ).fetchone()
        return dict(row) if row else None

    def get_transcript_token(self, thread_id: int) -> Optional[str]:
        row = self.conn.execute(
            "SELECT token FROM ticket_transcripts WHERE thread_id = ? "
            "ORDER BY closed_at DESC LIMIT 1",
            (thread_id,),
        ).fetchone()
        return row["token"] if row else None

    def list_ticket_transcripts(self, guild_id: int, limit: int = 100) -> list[dict]:
        rows = self.conn.execute(
            "SELECT token, thread_id, number, category_label, opener_id, opener_name, "
            "closed_by_id, closed_by_name, closed_at, message_count "
            "FROM ticket_transcripts WHERE guild_id = ? ORDER BY closed_at DESC LIMIT ?",
            (guild_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

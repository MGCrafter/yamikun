"""DEV-ONLY: Webpanel lokal mit echten DB-Daten ansehen — ohne Discord-Login.

Was es macht
------------
- Kopiert die echte `bot.db` nach /tmp/devpanel/ und arbeitet NUR auf der Kopie
  (deine echte Datei bleibt unangetastet — Löschen/Coins ändern wirkt nur lokal).
- Liest die Guild-IDs aus der DB und baut einen Fake-Bot mit passenden
  Fake-Guilds/Channels (es läuft kein echter Discord-Bot).
- Überspringt OAuth: jede Anfrage gilt als eingeloggter Dummy-Admin mit Zugriff
  auf alle gefundenen Server.
- Startet den echten WebPanelCog-Server und liefert das gebaute React-Frontend.

Start:  .venv/bin/python dev_panel.py
Dann:   http://127.0.0.1:8099/app
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sqlite3
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
SRC_DB = PROJECT / "bot.db"
DEV_DIR = Path("/tmp/devpanel")
DEV_DB = DEV_DIR / "bot.db"
PORT = 8099

# --- DB-Kopie anlegen (inkl. WAL/SHM, damit alle Daten mitkommen) ---------
DEV_DIR.mkdir(parents=True, exist_ok=True)
(DEV_DIR / "static").mkdir(exist_ok=True)
for suffix in ("", "-wal", "-shm"):
    src = Path(str(SRC_DB) + suffix)
    if src.exists():
        shutil.copy2(src, str(DEV_DB) + suffix)
print(f"[dev] bot.db -> {DEV_DB} kopiert (Original bleibt unangetastet)")

# --- Env für den Cog setzen, BEVOR er importiert wird ---------------------
os.environ.update({
    "WEB_ENABLED": "1",
    "WEB_BASE_URL": f"http://127.0.0.1:{PORT}",
    "OAUTH_CLIENT_ID": "dev",
    "OAUTH_CLIENT_SECRET": "dev",
    "WEB_HOST": "127.0.0.1",
    "WEB_PORT": str(PORT),
    "DATA_DIR": str(DEV_DIR),
    # WEB_OWNER_IDS leer lassen -> Dummy-Admin darf alles bearbeiten.
})

from db import Database  # noqa: E402
from cogs.webpanel import WebPanelCog  # noqa: E402


# --- Guild-IDs + Drop-Channels aus der DB lesen ---------------------------
def discover_guilds() -> dict[int, int | None]:
    """{guild_id: card_channel_id|None} aus der DB."""
    con = sqlite3.connect(str(DEV_DB))
    con.row_factory = sqlite3.Row
    gids: set[int] = set()
    for tbl in ("guild_settings", "reward_games", "levels", "custom_cards"):
        try:
            for r in con.execute(f"SELECT DISTINCT guild_id FROM {tbl}"):
                if r[0]:
                    gids.add(int(r[0]))
        except sqlite3.Error:
            pass
    channels: dict[int, int | None] = {g: None for g in gids}
    try:
        for r in con.execute("SELECT guild_id, card_channel_id FROM guild_settings"):
            channels[int(r["guild_id"])] = r["card_channel_id"]
    except sqlite3.Error:
        pass
    con.close()
    return channels


# --- Fake-Discord-Objekte -------------------------------------------------
class FakeChannel:
    def __init__(self, cid: int, name: str, category=None):
        self.id = cid
        self.name = name
        self.category = category


class FakeColor:
    def __init__(self, value: int):
        self.value = value


class FakeRole:
    def __init__(self, rid, name, position, color=0, default=False, managed=False):
        self.id = rid
        self.name = name
        self.position = position
        self.color = FakeColor(color)
        self._default = default
        self.managed = managed

    def is_default(self):
        return self._default

    def __lt__(self, other):
        return self.position < other.position


class FakeMember:
    def __init__(self, top_role):
        self.top_role = top_role
        self.guild_permissions = type(
            "FakePermissions",
            (),
            {"manage_channels": True, "move_members": True},
        )()


class _FakeAsset:
    def __init__(self, url: str):
        self.url = url

class FakeUser:
    def __init__(self, uid: int):
        self.display_name = f"User-{str(uid)[-4:]}"
        # Default-Discord-Avatar als Vorschau-Profilbild.
        self.display_avatar = _FakeAsset(
            f"https://cdn.discordapp.com/embed/avatars/{(uid >> 22) % 6}.png"
        )


class FakeGuild:
    def __init__(self, gid: int, name: str, drop_channel: int | None):
        self.id = gid
        self.name = name
        self.emojis = []
        self.text_channels = [
            FakeChannel(1, "allgemein"),
            FakeChannel(2, "bot-spam"),
        ]
        self.categories = [FakeChannel(10, "Yami Voice"), FakeChannel(11, "Gaming")]
        self.voice_channels = [
            FakeChannel(20, "➕ Eigenen Channel erstellen"),
            FakeChannel(21, "Meine Gaming Lobby"),
        ]
        self.voice_channels[0].category = self.categories[0]
        self.voice_channels[1].category = self.categories[1]
        # Gespeicherten Drop-Channel als echten Eintrag ergänzen (zeigt sich als ausgewählt).
        if drop_channel:
            self.text_channels.insert(0, FakeChannel(int(drop_channel), "card-drops"))
        # Fake-Rollen (für die Reaction-Roles-Seite). @everyone hat die Guild-ID.
        self.roles = [
            FakeRole(gid, "@everyone", 0, default=True),
            FakeRole(111, "Member", 1, 0x3498DB),
            FakeRole(222, "Gamer", 2, 0x2ECC71),
            FakeRole(333, "VIP", 3, 0xF1C40F),
        ]
        self.me = FakeMember(FakeRole(900, "YamiBot", 900))

    def get_channel(self, cid: int):
        return next((c for c in [*self.text_channels, *self.categories] if c.id == cid), None)

    def get_member(self, _uid: int):
        return None

    def get_role(self, rid: int):
        return next((r for r in self.roles if r.id == rid), None)


class FakeBot:
    def __init__(self, guild_channels: dict[int, int | None]):
        self.db = Database(str(DEV_DB))
        self.guilds = [
            FakeGuild(gid, f"Mein Server ({str(gid)[-4:]})", ch)
            for gid, ch in guild_channels.items()
        ]
        self._by_id = {g.id: g for g in self.guilds}

    def get_guild(self, gid: int):
        return self._by_id.get(gid)

    def get_user(self, uid: int):
        return FakeUser(uid)

    def get_cog(self, name: str):
        # Im Dev-Panel laufen keine echten Cogs (kein Discord-Login).
        return None


async def main():
    guild_channels = discover_guilds()
    if not guild_channels:
        print("[dev] Keine Guild-IDs in der DB gefunden — nichts anzuzeigen.")
        return
    print(f"[dev] Gefundene Server: {list(guild_channels)}")

    bot = FakeBot(guild_channels)
    cog = WebPanelCog(bot)

    # OAuth überspringen: jede Anfrage = eingeloggter Dummy-Admin mit allen Servern.
    # Für eine sinnvolle Vorschau: Dummy-Konto = größter Karten-Sammler der DB.
    demo_uid = 1
    try:
        con = sqlite3.connect(str(DEV_DB))
        row = con.execute(
            "SELECT user_id, SUM(count) c FROM card_inventory GROUP BY user_id ORDER BY c DESC LIMIT 1"
        ).fetchone()
        if row:
            demo_uid = int(row[0])
        con.close()
    except sqlite3.Error:
        pass

    dummy_session = {
        "user_id": demo_uid,
        "username": "Dev Admin",
        "avatar": f"https://cdn.discordapp.com/embed/avatars/{(demo_uid >> 22) % 6}.png",
        "guilds": {g.id: g.name for g in bot.guilds},
        "member_guilds": {g.id: g.name for g in bot.guilds},
        "csrf": "dev-csrf-token",
        "exp": time.time() + 10**9,
    }
    cog._session = lambda request: dummy_session  # type: ignore[assignment]

    await cog.cog_load()
    first = bot.guilds[0].id
    print("\n" + "=" * 60)
    print("  Dev-Panel läuft — KEIN Login nötig.")
    print(f"  Dashboard:   http://127.0.0.1:{PORT}/app")
    print(f"  Direkt:      http://127.0.0.1:{PORT}/g/{first}/overview")
    print("  Beenden mit Strg+C")
    print("=" * 60 + "\n")
    try:
        await asyncio.Event().wait()  # laufen lassen
    finally:
        await cog.cog_unload()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[dev] beendet.")

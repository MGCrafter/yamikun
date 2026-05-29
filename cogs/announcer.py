"""Announcer: postet neue Beiträge überwachter Quellen in einen Announce-Channel.

- YouTube-Kanäle werden automatisch auf ihren offiziellen RSS-Feed abgebildet
  (kein API-Key nötig).
- Beliebige andere RSS-Feeds (z.B. Bridge-Feeds für TikTok/Instagram) lassen sich
  ebenfalls hinzufügen.
- Zusätzlich gibt es /announce post für manuelles Reposten beliebiger Links.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

logger = logging.getLogger("oaken-tower-bot")

POLL_MINUTES: float = 5.0
MAX_POSTS_PER_POLL: int = 5  # gegen Spam, falls viele neue Einträge auf einmal
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (OakenTowerBot)"}

_YT_CHANNEL_ID = re.compile(r"UC[\w-]{22}")
_YT_RSS = "https://www.youtube.com/feeds/videos.xml?channel_id={}"


def _local(tag: str) -> str:
    """Lokaler Tag-Name ohne XML-Namespace."""
    return tag.rsplit("}", 1)[-1]


def parse_feed(content: bytes) -> list[dict]:
    """Parst Atom- (YouTube) und RSS-Feeds zu einer Liste {id, title, link}.

    Reihenfolge bleibt wie im Feed (i.d.R. neueste zuerst).
    """
    root = ET.fromstring(content)
    entries: list[dict] = []
    for node in root.iter():
        if _local(node.tag) not in ("entry", "item"):
            continue
        title = link = video_id = atom_id = guid = None
        for child in node:
            name = _local(child.tag)
            text = (child.text or "").strip() if child.text else ""
            if name == "title" and title is None:
                title = text
            elif name == "videoId":
                video_id = text
            elif name == "id" and atom_id is None:
                atom_id = text
            elif name == "guid" and guid is None:
                guid = text
            elif name == "link":
                href = child.get("href")
                if href:
                    if link is None or child.get("rel") == "alternate":
                        link = href
                elif text:
                    link = text
        entry_id = video_id or guid or atom_id or link
        if entry_id:
            entries.append({"id": entry_id, "title": title or "(ohne Titel)", "link": link})
    return entries


class AnnouncerCog(commands.Cog):
    """Überwacht Feeds und kündigt neue Beiträge an."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]
        self.session: Optional[aiohttp.ClientSession] = None

    async def cog_load(self) -> None:
        self.session = aiohttp.ClientSession(headers=HTTP_HEADERS)
        self.poll_loop.start()

    async def cog_unload(self) -> None:
        self.poll_loop.cancel()
        if self.session:
            await self.session.close()

    # --- Quellen-Auflösung ----------------------------------------------------

    async def _fetch(self, url: str) -> bytes:
        assert self.session is not None
        async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            resp.raise_for_status()
            return await resp.read()

    async def _resolve(self, raw: str) -> tuple[str, str, Optional[str]]:
        """Wandelt eine Eingabe in (feed_url, kind, label_hinweis) um.

        Unterstützt: YouTube-Kanal-ID (UC…), YouTube-URLs (Kanal/Handle/@/feeds)
        und beliebige RSS-Feed-URLs.
        """
        raw = raw.strip()

        # Reine YouTube-Kanal-ID
        if _YT_CHANNEL_ID.fullmatch(raw):
            return _YT_RSS.format(raw), "youtube", None

        if "youtube.com" in raw or "youtu.be" in raw:
            if "/feeds/videos.xml" in raw:
                return raw, "youtube", None
            m = re.search(r"/channel/(UC[\w-]{22})", raw)
            if m:
                return _YT_RSS.format(m.group(1)), "youtube", None
            # Handle/@/c/user → Kanal-ID aus der Seite ziehen
            channel_id = await self._scrape_channel_id(raw)
            if channel_id:
                return _YT_RSS.format(channel_id), "youtube", None
            raise ValueError("Konnte die YouTube-Kanal-ID nicht ermitteln.")

        # Bare @handle → YouTube-Handle
        if raw.startswith("@"):
            channel_id = await self._scrape_channel_id(f"https://www.youtube.com/{raw}")
            if channel_id:
                return _YT_RSS.format(channel_id), "youtube", None
            raise ValueError("Konnte die YouTube-Kanal-ID nicht ermitteln.")

        # Sonst: beliebiger RSS-Feed
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw, "rss", None

        raise ValueError("Unbekanntes Format. Gib eine YouTube-URL/Kanal-ID oder eine RSS-Feed-URL an.")

    async def _scrape_channel_id(self, url: str) -> Optional[str]:
        try:
            html = (await self._fetch(url)).decode("utf-8", errors="ignore")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Konnte YouTube-Seite nicht laden (%s): %s", url, exc)
            return None
        m = re.search(r'"channelId":"(UC[\w-]{22})"', html) or re.search(
            r'/channel/(UC[\w-]{22})', html
        )
        return m.group(1) if m else None

    # --- Poll-Loop ------------------------------------------------------------

    @tasks.loop(minutes=POLL_MINUTES)
    async def poll_loop(self) -> None:
        for feed in self.db.all_feeds():
            try:
                await self._check_feed(feed)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Feed %s (%s) fehlgeschlagen: %s", feed["id"], feed["feed_url"], exc)

    @poll_loop.before_loop
    async def _before_poll(self) -> None:
        await self.bot.wait_until_ready()

    async def _check_feed(self, feed) -> None:
        content = await self._fetch(feed["feed_url"])
        entries = parse_feed(content)
        if not entries:
            return
        newest_id = entries[0]["id"]
        last_id = feed["last_entry_id"]

        # Erstinitialisierung: nur merken, keine alten Beiträge nachposten.
        if not last_id:
            self.db.update_feed_last_id(feed["id"], newest_id)
            return
        if newest_id == last_id:
            return

        # Neue Einträge sammeln (bis zum zuletzt bekannten), älteste zuerst posten.
        new_entries: list[dict] = []
        for entry in entries:
            if entry["id"] == last_id:
                break
            new_entries.append(entry)
        new_entries = list(reversed(new_entries[:MAX_POSTS_PER_POLL]))

        channel = self._announce_channel(feed["guild_id"])
        if channel is not None:
            for entry in new_entries:
                await self._post_entry(channel, feed["label"], entry)

        self.db.update_feed_last_id(feed["id"], newest_id)

    def _announce_channel(self, guild_id: int) -> Optional[discord.abc.Messageable]:
        channel_id = self.db.get_announce_channel(guild_id)
        if not channel_id:
            return None
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return None
        channel = guild.get_channel(channel_id)
        return channel if isinstance(channel, discord.abc.Messageable) else None

    async def _post_entry(self, channel: discord.abc.Messageable, label, entry: dict) -> None:
        header = f"📢 **Neuer Beitrag{f' von {label}' if label else ''}**"
        body = entry["link"] or entry["title"]
        try:
            await channel.send(f"{header}\n{body}")
        except discord.Forbidden:
            logger.warning("Keine Berechtigung zum Posten im Announce-Channel.")

    # --- /announce-Befehlsgruppe (nur Mods) -----------------------------------

    announce = app_commands.Group(
        name="announce",
        description="Announce-Channel und überwachte Quellen verwalten (nur Mods).",
        guild_only=True,
        default_permissions=discord.Permissions(manage_channels=True),
    )

    @announce.command(name="channel", description="Setzt den Announce-Channel.")
    @app_commands.describe(channel="Channel, in den neue Beiträge gepostet werden")
    async def announce_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        self.db.set_announce_channel(interaction.guild_id, channel.id)
        await interaction.response.send_message(
            f"✅ Announce-Channel ist jetzt {channel.mention}.", ephemeral=True
        )

    @announce.command(name="add", description="Fügt eine Quelle hinzu (YouTube-Kanal oder RSS-Feed).")
    @app_commands.describe(
        quelle="YouTube-URL/Kanal-ID/@Handle oder beliebige RSS-Feed-URL",
        label="Optionaler Anzeigename (z.B. der Name der Person)",
    )
    async def announce_add(
        self, interaction: discord.Interaction, quelle: str, label: Optional[str] = None
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            feed_url, kind, _ = await self._resolve(quelle)
        except ValueError as exc:
            await interaction.followup.send(f"⚠️ {exc}", ephemeral=True)
            return

        # Aktuellen Stand merken, damit beim ersten Poll keine alten Beiträge kommen.
        last_id: Optional[str] = None
        try:
            entries = parse_feed(await self._fetch(feed_url))
            if entries:
                last_id = entries[0]["id"]
        except Exception as exc:  # noqa: BLE001
            await interaction.followup.send(
                f"⚠️ Quelle konnte nicht geladen werden: {exc}", ephemeral=True
            )
            return

        feed_id = self.db.add_feed(interaction.guild_id, feed_url, label, kind, last_id)
        await interaction.followup.send(
            f"✅ Quelle hinzugefügt (#{feed_id}, Typ `{kind}`"
            f"{f', Label „{label}"' if label else ''}).\n`{feed_url}`",
            ephemeral=True,
        )

    @announce.command(name="list", description="Zeigt alle überwachten Quellen.")
    async def announce_list(self, interaction: discord.Interaction) -> None:
        feeds = self.db.list_feeds(interaction.guild_id)
        if not feeds:
            await interaction.response.send_message(
                "Es werden noch keine Quellen überwacht.", ephemeral=True
            )
            return
        lines = []
        for f in feeds:
            label = f' „{f["label"]}"' if f["label"] else ""
            lines.append(f"**#{f['id']}** [`{f['kind']}`]{label}\n`{f['feed_url']}`")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @announce.command(name="remove", description="Entfernt eine Quelle anhand ihrer ID.")
    @app_commands.describe(id="Die ID aus /announce list")
    async def announce_remove(self, interaction: discord.Interaction, id: int) -> None:
        ok = self.db.remove_feed(interaction.guild_id, id)
        if ok:
            await interaction.response.send_message(f"🗑️ Quelle #{id} entfernt.", ephemeral=True)
        else:
            await interaction.response.send_message(
                f"⚠️ Keine Quelle mit ID #{id} gefunden.", ephemeral=True
            )

    @announce.command(name="post", description="Postet einen Link manuell in den Announce-Channel.")
    @app_commands.describe(link="Der zu postende Link", text="Optionaler Begleittext")
    async def announce_post(
        self, interaction: discord.Interaction, link: str, text: Optional[str] = None
    ) -> None:
        channel = self._announce_channel(interaction.guild_id)
        if channel is None:
            await interaction.response.send_message(
                "⚠️ Es ist noch kein Announce-Channel gesetzt (`/announce channel`).",
                ephemeral=True,
            )
            return
        message = f"📢 {text}\n{link}" if text else f"📢 {link}"
        try:
            await channel.send(message)
        except discord.Forbidden:
            await interaction.response.send_message(
                "⚠️ Mir fehlt die Berechtigung, in den Announce-Channel zu posten.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message("✅ Gepostet.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AnnouncerCog(bot))

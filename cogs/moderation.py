"""Moderations-Befehle. Aktuell: /purge zum Aufräumen von Channels."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("oaken-tower-bot")

MAX_PURGE = 100         # Discord-Limit für komfortables Bulk-Delete
SCAN_FACTOR = 10        # bei User-Filter so viel mehr Verlauf durchsuchen
SCAN_CAP = 1000


class ModerationCog(commands.Cog):
    """/purge — löscht eine angegebene Anzahl Nachrichten (optional nur eines Users)."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="purge",
        description="Löscht die letzten Nachrichten im Channel (optional nur von einem User).",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(
        anzahl="Wie viele Nachrichten löschen (1–100)",
        user="Optional: nur Nachrichten dieses Users löschen",
    )
    async def purge(
        self,
        interaction: discord.Interaction,
        anzahl: app_commands.Range[int, 1, MAX_PURGE],
        user: discord.Member | None = None,
    ) -> None:
        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            await interaction.response.send_message(
                "⚠️ In diesem Channel-Typ kann ich nicht löschen.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        matched = 0

        def check(message: discord.Message) -> bool:
            nonlocal matched
            if matched >= anzahl:
                return False
            if user is not None and message.author.id != user.id:
                return False
            matched += 1
            return True

        # Ohne Filter genau `anzahl` Nachrichten; mit Filter mehr Verlauf scannen.
        scan = anzahl if user is None else min(anzahl * SCAN_FACTOR, SCAN_CAP)
        try:
            deleted = await channel.purge(limit=scan, check=check, bulk=True)
        except discord.Forbidden:
            await interaction.followup.send(
                "⚠️ Mir fehlt die Berechtigung **Nachrichten verwalten** in diesem Channel.",
                ephemeral=True,
            )
            return
        except discord.HTTPException as exc:
            await interaction.followup.send(
                f"⚠️ Löschen fehlgeschlagen: {exc}. "
                "(Nachrichten älter als 14 Tage lassen sich nicht massenweise löschen.)",
                ephemeral=True,
            )
            return

        suffix = f" von {user.mention}" if user else ""
        logger.info(
            "Purge in Channel %s durch %s: %d Nachricht(en) gelöscht.",
            channel.id, interaction.user.id, len(deleted),
        )
        await interaction.followup.send(
            f"🧹 **{len(deleted)}** Nachricht(en){suffix} gelöscht.", ephemeral=True
        )

    @app_commands.command(name="say", description="Lässt den Bot eine Nachricht schreiben.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(text="Was soll der Bot sagen?", channel="Optional: Zielchannel")
    async def say(
        self,
        interaction: discord.Interaction,
        text: str,
        channel: discord.TextChannel | None = None,
    ) -> None:
        target = channel or interaction.channel
        try:
            # @everyone/@here bewusst sperren (kein Massen-Ping über den Bot).
            await target.send(text, allowed_mentions=discord.AllowedMentions(everyone=False))
        except discord.Forbidden:
            await interaction.response.send_message(
                "⚠️ Mir fehlt die Berechtigung, in diesem Channel zu schreiben.", ephemeral=True
            )
            return
        logger.info("Say von %s in Channel %s: %s", interaction.user.id, target.id, text[:120])
        await interaction.response.send_message(f"✅ Gesendet in {target.mention}.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationCog(bot))

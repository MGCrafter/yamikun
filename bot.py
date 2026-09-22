"""Oaken Tower Discord Bot — Entrypoint.

Lädt die Feature-Cogs (Auto-Delete, Leveling, Announcer), synchronisiert die
Slash-Commands und startet den Bot.

Features:
- cogs/oaken.py     — Auto-Delete veralteter Oaken-Tower-Codes (/oaken)
- cogs/leveling.py  — XP/Level aus Nachrichten & Voice, Coins (/rank, /leaderboard, /level)
- cogs/announcer.py — Announce neuer Beiträge überwachter Quellen (/announce)

Siehe docs/archive/oaken-tower-bot-spec.md und README.md für Details.
"""

from __future__ import annotations

import logging
import os

import discord
from discord import app_commands
from discord.ext import commands

from db import Database, DB_FILE

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# --- Konstanten ---------------------------------------------------------------
TOKEN_ENV: str = "DISCORD_TOKEN"
GUILD_ENV: str = "GUILD_ID"
COGS: tuple[str, ...] = (
    "cogs.oaken",
    "cogs.leveling",
    "cogs.announcer",
    "cogs.gambling",
    "cogs.blackjack",
    "cogs.slots",
    "cogs.roulette",
    "cogs.economy",
    "cogs.shop",
    "cogs.interactions",
    "cogs.social",
    "cogs.achievements",
    "cogs.lfg",
    "cogs.marry",
    "cogs.titles",
    "cogs.gamecards",
    "cogs.booster",
    "cogs.fusion",
    "cogs.profile",
    "cogs.moderation",
    "cogs.voicemaster",
    "cogs.reactionroles",
    "cogs.tickets",
    "cogs.welcome",
    "cogs.boostnotify",
    "cogs.twitch",
    "cogs.autoroles",
    "cogs.audit",
    "cogs.fun",
    "cogs.help",
    "cogs.webpanel",
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("oaken-tower-bot")


class OakenTowerBot(commands.Bot):
    """Bot mit Auto-Delete, Leveling und Announcer."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # Codes erkennen, Nachrichten-XP, Audit-Log
        # Members-Intent wird für Welcome-Nachrichten, das Audit-Log (Join/Leave,
        # Rollen-/Nick-Änderungen) und das Entfernen von Reaction Roles gebraucht.
        # WICHTIG: "Server Members Intent" muss im Developer Portal aktiviert sein,
        # sonst startet der Bot nicht.
        intents.members = True
        # Presence nur optional (Aktivitäts-Tracking für Karten-Rewards) — eigener
        # privilegierter Intent, daher hinter einem Schalter.
        if os.environ.get("PRESENCE_INTENT") == "1":
            intents.presences = True
        super().__init__(command_prefix="!", intents=intents)
        self.db = Database(DB_FILE)

    async def setup_hook(self) -> None:
        # Cogs laden, BEVOR synchronisiert wird (Commands müssen im Baum sein).
        for ext in COGS:
            try:
                await self.load_extension(ext)
                logger.info("Cog geladen: %s", ext)
            except Exception:  # noqa: BLE001
                logger.exception("Cog konnte nicht geladen werden: %s", ext)

        guild_id = os.environ.get(GUILD_ENV)
        if guild_id:
            try:
                guild = discord.Object(id=int(guild_id))
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                logger.info(
                    "%d Command(s) auf Guild %s gesynct (sofort sichtbar).",
                    len(synced), guild_id,
                )
                # Etwaige global registrierte Commands entfernen → keine Duplikate.
                self.tree.clear_commands(guild=None)
                await self.tree.sync()
                logger.info("Globale Commands geleert (Duplikate vermieden).")
                return
            except ValueError:
                logger.warning("GUILD_ID=%r ist keine gültige ID — falle auf global zurück.", guild_id)
            except discord.Forbidden:
                logger.warning(
                    "Guild-Sync für %s nicht erlaubt (Missing Access). Lade den Bot mit "
                    "Scope 'applications.commands' neu ein. Falle vorerst auf globalen Sync zurück.",
                    guild_id,
                )

        synced = await self.tree.sync()
        logger.info("%d Command(s) global gesynct (Verteilung bis ~1h).", len(synced))

    async def close(self) -> None:
        self.db.close()
        await super().close()


bot = OakenTowerBot()


@bot.event
async def on_ready() -> None:
    logger.info("Eingeloggt als %s (ID: %s).", bot.user, bot.user.id if bot.user else "?")


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
) -> None:
    """Antwortet auf Command-Fehler dezent (ephemeral), statt zu crashen."""
    if isinstance(error, app_commands.MissingPermissions):
        message = "⛔ Dafür brauchst du die Berechtigung **Kanäle verwalten**."
    elif isinstance(error, app_commands.CommandOnCooldown):
        message = f"⏳ Zu schnell! Versuch's in {error.retry_after:.0f} s nochmal."
    else:
        logger.exception("Unerwarteter Fehler in einem Command: %s", error)
        message = "⚠️ Es ist ein Fehler aufgetreten."

    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        # Interaction ist evtl. schon abgelaufen/unbekannt (10062) — dann gibt es
        # nichts mehr zu antworten; kein Folge-Crash provozieren.
        pass


def main() -> None:
    token = os.environ.get(TOKEN_ENV)
    if not token:
        raise SystemExit(
            f"Umgebungsvariable {TOKEN_ENV} ist nicht gesetzt. "
            "Token setzen oder in einer .env-Datei hinterlegen."
        )
    try:
        bot.run(token, log_handler=None)
    except discord.errors.PrivilegedIntentsRequired:
        raise SystemExit(
            "FEHLER: Privilegierte Intents fehlen. Aktiviere im Discord Developer Portal "
            "(Bot → Privileged Gateway Intents) sowohl 'Message Content Intent' ALS AUCH "
            "'Server Members Intent' und starte den Bot neu. (Für Karten-Rewards fürs "
            "Spielen zusätzlich 'Presence Intent' + PRESENCE_INTENT=1.)"
        )


if __name__ == "__main__":
    main()

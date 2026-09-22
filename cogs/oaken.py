"""Auto-Delete von veralteten Oaken-Tower-Codes + 1v1-Rundenzählung.

Löscht in aktivierten Channels den alten Code eines Users, sobald derselbe User
einen neuen postet. Mit /oaken newgame startet eine Rundenzählung: Bei jedem Code
antwortet der Bot mit „Runde X — Code von @user". Eine Runde steigt erst, wenn
beide einen neuen Code gepostet haben. Beim Löschen eines alten Codes wird auch
die dazugehörige „Runde X"-Antwort des Bots mitgelöscht. Konfiguration in
config.json.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("oaken-tower-bot")

# Zusammenhängender Block aus mind. 200 Base64-Zeichen → schließt normale
# Nachrichten und kurze Strings sicher aus. re.search reicht.
DEFAULT_PATTERN: re.Pattern[str] = re.compile(r"[A-Za-z0-9+/=]{200,}")
CONFIG_FILE: str = os.path.join(os.environ.get("DATA_DIR", "."), "config.json")


class ConfigStore:
    """Channel-Konfiguration mit Persistenz in config.json."""

    def __init__(self, path: str = CONFIG_FILE) -> None:
        self.path = path
        self.data: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        if not os.path.exists(self.path):
            logger.info("Keine %s gefunden — starte mit leerer Konfiguration.", self.path)
            return
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Konnte %s nicht lesen (%s) — starte leer.", self.path, exc)
            return
        if not isinstance(raw, dict):
            logger.warning("%s hat unerwartetes Format — starte leer.", self.path)
            return

        cleaned: dict[str, dict] = {}
        for channel_id, entry in raw.items():
            if not isinstance(entry, dict):
                continue
            enabled = bool(entry.get("enabled", False))
            last_codes: dict[str, int] = {}
            raw_codes = entry.get("last_codes", {})
            if isinstance(raw_codes, dict):
                for user_id, message_id in raw_codes.items():
                    try:
                        last_codes[str(int(user_id))] = int(message_id)
                    except (TypeError, ValueError):
                        continue
            last_replies: dict[str, int] = {}
            raw_replies = entry.get("last_replies", {})
            if isinstance(raw_replies, dict):
                for user_id, message_id in raw_replies.items():
                    try:
                        last_replies[str(int(user_id))] = int(message_id)
                    except (TypeError, ValueError):
                        continue
            try:
                channel_key = str(int(channel_id))
            except (TypeError, ValueError):
                continue

            channel_entry: dict = {
                "enabled": enabled,
                "last_codes": last_codes,
                "last_replies": last_replies,
            }
            game = entry.get("game")
            if isinstance(game, dict):
                posted: list[int] = []
                for x in game.get("posted", []):
                    try:
                        posted.append(int(x))
                    except (TypeError, ValueError):
                        continue
                try:
                    round_no = int(game.get("round", 1))
                except (TypeError, ValueError):
                    round_no = 1
                channel_entry["game"] = {
                    "active": bool(game.get("active", False)),
                    "round": round_no,
                    "posted": posted,
                }
            cleaned[channel_key] = channel_entry

        self.data = cleaned
        logger.info("Auto-Delete-Konfiguration geladen: %d Channel(s).", len(self.data))

    def save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=2)
        except OSError as exc:
            logger.error("Konnte %s nicht schreiben: %s", self.path, exc)

    def _channel(self, channel_id: int) -> dict:
        key = str(channel_id)
        if key not in self.data:
            self.data[key] = {"enabled": False, "last_codes": {}, "last_replies": {}}
        # Ältere Einträge ohne last_replies nachrüsten.
        self.data[key].setdefault("last_replies", {})
        return self.data[key]

    def is_enabled(self, channel_id: int) -> bool:
        entry = self.data.get(str(channel_id))
        return bool(entry and entry.get("enabled"))

    def set_enabled(self, channel_id: int, enabled: bool) -> None:
        self._channel(channel_id)["enabled"] = enabled
        self.save()

    def get_last_code(self, channel_id: int, user_id: int) -> Optional[int]:
        entry = self.data.get(str(channel_id))
        if not entry:
            return None
        return entry["last_codes"].get(str(user_id))

    def set_last_code(self, channel_id: int, user_id: int, message_id: int) -> None:
        self._channel(channel_id)["last_codes"][str(user_id)] = message_id
        self.save()

    def get_last_reply(self, channel_id: int, user_id: int) -> Optional[int]:
        entry = self.data.get(str(channel_id))
        if not entry:
            return None
        return entry.get("last_replies", {}).get(str(user_id))

    def set_last_reply(self, channel_id: int, user_id: int, message_id: int) -> None:
        self._channel(channel_id)["last_replies"][str(user_id)] = message_id
        self.save()

    def clear_last_reply(self, channel_id: int, user_id: int) -> None:
        entry = self.data.get(str(channel_id))
        if entry:
            entry.get("last_replies", {}).pop(str(user_id), None)
            self.save()

    def reset_channel(self, channel_id: int) -> None:
        entry = self.data.get(str(channel_id))
        if entry:
            entry["last_codes"] = {}
            entry["last_replies"] = {}
            self.save()

    # --- 1v1-Spiel / Rundenzählung --------------------------------------------

    def start_game(self, channel_id: int) -> None:
        ch = self._channel(channel_id)
        ch["game"] = {"active": True, "round": 1, "posted": []}
        self.save()

    def stop_game(self, channel_id: int) -> None:
        entry = self.data.get(str(channel_id))
        if entry and "game" in entry:
            entry["game"]["active"] = False
            self.save()

    def get_game(self, channel_id: int) -> Optional[dict]:
        """Gibt den Spielstand zurück, aber nur wenn ein Spiel aktiv ist."""
        entry = self.data.get(str(channel_id))
        game = entry.get("game") if entry else None
        return game if (game and game.get("active")) else None

    def update_game(self, channel_id: int, round_no: int, posted: list[int]) -> None:
        ch = self._channel(channel_id)
        game = ch.get("game")
        if not game:
            ch["game"] = {"active": True, "round": round_no, "posted": posted}
        else:
            game["round"] = round_no
            game["posted"] = posted
            game["active"] = True
        self.save()


class OakenCog(commands.Cog):
    """Auto-Delete-Logik und /oaken-Befehle."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.config = ConfigStore()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Löscht ggf. den alten Code desselben Users im selben Channel."""
        if message.guild is None or message.author.bot:
            return
        if not self.config.is_enabled(message.channel.id):
            return
        if not message.content or not DEFAULT_PATTERN.search(message.content):
            return

        channel_id = message.channel.id
        author_id = message.author.id

        old_message_id = self.config.get_last_code(channel_id, author_id)
        if old_message_id is not None and old_message_id != message.id:
            try:
                old_message = await message.channel.fetch_message(old_message_id)
                await old_message.delete()
                logger.info(
                    "Alten Code von User %s in Channel %s gelöscht (Message %s).",
                    author_id, channel_id, old_message_id,
                )
            except discord.NotFound:
                logger.info("Alte Message %s nicht gefunden — überspringe.", old_message_id)
            except discord.Forbidden:
                logger.warning(
                    "Keine Berechtigung zum Löschen in Channel %s — Message %s bleibt.",
                    channel_id, old_message_id,
                )

            # Yamis zugehörige alte „Runde X"-Antwort ebenfalls löschen.
            old_reply_id = self.config.get_last_reply(channel_id, author_id)
            if old_reply_id is not None:
                try:
                    old_reply = await message.channel.fetch_message(old_reply_id)
                    await old_reply.delete()
                    logger.info(
                        "Alte Runden-Antwort für User %s in Channel %s gelöscht (Message %s).",
                        author_id, channel_id, old_reply_id,
                    )
                except discord.NotFound:
                    logger.info("Alte Antwort %s nicht gefunden — überspringe.", old_reply_id)
                except discord.Forbidden:
                    logger.warning(
                        "Keine Berechtigung zum Löschen der Antwort %s in Channel %s.",
                        old_reply_id, channel_id,
                    )
                self.config.clear_last_reply(channel_id, author_id)

        # Rundenzählung, falls ein Spiel läuft: eine Runde steigt erst, wenn
        # beide einen neuen Code gepostet haben (Austausch abgeschlossen).
        game = self.config.get_game(channel_id)
        if game is not None:
            round_no = int(game.get("round", 1))
            posted = list(game.get("posted", []))
            if len(posted) >= 2:
                round_no += 1
                posted = [author_id]
            elif author_id not in posted:
                posted.append(author_id)
            self.config.update_game(channel_id, round_no, posted)
            try:
                reply = await message.reply(
                    f"🎮 **Runde {round_no}** — Code von {message.author.mention}",
                    mention_author=False,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                self.config.set_last_reply(channel_id, author_id, reply.id)
            except discord.HTTPException:
                pass

        self.config.set_last_code(channel_id, author_id, message.id)

    # --- /oaken-Befehlsgruppe -------------------------------------------------

    oaken = app_commands.Group(
        name="oaken",
        description="Steuerung des Oaken-Tower Auto-Delete.",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @oaken.command(name="on", description="Aktiviert Auto-Delete im aktuellen Channel.")
    async def oaken_on(self, interaction: discord.Interaction) -> None:
        self.config.set_enabled(interaction.channel_id, True)
        logger.info("Auto-Delete aktiviert in Channel %s.", interaction.channel_id)
        await interaction.response.send_message(
            "✅ Auto-Delete ist in diesem Channel **aktiviert**.", ephemeral=True
        )

    @oaken.command(name="off", description="Deaktiviert Auto-Delete im aktuellen Channel.")
    async def oaken_off(self, interaction: discord.Interaction) -> None:
        self.config.set_enabled(interaction.channel_id, False)
        logger.info("Auto-Delete deaktiviert in Channel %s.", interaction.channel_id)
        await interaction.response.send_message(
            "🛑 Auto-Delete ist in diesem Channel **deaktiviert**.", ephemeral=True
        )

    @oaken.command(name="newgame", description="Startet ein neues Spiel mit Rundenzählung in diesem Channel.")
    async def oaken_newgame(self, interaction: discord.Interaction) -> None:
        self.config.set_enabled(interaction.channel_id, True)
        self.config.start_game(interaction.channel_id)
        logger.info("Neues Oaken-Spiel in Channel %s gestartet.", interaction.channel_id)
        await interaction.response.send_message(
            "🎮 **Neues Spiel gestartet!** Ab jetzt zähle ich die Runden mit — der nächste "
            "Code ist **Runde 1**. Eine Runde ist voll, sobald beide einen neuen Code gepostet "
            "haben. (Alte Codes werden weiterhin automatisch gelöscht.)"
        )

    @oaken.command(name="endgame", description="Beendet das laufende Spiel (Rundenzählung stoppt).")
    async def oaken_endgame(self, interaction: discord.Interaction) -> None:
        self.config.stop_game(interaction.channel_id)
        await interaction.response.send_message(
            "🏁 Spiel beendet — ich zähle keine Runden mehr (Auto-Delete läuft weiter).",
            ephemeral=True,
        )

    @oaken.command(name="status", description="Zeigt Auto-Delete- und Spielstatus dieses Channels.")
    async def oaken_status(self, interaction: discord.Interaction) -> None:
        enabled = self.config.is_enabled(interaction.channel_id)
        game = self.config.get_game(interaction.channel_id)
        lines = [
            "✅ Auto-Delete ist in diesem Channel **aktiv**."
            if enabled
            else "🛑 Auto-Delete ist in diesem Channel **inaktiv**."
        ]
        if game:
            lines.append(f"🎮 Spiel läuft — aktuelle **Runde {int(game.get('round', 1))}**.")
        else:
            lines.append("🎮 Kein Spiel aktiv — `/oaken newgame` zum Starten.")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @oaken.command(
        name="reset",
        description="Vergisst gespeicherte Code-Message-IDs (löscht nichts, nur Tracking).",
    )
    async def oaken_reset(self, interaction: discord.Interaction) -> None:
        self.config.reset_channel(interaction.channel_id)
        logger.info("Tracking zurückgesetzt in Channel %s.", interaction.channel_id)
        await interaction.response.send_message(
            "♻️ Gespeicherte Code-IDs in diesem Channel wurden vergessen. "
            "(Es wurde nichts gelöscht.)",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(OakenCog(bot))

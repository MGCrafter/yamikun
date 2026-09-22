"""Gambling-Spiele rund um die Coin-Währung.

Aktuell: /coinflip — auf Head oder Tail setzen. Bei richtigem Tipp wird der
Einsatz verdoppelt (netto +Einsatz), sonst ist der Einsatz weg. Die Coins sind
dieselben wie im Leveling-System.
"""

from __future__ import annotations

import asyncio
import logging
import random

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("oaken-tower-bot")

# --- Einstellbare Werte -------------------------------------------------------
MAX_BET: int = 10000
WIN_CHANCE: float = 0.48          # leichter House-Edge (< 0.5)
LUCK_WIN_CHANCE: float = 0.65     # mit aktivem Glücksbringer
SPIN_SECONDS: float = 2.5         # Dauer der Dreh-Animation

# Custom-Emoji-Namen (mit Fallbacks, falls eins fehlt)
EMOJI_SPIN = ("YamiCoinflip", "🪙")
EMOJI_HEAD = ("YamiToken", "🪙")
EMOJI_TAIL = ("YamiTail", "⚫")
EMOJI_COIN = ("YamiToken", "🪙")


class GamblingCog(commands.Cog):
    """Coinflip und (später) weitere Glücksspiele."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]

    def _emoji(self, guild: discord.Guild | None, spec: tuple[str, str]) -> str:
        """Löst ein Custom-Emoji per Name auf, sonst den Fallback."""
        name, fallback = spec
        if guild is not None:
            emoji = discord.utils.get(guild.emojis, name=name)
            if emoji is not None:
                return str(emoji)
        return fallback

    @staticmethod
    def _fmt(n: int) -> str:
        """Formatiert eine Zahl mit Tausenderpunkten (1.100)."""
        return f"{n:,}".replace(",", ".")

    @app_commands.command(
        name="coinflip",
        description="Setze Coins auf Head oder Tail. Triffst du, verdoppelt sich der Einsatz!",
    )
    @app_commands.guild_only()
    @app_commands.describe(seite="Worauf setzt du?", einsatz=f"Einsatz in Coins (1–{MAX_BET})")
    @app_commands.choices(
        seite=[
            app_commands.Choice(name="Head", value="head"),
            app_commands.Choice(name="Tail", value="tail"),
        ]
    )
    async def coinflip(
        self,
        interaction: discord.Interaction,
        seite: app_commands.Choice[str],
        einsatz: int,
    ) -> None:
        guild = interaction.guild
        coin = self._emoji(guild, EMOJI_COIN)

        # Einsatz prüfen
        if einsatz < 1 or einsatz > MAX_BET:
            await interaction.response.send_message(
                f"⚠️ Der Einsatz muss zwischen **1** und **{MAX_BET}** {coin} liegen.",
                ephemeral=True,
            )
            return

        row = self.db.get_user(guild.id, interaction.user.id)
        balance = int(row["coins"])
        # Einsatz atomar abbuchen (nur wenn das Guthaben reicht) – verhindert Races.
        if not self.db.spend_coins(guild.id, interaction.user.id, einsatz):
            await interaction.response.send_message(
                f"⚠️ Du hast nur **{balance}** {coin}, das reicht nicht für **{einsatz}**.",
                ephemeral=True,
            )
            return

        # Ergebnis bestimmen; bei Gewinn den doppelten Einsatz zurückzahlen.
        boosted = self.db.consume_charge(guild.id, interaction.user.id, "luck")
        win = random.random() < (LUCK_WIN_CHANCE if boosted else WIN_CHANCE)
        chosen = seite.value
        landed = chosen if win else ("tail" if chosen == "head" else "head")
        payout = einsatz * 2 if win else 0
        new_balance = self.db.add_coins(guild.id, interaction.user.id, payout)
        self.db.record_game(guild.id, interaction.user.id, "coinflip", "win" if win else "loss")

        author_name = interaction.user.display_name
        author_icon = interaction.user.display_avatar.url

        # Öffentliche Dreh-Animation (goldenes Embed) …
        spin = self._emoji(guild, EMOJI_SPIN)
        spinning = discord.Embed(
            title="🎰 Coinflip",
            color=0xF1C40F,
            description=(
                f"{spin} **{self._fmt(einsatz)}** {coin} auf **{seite.name}** … "
                "*die Münze dreht sich!*"
            ),
        )
        spinning.set_author(name=author_name, icon_url=author_icon)
        await interaction.response.send_message(embed=spinning)
        message = await interaction.original_response()
        await asyncio.sleep(SPIN_SECONDS)

        # … dann Ergebnis-Embed (grün = Gewinn, rot = Verlust).
        landed_emoji = self._emoji(guild, EMOJI_HEAD if landed == "head" else EMOJI_TAIL)
        side_label = "Head" if landed == "head" else "Tail"
        result = discord.Embed(
            title="🎰 Coinflip",
            color=0x2ECC71 if win else 0xE74C3C,
            description=f"{landed_emoji}  **{side_label}!**",
        )
        result.set_author(name=author_name, icon_url=author_icon)
        result.add_field(name="Einsatz", value=f"{self._fmt(einsatz)} {coin}", inline=True)
        result.add_field(
            name="Ergebnis",
            value=(f"🎉 +{self._fmt(einsatz)} {coin}" if win else f"💸 −{self._fmt(einsatz)} {coin}"),
            inline=True,
        )
        result.add_field(
            name="Neuer Kontostand", value=f"{self._fmt(new_balance)} {coin}", inline=False
        )
        if boosted:
            remaining = self.db.get_charges(guild.id, interaction.user.id, "luck")
            result.set_footer(text=f"🍀 Glücksbringer aktiv (noch {remaining})")

        try:
            await message.edit(embed=result)
        except discord.HTTPException:
            logger.warning("Konnte Coinflip-Ergebnis nicht editieren.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GamblingCog(bot))

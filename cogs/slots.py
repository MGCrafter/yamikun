"""Slot-Machine: 3 Walzen, nur drei gleiche Symbole zahlen (gestaffelt).

Jackpot-Symbol ist das :YamiToken:-Emoji des Servers. Einsatz/Coins teilen sich
mit dem übrigen Wirtschaftssystem.
"""

from __future__ import annotations

import asyncio
import logging
import random

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("oaken-tower-bot")

MAX_BET: int = 100000
COIN_EMOJI_NAME = "YamiToken"
COIN_FALLBACK = "🪙"
SPINNER = "🎰"
REEL_DELAY = 0.8  # Sekunden zwischen den stoppenden Walzen
LUCK_COPY = 0.40  # mit Glücksbringer: Chance, dass Walze 2/3 die erste kopiert
BASE_COPY = 0.05  # immer aktiv: leichter Kopier-Bias → Gewinnchance ~2,8 % → ~4,3 %

# Symbol-Key → Auszahlungs-Multiplikator (nur bei drei Gleichen).
PAYOUTS: dict[str, int] = {
    "token": 100,  # Jackpot (:YamiToken:)
    "diamond": 35,
    "star": 25,
    "bell": 15,
    "lemon": 10,
    "cherry": 10,
}
# Anzeige der Nicht-Jackpot-Symbole (token wird zur Laufzeit aufgelöst).
DISPLAY: dict[str, str] = {
    "diamond": "💎",
    "star": "⭐",
    "bell": "🔔",
    "lemon": "🍋",
    "cherry": "🍒",
}
SYMBOL_KEYS = list(PAYOUTS.keys())


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", ".")


class SlotsCog(commands.Cog):
    """/slots."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]

    def _coin(self, guild: discord.Guild | None) -> str:
        if guild is not None:
            emoji = discord.utils.get(guild.emojis, name=COIN_EMOJI_NAME)
            if emoji is not None:
                return str(emoji)
        return COIN_FALLBACK

    def _disp(self, guild: discord.Guild | None, key: str) -> str:
        """Anzeige-Emoji für ein Symbol (Jackpot = YamiToken)."""
        if key == "token":
            return self._coin(guild)
        return DISPLAY[key]

    def _reel_line(self, guild: discord.Guild | None, reels: list[str | None]) -> str:
        cells = [self._disp(guild, r) if r else SPINNER for r in reels]
        return f"┃ {cells[0]} ┃ {cells[1]} ┃ {cells[2]} ┃"

    @app_commands.command(name="slots", description="Drehe die Slot-Machine. Drei Gleiche gewinnen!")
    @app_commands.guild_only()
    @app_commands.describe(einsatz=f"Einsatz in Coins (1–{MAX_BET})")
    async def slots(
        self, interaction: discord.Interaction, einsatz: app_commands.Range[int, 1, MAX_BET]
    ) -> None:
        guild = interaction.guild
        coin = self._coin(guild)
        balance = int(self.db.get_user(guild.id, interaction.user.id)["coins"])
        # Einsatz atomar abbuchen (nur wenn das Guthaben reicht) – verhindert Races.
        if not self.db.spend_coins(guild.id, interaction.user.id, einsatz):
            await interaction.response.send_message(
                f"⚠️ Du hast nur **{_fmt(balance)}** {coin}, das reicht nicht für **{_fmt(einsatz)}**.",
                ephemeral=True,
            )
            return

        # Einsatz ist abgebucht – Ergebnis ziehen (ggf. mit Glücksbringer-Bias).
        boosted = self.db.consume_charge(guild.id, interaction.user.id, "luck")
        remaining = self.db.get_charges(guild.id, interaction.user.id, "luck")
        copy_chance = LUCK_COPY if boosted else BASE_COPY
        reels = [random.choice(SYMBOL_KEYS)]
        for _ in range(2):
            reels.append(
                reels[0] if random.random() < copy_chance else random.choice(SYMBOL_KEYS)
            )
        win = reels[0] == reels[1] == reels[2]
        mult = PAYOUTS[reels[0]] if win else 0
        payout = einsatz * mult
        new_balance = self.db.add_coins(guild.id, interaction.user.id, payout)
        self.db.record_game(guild.id, interaction.user.id, "slots", "win" if win else "loss")

        author_name = interaction.user.display_name
        author_icon = interaction.user.display_avatar.url

        def build(shown: int, final: bool = False) -> discord.Embed:
            partial: list[str | None] = [
                reels[i] if i < shown else None for i in range(3)
            ]
            color = 0xF1C40F
            if final:
                color = 0x2ECC71 if win else 0xE74C3C
            embed = discord.Embed(title="🎰 Slots", color=color)
            embed.set_author(name=author_name, icon_url=author_icon)
            embed.add_field(
                name=f"Einsatz: {_fmt(einsatz)} {coin}",
                value=f"## {self._reel_line(guild, partial)}",
                inline=False,
            )
            if final:
                if win:
                    sym = self._disp(guild, reels[0])
                    embed.description = (
                        f"🎉 **3× {sym}** — Gewinn **x{mult}**: **+{_fmt(payout - einsatz)}** {coin}!\n"
                        f"Kontostand: **{_fmt(new_balance)}** {coin}"
                    )
                else:
                    embed.description = (
                        f"Kein Gewinn. 💸 **−{_fmt(einsatz)}** {coin}\n"
                        f"Kontostand: **{_fmt(new_balance)}** {coin}"
                    )
            else:
                embed.description = "*Die Walzen drehen sich…*"
            if final and boosted:
                embed.set_footer(text=f"🍀 Glücksbringer aktiv (noch {remaining})")
            return embed

        # Gestaffelte Animation: erst alle drehen, dann Walze für Walze stoppen.
        await interaction.response.send_message(embed=build(0))
        message = await interaction.original_response()
        for shown in (1, 2):
            await asyncio.sleep(REEL_DELAY)
            await message.edit(embed=build(shown))
        await asyncio.sleep(REEL_DELAY)
        await message.edit(embed=build(3, final=True))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SlotsCog(bot))

"""Roulette: europäisches Rad (0–36, eine grüne Null).

Wettarten: Rot/Schwarz, Gerade/Ungerade, 1–18/19–36, Dutzende, Spalten und
Einzelzahl. Einsatz/Coins teilen sich mit dem übrigen Wirtschaftssystem.
Auszahlung = Einsatz × Multiplikator (even-money ×2, Dutzend/Spalte ×3,
Einzelzahl ×36). Die grüne 0 sorgt für den üblichen Hausvorteil (~2,7 %).
"""

from __future__ import annotations

import asyncio
import random

import discord
from discord import app_commands
from discord.ext import commands

MAX_BET: int = 100000
COIN_EMOJI_NAME = "YamiToken"
COIN_FALLBACK = "🪙"
REEL_DELAY = 0.8  # Sekunden zwischen den Animationsschritten

# Rote Zahlen auf dem europäischen Rad — alles andere (außer 0) ist schwarz.
RED: set[int] = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}

# art-Value → (Anzeige-Label, Auszahlungs-Multiplikator)
BETS: dict[str, tuple[str, int]] = {
    "rot": ("Rot", 2),
    "schwarz": ("Schwarz", 2),
    "gerade": ("Gerade", 2),
    "ungerade": ("Ungerade", 2),
    "tief": ("1–18", 2),
    "hoch": ("19–36", 2),
    "dutzend1": ("1. Dutzend (1–12)", 3),
    "dutzend2": ("2. Dutzend (13–24)", 3),
    "dutzend3": ("3. Dutzend (25–36)", 3),
    "spalte1": ("1. Spalte", 3),
    "spalte2": ("2. Spalte", 3),
    "spalte3": ("3. Spalte", 3),
    "zahl": ("Zahl", 36),
}


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _color_emoji(n: int) -> str:
    if n == 0:
        return "🟢"
    return "🔴" if n in RED else "⚫"


def _color_name(n: int) -> str:
    if n == 0:
        return "Grün"
    return "Rot" if n in RED else "Schwarz"


def _is_win(art: str, zahl: int | None, result: int) -> bool:
    """True, wenn die gezogene Zahl die Wette trifft (0 verliert alle Außenwetten)."""
    if art == "rot":
        return result in RED
    if art == "schwarz":
        return result != 0 and result not in RED
    if art == "gerade":
        return result != 0 and result % 2 == 0
    if art == "ungerade":
        return result % 2 == 1
    if art == "tief":
        return 1 <= result <= 18
    if art == "hoch":
        return 19 <= result <= 36
    if art == "dutzend1":
        return 1 <= result <= 12
    if art == "dutzend2":
        return 13 <= result <= 24
    if art == "dutzend3":
        return 25 <= result <= 36
    if art == "spalte1":
        return result != 0 and result % 3 == 1
    if art == "spalte2":
        return result != 0 and result % 3 == 2
    if art == "spalte3":
        return result != 0 and result % 3 == 0
    if art == "zahl":
        return zahl is not None and result == zahl
    return False


class RouletteCog(commands.Cog):
    """/roulette."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]

    def _coin(self, guild: discord.Guild | None) -> str:
        if guild is not None:
            emoji = discord.utils.get(guild.emojis, name=COIN_EMOJI_NAME)
            if emoji is not None:
                return str(emoji)
        return COIN_FALLBACK

    @staticmethod
    def _spin_strip() -> str:
        """Zufälliger Streifen rollender Zahlen für die Animation."""
        nums = [random.randint(0, 36) for _ in range(5)]
        return " · ".join(f"{_color_emoji(n)} {n}" for n in nums)

    @app_commands.command(
        name="roulette",
        description="Setze auf Rot/Schwarz, Zahlen, Dutzende … und dreh das Rad.",
    )
    @app_commands.guild_only()
    @app_commands.describe(
        einsatz=f"Einsatz in Coins (1–{MAX_BET})",
        art="Worauf wettest du?",
        zahl="Nur bei 'Einzelzahl': die Zahl 0–36",
    )
    @app_commands.choices(
        art=[
            app_commands.Choice(name="Rot (×2)", value="rot"),
            app_commands.Choice(name="Schwarz (×2)", value="schwarz"),
            app_commands.Choice(name="Gerade (×2)", value="gerade"),
            app_commands.Choice(name="Ungerade (×2)", value="ungerade"),
            app_commands.Choice(name="1–18 (×2)", value="tief"),
            app_commands.Choice(name="19–36 (×2)", value="hoch"),
            app_commands.Choice(name="1. Dutzend 1–12 (×3)", value="dutzend1"),
            app_commands.Choice(name="2. Dutzend 13–24 (×3)", value="dutzend2"),
            app_commands.Choice(name="3. Dutzend 25–36 (×3)", value="dutzend3"),
            app_commands.Choice(name="1. Spalte (×3)", value="spalte1"),
            app_commands.Choice(name="2. Spalte (×3)", value="spalte2"),
            app_commands.Choice(name="3. Spalte (×3)", value="spalte3"),
            app_commands.Choice(name="Einzelzahl — zahl angeben (×36)", value="zahl"),
        ]
    )
    async def roulette(
        self,
        interaction: discord.Interaction,
        einsatz: app_commands.Range[int, 1, MAX_BET],
        art: app_commands.Choice[str],
        zahl: app_commands.Range[int, 0, 36] | None = None,
    ) -> None:
        guild = interaction.guild
        coin = self._coin(guild)

        if art.value == "zahl" and zahl is None:
            await interaction.response.send_message(
                "⚠️ Bei **Einzelzahl** musst du auch eine Zahl (0–36) angeben.",
                ephemeral=True,
            )
            return

        balance = int(self.db.get_user(guild.id, interaction.user.id)["coins"])
        # Einsatz atomar abbuchen (nur wenn das Guthaben reicht) – verhindert Races.
        if not self.db.spend_coins(guild.id, interaction.user.id, einsatz):
            await interaction.response.send_message(
                f"⚠️ Du hast nur **{_fmt(balance)}** {coin}, das reicht nicht für **{_fmt(einsatz)}**.",
                ephemeral=True,
            )
            return

        label, mult = BETS[art.value]
        bet_label = f"Zahl {zahl}" if art.value == "zahl" else label

        # Einsatz ist abgebucht – Ergebnis ziehen und sofort abrechnen.
        result = random.randint(0, 36)
        win = _is_win(art.value, zahl, result)
        payout = einsatz * mult if win else 0
        new_balance = self.db.add_coins(guild.id, interaction.user.id, payout)
        self.db.record_game(guild.id, interaction.user.id, "roulette", "win" if win else "loss")

        author_name = interaction.user.display_name
        author_icon = interaction.user.display_avatar.url

        def build(strip: str, final: bool = False) -> discord.Embed:
            if final:
                col_e, col_n = _color_emoji(result), _color_name(result)
                color = 0x2ECC71 if win else 0xE74C3C
                embed = discord.Embed(title=f"🎡 Roulette — {col_e} {result} {col_n}", color=color)
                embed.add_field(
                    name=f"Einsatz: {_fmt(einsatz)} {coin} auf {bet_label}",
                    value=f"## ╭──────╮  {col_e} {result}  ╰──────╯",
                    inline=False,
                )
                if win:
                    embed.description = (
                        f"🎉 **Treffer!** Auszahlung **×{mult}** → **+{_fmt(payout - einsatz)}** {coin}\n"
                        f"Kontostand: **{_fmt(new_balance)}** {coin}"
                    )
                else:
                    embed.description = (
                        f"Kein Treffer. 💸 **−{_fmt(einsatz)}** {coin}\n"
                        f"Kontostand: **{_fmt(new_balance)}** {coin}"
                    )
            else:
                embed = discord.Embed(title="🎡 Roulette", color=0xF1C40F)
                embed.add_field(
                    name=f"Einsatz: {_fmt(einsatz)} {coin} auf {bet_label}",
                    value=f"## {strip}",
                    inline=False,
                )
                embed.description = "*Die Kugel rollt…*"
            embed.set_author(name=author_name, icon_url=author_icon)
            return embed

        # Animation: Kugel rollt (mehrere Edits), dann bleibt sie auf dem Ergebnis stehen.
        await interaction.response.send_message(embed=build(self._spin_strip()))
        message = await interaction.original_response()
        for _ in range(3):
            await asyncio.sleep(REEL_DELAY)
            await message.edit(embed=build(self._spin_strip()))
        await asyncio.sleep(REEL_DELAY)
        await message.edit(embed=build("", final=True))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RouletteCog(bot))

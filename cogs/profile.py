"""Profilseite (OwO-Style) und Bio-Verwaltung.

Zeigt Avatar, Level + XP-Fortschritt, Coins, Leaderboard-Platz, Coinflip-Statistik
und eine frei setzbare Bio.
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from cogs.leveling import level_from_total, xp_needed

COIN_EMOJI_NAME = "YamiToken"
COIN_FALLBACK = "🪙"
BIO_MAX_LEN = 200
BAR_LENGTH = 14


def _fmt(n: int) -> str:
    """Zahl mit Tausenderpunkten."""
    return f"{n:,}".replace(",", ".")


def _bar(fraction: float, length: int = BAR_LENGTH) -> str:
    """Text-Fortschrittsbalken aus █ und ░."""
    fraction = max(0.0, min(1.0, fraction))
    filled = round(fraction * length)
    return "█" * filled + "░" * (length - filled)


class ProfileCog(commands.Cog):
    """/profile und /setbio."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]

    def _coin(self, guild: discord.Guild | None) -> str:
        if guild is not None:
            emoji = discord.utils.get(guild.emojis, name=COIN_EMOJI_NAME)
            if emoji is not None:
                return str(emoji)
        return COIN_FALLBACK

    @app_commands.command(name="profile", description="Zeigt das Profil eines Users.")
    @app_commands.guild_only()
    @app_commands.describe(user="Wessen Profil? (Standard: du selbst)")
    async def profile(
        self, interaction: discord.Interaction, user: discord.Member | None = None
    ) -> None:
        target = user or interaction.user
        guild = interaction.guild
        coin = self._coin(guild)

        row = self.db.get_user(guild.id, target.id)
        total_xp = int(row["xp"])
        coins = int(row["coins"])
        level, into_level = level_from_total(total_xp)
        need = xp_needed(level)
        pos, total = self.db.rank_position(guild.id, target.id)
        bio = self.db.get_bio(guild.id, target.id)
        equipped_title = self.db.get_title(guild.id, target.id)
        spouses = self.db.list_marriages(guild.id, target.id)

        custom = self.db.get_profile_color(guild.id, target.id)
        if custom is not None:
            color = discord.Color(custom)
        elif target.color.value:
            color = target.color
        else:
            color = discord.Color(0x5865F2)
        desc = bio or "*Keine Bio gesetzt — `/setbio` zum Setzen.*"
        if equipped_title:
            desc = f"🏷️ **{equipped_title}**\n{desc}"
        embed = discord.Embed(
            title=f"Profil von {target.display_name}",
            color=color,
            description=desc,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Level", value=f"**{level}**", inline=True)
        embed.add_field(name="Rang", value=f"#{pos} / {total}", inline=True)
        embed.add_field(name="Coins", value=f"{_fmt(coins)} {coin}", inline=True)

        frac = into_level / need if need else 0
        embed.add_field(
            name="XP-Fortschritt",
            value=f"`{_bar(frac)}`\n{_fmt(into_level)} / {_fmt(need)} XP "
            f"(gesamt {_fmt(total_xp)})",
            inline=False,
        )

        def stat_line(g: int, w: int, l: int) -> str:
            if g == 0:
                return "Noch nicht gespielt."
            return f"{_fmt(g)} Spiele\n{w}W / {l}L · {w / g * 100:.0f}%"

        for game_title, key in (("🪙 Coinflip", "coinflip"), ("🃏 Blackjack", "blackjack"), ("🎰 Slots", "slots")):
            g, w, l = self.db.get_game_stats(guild.id, target.id, key)
            embed.add_field(name=game_title, value=stat_line(g, w, l), inline=True)

        if spouses:
            names = []
            for other_id, _ in spouses[:5]:
                member = interaction.guild.get_member(other_id)
                names.append(member.mention if member else f"<@{other_id}>")
            suffix = f" +{len(spouses) - 5} weitere" if len(spouses) > 5 else ""
            embed.add_field(name="💍 Verheiratet mit", value=", ".join(names) + suffix, inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="setbio", description="Setzt deine Profil-Bio.")
    @app_commands.guild_only()
    @app_commands.describe(text=f"Dein Bio-Text (max. {BIO_MAX_LEN} Zeichen, leer = löschen)")
    async def setbio(self, interaction: discord.Interaction, text: str) -> None:
        text = text.strip()
        if len(text) > BIO_MAX_LEN:
            await interaction.response.send_message(
                f"⚠️ Die Bio darf höchstens **{BIO_MAX_LEN}** Zeichen lang sein "
                f"(deine: {len(text)}).",
                ephemeral=True,
            )
            return
        self.db.set_bio(interaction.guild_id, interaction.user.id, text or None)
        if text:
            await interaction.response.send_message("✅ Bio gespeichert.", ephemeral=True)
        else:
            await interaction.response.send_message("✅ Bio gelöscht.", ephemeral=True)

    @app_commands.command(name="setcolor", description="Setzt deine Profil-Akzentfarbe (Hex, z.B. #FF8800).")
    @app_commands.guild_only()
    @app_commands.describe(farbe="Hex-Farbe wie #FF8800 – oder 'reset' für Standard")
    async def setcolor(self, interaction: discord.Interaction, farbe: str) -> None:
        raw = farbe.strip().lower()
        if raw in ("reset", "clear", "standard"):
            self.db.set_profile_color(interaction.guild_id, interaction.user.id, None)
            await interaction.response.send_message(
                "🎨 Profilfarbe zurückgesetzt (nutzt jetzt deine Rollenfarbe).", ephemeral=True
            )
            return
        hexval = raw.lstrip("#")
        if len(hexval) != 6 or any(c not in "0123456789abcdef" for c in hexval):
            await interaction.response.send_message(
                "⚠️ Ungültige Farbe. Gib einen Hex-Code wie `#FF8800` an (oder `reset`).",
                ephemeral=True,
            )
            return
        value = int(hexval, 16)
        self.db.set_profile_color(interaction.guild_id, interaction.user.id, value)
        embed = discord.Embed(
            description=f"🎨 Profilfarbe gesetzt auf **#{hexval.upper()}**. Schau dir dein `/profile` an!",
            color=value,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProfileCog(bot))

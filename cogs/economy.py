"""Economy-Befehle: tägliche Login-Belohnung (/daily) und Coin-Überweisung (/pay)."""

from __future__ import annotations

import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("oaken-tower-bot")

COIN_EMOJI_NAME = "YamiToken"
COIN_FALLBACK = "🪙"

DAILY_COOLDOWN = 24 * 3600       # frühestens nach 24 h wieder einlösbar
DAILY_RESET = 48 * 3600         # länger als 48 h kein Claim → Streak zurück auf 1
DAILY_PER_STREAK = 10           # Coins pro Streak-Tag
DAILY_CAP = 500                 # Deckel der Grundbelohnung
WEEK_BONUS = 100                # Extra alle 7 Streak-Tage


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", ".")


class EconomyCog(commands.Cog):
    """/daily und /pay."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]

    def _coin(self, guild: discord.Guild | None) -> str:
        if guild is not None:
            emoji = discord.utils.get(guild.emojis, name=COIN_EMOJI_NAME)
            if emoji is not None:
                return str(emoji)
        return COIN_FALLBACK

    @app_commands.command(name="daily", description="Hole deine tägliche Coin-Belohnung ab.")
    @app_commands.guild_only()
    async def daily(self, interaction: discord.Interaction) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        coin = self._coin(interaction.guild)
        now = time.time()
        last, streak = self.db.get_daily(gid, uid)

        # Schon innerhalb der letzten 24 h abgeholt?
        if last and (now - last) < DAILY_COOLDOWN:
            remaining = DAILY_COOLDOWN - (now - last)
            hrs, mins = int(remaining // 3600), int((remaining % 3600) // 60)
            await interaction.response.send_message(
                f"⏳ Du hast dein Daily schon abgeholt. Komm in **{hrs}h {mins}m** wieder.",
                ephemeral=True,
            )
            return

        # Streak fortführen oder zurücksetzen.
        streak = streak + 1 if last and (now - last) <= DAILY_RESET else 1
        base = min(DAILY_PER_STREAK * streak, DAILY_CAP)
        bonus = WEEK_BONUS if streak % 7 == 0 else 0
        reward = base + bonus

        self.db.set_daily(gid, uid, now, streak)
        new_balance = self.db.add_coins(gid, uid, reward)

        embed = discord.Embed(title="🎁 Daily Reward", color=0xF1C40F)
        embed.set_author(
            name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url
        )
        reward_text = f"+{_fmt(reward)} {coin}"
        if bonus:
            reward_text += f"\n🔥 inkl. +{WEEK_BONUS} Wochen-Bonus!"
        embed.add_field(name="Belohnung", value=reward_text, inline=True)
        embed.add_field(name="Streak", value=f"{streak} 🔥", inline=True)
        embed.add_field(name="Kontostand", value=f"{_fmt(new_balance)} {coin}", inline=True)
        days_to_bonus = (7 - streak % 7) % 7
        if days_to_bonus:
            embed.set_footer(text=f"Noch {days_to_bonus} Tag(e) bis zum nächsten Wochen-Bonus.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="pay", description="Überweise einem anderen Mitglied Coins.")
    @app_commands.guild_only()
    @app_commands.describe(user="Empfänger", betrag="Anzahl Coins")
    async def pay(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        betrag: app_commands.Range[int, 1, None],
    ) -> None:
        coin = self._coin(interaction.guild)
        if user.bot:
            await interaction.response.send_message(
                "⚠️ An Bots kannst du keine Coins schicken.", ephemeral=True
            )
            return
        if user.id == interaction.user.id:
            await interaction.response.send_message(
                "⚠️ Dir selbst kannst du keine Coins schicken.", ephemeral=True
            )
            return

        balance = int(self.db.get_user(interaction.guild_id, interaction.user.id)["coins"])
        if betrag > balance:
            await interaction.response.send_message(
                f"⚠️ Du hast nur **{_fmt(balance)}** {coin}, das reicht nicht für **{_fmt(betrag)}**.",
                ephemeral=True,
            )
            return

        self.db.add_coins(interaction.guild_id, interaction.user.id, -betrag)
        self.db.add_coins(interaction.guild_id, user.id, betrag)
        logger.info("Pay: %s → %s : %d", interaction.user.id, user.id, betrag)

        embed = discord.Embed(
            description=f"💸 {interaction.user.mention} → {user.mention}: **{_fmt(betrag)}** {coin}",
            color=0x2ECC71,
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EconomyCog(bot))

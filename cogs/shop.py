"""Shop: Coins gegen temporäre Boosts eintauschen.

Items (v1):
- 🍀 Glücksbringer (luck): erhöhte Gewinnchance für die nächsten Coinflip/Slots-Spiele.
- ⚡ XP-Boost (xp): doppelte XP (Nachrichten & Voice) für eine Stunde.

Effekt-Keys ("luck", "xpboost") werden von gambling/slots/leveling gelesen.
"""

from __future__ import annotations

import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("oaken-tower-bot")

COIN_EMOJI_NAME = "YamiToken"
COIN_FALLBACK = "🪙"

# Item-Parameter (zentral, leicht anpassbar)
LUCK_PRICE = 20000
LUCK_CHARGES = 5
XP_PRICE = 10000
XP_DURATION = 3600  # Sekunden (1 Stunde)


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", ".")


class ShopCog(commands.Cog):
    """/shop und /buy."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]

    def _coin(self, guild: discord.Guild | None) -> str:
        if guild is not None:
            emoji = discord.utils.get(guild.emojis, name=COIN_EMOJI_NAME)
            if emoji is not None:
                return str(emoji)
        return COIN_FALLBACK

    @app_commands.command(name="shop", description="Zeigt den Shop.")
    @app_commands.guild_only()
    async def shop(self, interaction: discord.Interaction) -> None:
        coin = self._coin(interaction.guild)
        embed = discord.Embed(
            title="🛒 Shop",
            color=0x9B59B6,
            description="Kaufe mit `/buy <item>`.",
        )
        embed.add_field(
            name=f"🍀 Glücksbringer — {_fmt(LUCK_PRICE)} {coin}",
            value=f"Erhöhte Gewinnchance für die nächsten **{LUCK_CHARGES}** Coinflip-/Slots-Spiele.\n`/buy item:Glücksbringer`",
            inline=False,
        )
        embed.add_field(
            name=f"⚡ XP-Boost — {_fmt(XP_PRICE)} {coin}",
            value=f"**Doppelte XP** (Nachrichten & Voice) für **{XP_DURATION // 60} Minuten**.\n`/buy item:XP-Boost`",
            inline=False,
        )
        from cogs.booster import PACKS  # lokal, um Import-Reihenfolge unkritisch zu halten

        packs_text = "\n".join(
            f"{p['emoji']} **{p['label']}** — {_fmt(p['price'])} {coin} ({p['cards']} Karten)"
            for p in PACKS.values()
        )
        embed.add_field(
            name="🎴 Booster-Packs",
            value=f"{packs_text}\nKaufen mit `/booster buy`, öffnen mit `/booster open`.",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="buy", description="Kaufe ein Item aus dem Shop.")
    @app_commands.guild_only()
    @app_commands.describe(item="Was möchtest du kaufen?")
    @app_commands.choices(
        item=[
            app_commands.Choice(name="Glücksbringer", value="luck"),
            app_commands.Choice(name="XP-Boost", value="xp"),
        ]
    )
    async def buy(
        self, interaction: discord.Interaction, item: app_commands.Choice[str]
    ) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        coin = self._coin(interaction.guild)
        price = LUCK_PRICE if item.value == "luck" else XP_PRICE

        balance = int(self.db.get_user(gid, uid)["coins"])
        if balance < price:
            await interaction.response.send_message(
                f"⚠️ Du hast nur **{_fmt(balance)}** {coin}, brauchst aber **{_fmt(price)}**.",
                ephemeral=True,
            )
            return

        self.db.add_coins(gid, uid, -price)
        if item.value == "luck":
            self.db.add_charges(gid, uid, "luck", LUCK_CHARGES)
            total = self.db.get_charges(gid, uid, "luck")
            detail = (
                f"🍀 **Glücksbringer** aktiviert — erhöhte Gewinnchance für "
                f"**{LUCK_CHARGES}** Spiele (insgesamt **{total}** geladen)."
            )
        else:
            new_exp = self.db.extend_expires(gid, uid, "xpboost", time.time(), XP_DURATION)
            detail = (
                f"⚡ **XP-Boost** aktiviert — doppelte XP bis "
                f"<t:{int(new_exp)}:t> (<t:{int(new_exp)}:R>)."
            )

        new_balance = self.db.add_coins(gid, uid, 0)
        embed = discord.Embed(title="✅ Gekauft", color=0x2ECC71, description=detail)
        embed.set_footer(text=f"Neuer Kontostand: {_fmt(new_balance)}")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ShopCog(bot))

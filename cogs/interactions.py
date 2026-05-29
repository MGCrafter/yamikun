"""Soziale Interactions mit GIFs (nekos.best) + Zähler + Freundschafts-XP.

Jede Interaction mit einer anderen Person erhöht den persönlichen Zähler und gibt
Freundschafts-XP für das Paar (siehe cogs/social.py).
"""

from __future__ import annotations

import logging
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("oaken-tower-bot")

NEKOS_URL = "https://nekos.best/api/v2/{}"
FRIEND_XP = 10  # Freundschafts-XP pro Interaction

# action → Satzbaustein, Emoji, Embed-Farbe
ACTIONS: dict[str, dict] = {
    "hug": {"verb": "umarmt", "emoji": "🤗", "color": 0xF8A5C2},
    "pat": {"verb": "tätschelt den Kopf von", "emoji": "🫶", "color": 0xFAD390},
    "kiss": {"verb": "küsst", "emoji": "😘", "color": 0xEB2F06},
    "slap": {"verb": "slappt", "emoji": "👋", "color": 0xE55039},
    "highfive": {"verb": "gibt ein High-Five an", "emoji": "🙌", "color": 0x60A3BC},
}


class InteractionsCog(commands.Cog):
    """/hug, /pat, /kiss, /slap, /highfive."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]
        self.session: Optional[aiohttp.ClientSession] = None

    async def cog_load(self) -> None:
        self.session = aiohttp.ClientSession()

    async def cog_unload(self) -> None:
        if self.session:
            await self.session.close()

    async def _fetch_gif(self, action: str) -> Optional[str]:
        if self.session is None:
            return None
        try:
            async with self.session.get(
                NEKOS_URL.format(action), timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data["results"][0]["url"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("nekos.best-Abruf fehlgeschlagen (%s): %s", action, exc)
            return None

    async def _do(self, interaction: discord.Interaction, target: discord.Member, action: str) -> None:
        cfg = ACTIONS[action]
        if target.bot:
            await interaction.response.send_message(
                "⚠️ Mit Bots funktioniert das nicht.", ephemeral=True
            )
            return

        gif = await self._fetch_gif(action)

        if target.id == interaction.user.id:
            embed = discord.Embed(
                description=f"{interaction.user.mention} {cfg['verb']} sich selbst… {cfg['emoji']}",
                color=cfg["color"],
            )
            if gif:
                embed.set_image(url=gif)
            await interaction.response.send_message(embed=embed)
            return

        count = self.db.add_interaction(interaction.guild_id, interaction.user.id, target.id, action)
        self.db.add_friend_xp(interaction.guild_id, interaction.user.id, target.id, FRIEND_XP)

        embed = discord.Embed(
            description=f"{interaction.user.mention} {cfg['verb']} {target.mention}! {cfg['emoji']}",
            color=cfg["color"],
        )
        if gif:
            embed.set_image(url=gif)
        embed.set_footer(text=f"Schon {count}× · +{FRIEND_XP} Freundschafts-XP")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="hug", description="Umarme jemanden.")
    @app_commands.guild_only()
    @app_commands.describe(user="Wen möchtest du umarmen?")
    async def hug(self, interaction: discord.Interaction, user: discord.Member) -> None:
        await self._do(interaction, user, "hug")

    @app_commands.command(name="pat", description="Tätschle jemandem den Kopf.")
    @app_commands.guild_only()
    @app_commands.describe(user="Wen?")
    async def pat(self, interaction: discord.Interaction, user: discord.Member) -> None:
        await self._do(interaction, user, "pat")

    @app_commands.command(name="kiss", description="Küsse jemanden.")
    @app_commands.guild_only()
    @app_commands.describe(user="Wen?")
    async def kiss(self, interaction: discord.Interaction, user: discord.Member) -> None:
        await self._do(interaction, user, "kiss")

    @app_commands.command(name="slap", description="Verpasse jemandem eine (spaßige) Ohrfeige.")
    @app_commands.guild_only()
    @app_commands.describe(user="Wen?")
    async def slap(self, interaction: discord.Interaction, user: discord.Member) -> None:
        await self._do(interaction, user, "slap")

    @app_commands.command(name="highfive", description="Gib jemandem ein High-Five.")
    @app_commands.guild_only()
    @app_commands.describe(user="Wem?")
    async def highfive(self, interaction: discord.Interaction, user: discord.Member) -> None:
        await self._do(interaction, user, "highfive")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(InteractionsCog(bot))

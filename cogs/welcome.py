"""Willkommensnachrichten, wenn jemand dem Server beitritt.

Konfiguriert ausschließlich über das Webpanel (an/aus, Channel, Text). Der Text
unterstützt Platzhalter:
  {user}       — Erwähnung (@Name)
  {user_name}  — Anzeigename
  {server}     — Servername
  {count}      — Mitgliederzahl

Benötigt den Server-Members-Intent (in bot.py aktiviert).
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

logger = logging.getLogger("oaken-tower-bot")

DEFAULT_WELCOME = "Willkommen {user} auf **{server}**! 🎉 Du bist unser {count}. Mitglied."


def render_welcome(template: str | None, member: discord.Member) -> str:
    """Platzhalter ersetzen — bewusst per replace (kein str.format), damit
    fremde geschweifte Klammern im Text keine Exceptions auslösen."""
    text = template or DEFAULT_WELCOME
    repl = {
        "{user}": member.mention,
        "{user_name}": member.display_name,
        "{server}": member.guild.name,
        "{count}": str(member.guild.member_count or "?"),
    }
    for key, value in repl.items():
        text = text.replace(key, value)
    return text


class WelcomeCog(commands.Cog):
    """Begrüßt neue Mitglieder im konfigurierten Channel."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        cfg = self.db.get_welcome(member.guild.id)
        if not cfg["enabled"] or not cfg["channel_id"]:
            return
        channel = member.guild.get_channel(cfg["channel_id"])
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        embed = discord.Embed(
            description=render_welcome(cfg["message"], member), color=0x7C3AED
        )
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        embed.set_thumbnail(url=member.display_avatar.url)
        if cfg.get("image"):
            embed.set_image(url=cfg["image"])  # Banner/Welcome-Bild
        try:
            await channel.send(
                member.mention, embed=embed,
                allowed_mentions=discord.AllowedMentions(users=True, everyone=False, roles=False),
            )
        except discord.Forbidden:
            logger.warning("Welcome: keine Schreibrechte in Channel %s (Guild %s).",
                           channel.id, member.guild.id)
        except discord.HTTPException:
            logger.exception("Welcome: Senden fehlgeschlagen.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WelcomeCog(bot))

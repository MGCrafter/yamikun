"""Boost-Benachrichtigungen, wenn ein Mitglied den Server boosted.

Konfiguriert ausschließlich über das Webpanel (an/aus, Channel, Text,
Erwähnung, Bild/GIF). Der Text unterstützt Platzhalter:
  {user}         — Erwähnung (@Name)
  {username}     — Discord-Nutzername
  {displayName}  — Anzeigename auf dem Server
  {server}       — Servername
  {boostCount}   — aktuelle Boost-Anzahl des Servers

Benötigt den Server-Members-Intent (in bot.py aktiviert).

Boost-Erkennung: on_member_update feuert, sobald premium_since von None
auf einen Timestamp wechselt (= Mitglied boosted erstmals oder erneut nach
einer Pause). Wichtig: Discord sendet dieses Event nur, wenn der Bot über
den Members-Intent verfügt (privilegierter Intent, muss im Developer Portal
aktiviert sein).
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

logger = logging.getLogger("oaken-tower-bot")

DEFAULT_BOOST = "Danke {user} fürs Boosten von {server}! 💜 Wir haben jetzt {boostCount} Boosts!"


def render_boost(template: str | None, member: discord.Member) -> str:
    """Platzhalter ersetzen — bewusst per replace (kein str.format), damit
    fremde geschweifte Klammern im Text keine Exceptions auslösen."""
    text = template or DEFAULT_BOOST
    repl = {
        "{user}": member.mention,
        "{username}": member.name,
        "{displayName}": member.display_name,
        "{server}": member.guild.name,
        "{boostCount}": str(member.guild.premium_subscription_count or 0),
    }
    for key, value in repl.items():
        text = text.replace(key, value)
    return text


class BoostNotifyCog(commands.Cog):
    """Postet eine konfigurierbare Nachricht, wenn jemand den Server boosted."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        # Nur feuern, wenn premium_since von None auf einen Wert wechselt.
        # Das ist das einzige zuverlässige Einzelmitglied-Boost-Start-Signal.
        # Re-Boosts nach einer Pause werden bewusst als neuer Boost gewertet.
        if after.bot:
            return
        if not (before.premium_since is None and after.premium_since is not None):
            return

        cfg = self.db.get_boost(after.guild.id)
        if not cfg["enabled"] or not cfg["channel_id"]:
            return

        channel = after.guild.get_channel(cfg["channel_id"])
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            logger.warning(
                "BoostNotify: Channel %s nicht gefunden oder kein TextChannel (Guild %s).",
                cfg["channel_id"], after.guild.id,
            )
            return

        # Berechtigungen prüfen, bevor gesendet wird.
        me = after.guild.me
        if me is None:
            # Bot-Member (noch) nicht im Cache — Permissions nicht prüfbar.
            return
        perms = channel.permissions_for(me)
        if not perms.send_messages:
            logger.warning(
                "BoostNotify: Keine Schreibrechte in Channel %s (Guild %s).",
                channel.id, after.guild.id,
            )
            return
        if cfg.get("image") and not (perms.attach_files or perms.embed_links):
            logger.warning(
                "BoostNotify: Kein attach_files/embed_links für Bild in Channel %s (Guild %s).",
                channel.id, after.guild.id,
            )
            # Nachricht trotzdem senden — nur Bild fehlt.

        embed = discord.Embed(
            description=render_boost(cfg["message"], after),
            color=0x7C3AED,
        )
        embed.set_author(name=after.display_name, icon_url=after.display_avatar.url)
        if cfg.get("image"):
            embed.set_image(url=cfg["image"])

        content = after.mention if cfg["mention"] else None
        allowed = discord.AllowedMentions(users=True, everyone=False, roles=False)

        try:
            await channel.send(
                content,
                embed=embed,
                allowed_mentions=allowed if content else discord.AllowedMentions.none(),
            )
        except discord.Forbidden:
            logger.warning(
                "BoostNotify: Forbidden — keine Schreibrechte in Channel %s (Guild %s).",
                channel.id, after.guild.id,
            )
        except discord.HTTPException:
            logger.exception("BoostNotify: Senden fehlgeschlagen.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BoostNotifyCog(bot))

"""Auto-Rollen: neue Mitglieder erhalten beim Beitritt automatisch konfigurierte Rollen.

Konfiguriert ausschließlich über das Webpanel (an/aus, Rollen-Auswahl). Es werden
nur Rollen vergeben, die unterhalb der höchsten Bot-Rolle liegen und nicht per
Integration verwaltet werden. Fehlt dem Bot die Berechtigung 'Rollen verwalten',
wird eine Warnung geloggt und kein Fehler ausgelöst.
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

logger = logging.getLogger("oaken-tower-bot")


class AutoRolesCog(commands.Cog):
    """Vergibt Auto-Rollen an neue Mitglieder."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        # Bots erhalten keine Auto-Rollen.
        if member.bot:
            return

        cfg = self.db.get_autoroles(member.guild.id)
        if not cfg["enabled"] or not cfg["role_ids"]:
            return

        # Bot-Member evtl. noch nicht im Cache (z. B. unter Last beim Start).
        me = member.guild.me
        if me is None:
            logger.warning(
                "AutoRoles: guild.me ist None auf Guild %s — übersprungen.",
                member.guild.id,
            )
            return

        # Berechtigungs-Check: 'Rollen verwalten' zwingend erforderlich.
        if not me.guild_permissions.manage_roles:
            logger.warning(
                "AutoRoles: Bot hat keine 'Rollen verwalten'-Berechtigung auf Guild %s — übersprungen.",
                member.guild.id,
            )
            return

        top_role = me.top_role
        assignable: list[discord.Role] = []

        for rid in cfg["role_ids"]:
            role = member.guild.get_role(rid)
            if role is None:
                # Rolle existiert nicht mehr (z. B. gelöscht).
                continue
            if role >= top_role:
                # Hierarchie-Problem: Bot-Rolle ist nicht hoch genug.
                logger.debug(
                    "AutoRoles: Rolle %s (%s) liegt über/gleich der Bot-Rolle — Guild %s, übersprungen.",
                    role.name, role.id, member.guild.id,
                )
                continue
            if role.managed:
                # Bot-verwaltete Rollen (z. B. Integrationen) nicht anfassen.
                logger.debug(
                    "AutoRoles: Rolle %s (%s) ist managed — Guild %s, übersprungen.",
                    role.name, role.id, member.guild.id,
                )
                continue
            assignable.append(role)

        if not assignable:
            return

        try:
            await member.add_roles(*assignable, reason="Auto Role")
        except discord.Forbidden:
            logger.warning(
                "AutoRoles: Forbidden beim Vergeben der Rollen an %s (Guild %s).",
                member.id, member.guild.id,
            )
        except discord.HTTPException:
            logger.exception(
                "AutoRoles: HTTPException beim Vergeben der Rollen an %s (Guild %s).",
                member.id, member.guild.id,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutoRolesCog(bot))

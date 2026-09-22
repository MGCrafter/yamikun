"""Server-Audit-Log — protokolliert Ereignisse in die DB und (optional) live in
einen Channel. Jede Kategorie ist im Webpanel einzeln ein-/ausschaltbar.

Kategorien:
  messages  — Nachrichten gelöscht/bearbeitet
  voice     — Voice betreten/verlassen/gewechselt
  members   — Join/Leave/Ban/Unban
  roles     — Rollen vergeben/entfernt, Nickname-Änderungen, Rollen erstellt/gelöscht
  channels  — Channels erstellt/gelöscht

Benötigt Members- & Message-Content-Intent (in bot.py aktiviert).
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

logger = logging.getLogger("oaken-tower-bot")

# Kategorie-Key -> (Anzeigename, Embed-Farbe)
CATEGORIES: dict[str, tuple[str, int]] = {
    "messages": ("Nachrichten", 0x5865F2),
    "voice": ("Voice", 0x2ECC71),
    "members": ("Mitglieder", 0x3498DB),
    "roles": ("Rollen & Nicknames", 0xF1C40F),
    "channels": ("Channels", 0x9B59B6),
}

MAX_CONTENT = 900  # Inhalt im Log kürzen


def _clip(text: str | None) -> str | None:
    if not text:
        return None
    return text if len(text) <= MAX_CONTENT else text[:MAX_CONTENT] + " …"


class AuditCog(commands.Cog):
    """Schreibt Audit-Einträge in die DB und postet sie optional in einen Channel."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]

    async def _log(
        self, guild: discord.Guild, category: str, event_type: str, summary: str,
        *, actor: discord.abc.User | None = None, target: discord.abc.User | None = None,
        channel: discord.abc.GuildChannel | None = None, detail: str | None = None,
    ) -> None:
        if guild is None or not self.db.is_audit_enabled(guild.id, category):
            return
        self.db.add_audit_log(
            guild.id, category, event_type, summary,
            actor_id=actor.id if actor else None,
            target_id=target.id if target else None,
            channel_id=channel.id if channel else None,
            detail=detail,
        )
        chan_id = self.db.get_audit_channel(guild.id)
        if not chan_id:
            return
        ch = guild.get_channel(chan_id)
        if not isinstance(ch, (discord.TextChannel, discord.Thread)):
            return
        label, color = CATEGORIES.get(category, (category, 0x95A5A6))
        embed = discord.Embed(description=summary, color=color, timestamp=discord.utils.utcnow())
        embed.set_author(name=label)
        if detail:
            embed.add_field(name="Details", value=_clip(detail) or "—", inline=False)
        try:
            await ch.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Audit: konnte nicht in Channel %s posten.", chan_id)

    async def log(
        self, guild: discord.Guild, category: str, event_type: str, summary: str,
        *, actor: discord.abc.User | None = None, target: discord.abc.User | None = None,
        channel: discord.abc.GuildChannel | None = None, detail: str | None = None,
    ) -> None:
        """Öffentliche Schnittstelle für Cogs: DB-Eintrag plus Live-Channel-Embed."""
        await self._log(
            guild,
            category,
            event_type,
            summary,
            actor=actor,
            target=target,
            channel=channel,
            detail=detail,
        )

    # --- Nachrichten ----------------------------------------------------------

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        await self._log(
            message.guild, "messages", "message_delete",
            f"🗑️ Nachricht von **{message.author}** in {message.channel.mention} gelöscht",
            actor=message.author, channel=message.channel, detail=_clip(message.content),
        )

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if before.guild is None or before.author.bot or before.content == after.content:
            return
        detail = f"Vorher: {before.content or '—'}\nNachher: {after.content or '—'}"
        await self._log(
            before.guild, "messages", "message_edit",
            f"✏️ Nachricht von **{before.author}** in {before.channel.mention} bearbeitet",
            actor=before.author, channel=before.channel, detail=_clip(detail),
        )

    # --- Voice ----------------------------------------------------------------

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        if member.guild is None:
            return
        if before.channel is None and after.channel is not None:
            await self._log(member.guild, "voice", "voice_join",
                            f"🔊 **{member}** hat Voice **{after.channel.name}** betreten", actor=member)
        elif before.channel is not None and after.channel is None:
            await self._log(member.guild, "voice", "voice_leave",
                            f"🔇 **{member}** hat Voice **{before.channel.name}** verlassen", actor=member)
        elif before.channel and after.channel and before.channel.id != after.channel.id:
            await self._log(
                member.guild, "voice", "voice_move",
                f"↔️ **{member}** wechselte Voice: **{before.channel.name}** → **{after.channel.name}**",
                actor=member,
            )

    # --- Mitglieder -----------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        await self._log(member.guild, "members", "member_join",
                        f"📥 **{member}** ist dem Server beigetreten", target=member)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        await self._log(member.guild, "members", "member_leave",
                        f"📤 **{member}** hat den Server verlassen", target=member)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.abc.User) -> None:
        await self._log(guild, "members", "member_ban", f"🔨 **{user}** wurde gebannt", target=user)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.abc.User) -> None:
        await self._log(guild, "members", "member_unban", f"♻️ **{user}** wurde entbannt", target=user)

    # --- Rollen & Nicknames ---------------------------------------------------

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        added = [r for r in after.roles if r not in before.roles]
        removed = [r for r in before.roles if r not in after.roles]
        if added:
            names = ", ".join(r.name for r in added)
            await self._log(after.guild, "roles", "role_grant",
                            f"➕ **{after}** erhielt Rolle(n): {names}", target=after)
        if removed:
            names = ", ".join(r.name for r in removed)
            await self._log(after.guild, "roles", "role_remove",
                            f"➖ **{after}** verlor Rolle(n): {names}", target=after)
        if before.nick != after.nick:
            await self._log(
                after.guild, "roles", "nick_change",
                f"🏷️ **{after}** Nickname: {before.nick or '—'} → {after.nick or '—'}", target=after,
            )

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        await self._log(role.guild, "roles", "role_create", f"🆕 Rolle erstellt: **{role.name}**")

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        await self._log(role.guild, "roles", "role_delete", f"❌ Rolle gelöscht: **{role.name}**")

    # --- Channels -------------------------------------------------------------

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        await self._log(channel.guild, "channels", "channel_create",
                        f"🆕 Channel erstellt: **{channel.name}**", channel=channel)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        await self._log(channel.guild, "channels", "channel_delete",
                        f"❌ Channel gelöscht: **{channel.name}**")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AuditCog(bot))

"""Reaction Roles — Mitglieder vergeben sich Rollen per Reaktion.

- Bindungen (Nachricht + Emoji → Rolle) liegen in der DB (Tabelle reaction_roles).
- Verwaltbar per Slash-Command (/reactionrole add|remove|list) UND über das
  Webpanel (ruft bind()/unbind() dieses Cogs auf).
- Beim Reagieren/Entreagieren vergibt bzw. entfernt der Bot die Rolle.

Emoji-Speicherung: Unicode-Emoji direkt ("🎮"); Server-Emojis als "name:id".
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("oaken-tower-bot")


def emoji_key(emoji: discord.PartialEmoji | discord.Emoji | str) -> str:
    """Einheitlicher DB-Schlüssel für ein Emoji (Unicode-Char oder 'name:id')."""
    if isinstance(emoji, str):
        emoji = discord.PartialEmoji.from_str(emoji)
    if getattr(emoji, "id", None):
        return f"{emoji.name}:{emoji.id}"
    return emoji.name or ""


class ReactionRolesCog(commands.Cog):
    """Selbstvergabe von Rollen per Reaktion."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]

    # --- Gemeinsame Logik (auch vom Webpanel genutzt) -------------------------

    async def bind(
        self,
        guild: discord.Guild,
        channel_id: int,
        message_id: int,
        emoji: str,
        role_id: int,
        required_role_id: int | None = None,
    ) -> str:
        """Bindung anlegen: Reaktion an die Nachricht hängen + in DB speichern.

        ``required_role_id`` (optional): nur Mitglieder mit dieser Rolle bekommen
        die Reaction Role; ohne sie wird die Reaktion wieder entfernt.

        Gibt den gespeicherten Emoji-Key zurück. Wirft bei Problemen Exceptions
        (z.B. NotFound/Forbidden), die der Aufrufer behandeln muss.
        """
        pe = discord.PartialEmoji.from_str(emoji)
        key = emoji_key(pe)
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            raise ValueError("channel")
        message = await channel.fetch_message(message_id)
        await message.add_reaction(pe)
        self.db.add_reaction_role(guild.id, channel_id, message_id, key, role_id, required_role_id)
        return key

    def unbind(self, guild_id: int, message_id: int, emoji: str) -> bool:
        return self.db.remove_reaction_role(guild_id, message_id, emoji_key(emoji))

    # --- Listener -------------------------------------------------------------

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id is None or (self.bot.user and payload.user_id == self.bot.user.id):
            return
        binding = self.db.get_reaction_role(
            payload.guild_id, payload.message_id, emoji_key(payload.emoji)
        )
        if not binding:
            return
        role_id, required_role_id = binding
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        role = guild.get_role(role_id)
        member = payload.member or guild.get_member(payload.user_id)
        if role is None or member is None or member.bot:
            return
        # Optionale Voraussetzungs-Rolle: fehlt sie, vergeben wir nichts und
        # nehmen die Reaktion des Mitglieds wieder weg (klares Feedback).
        if required_role_id is not None and not member.get_role(required_role_id):
            await self._remove_member_reaction(payload, guild, member)
            return
        try:
            await member.add_roles(role, reason="Reaction Role")
        except discord.Forbidden:
            logger.warning("Reaction Role: keine Berechtigung, %s in %s zu vergeben.", role.id, guild.id)
        except discord.HTTPException:
            logger.exception("Reaction Role: Vergeben fehlgeschlagen.")

    async def _remove_member_reaction(
        self,
        payload: discord.RawReactionActionEvent,
        guild: discord.Guild,
        member: discord.Member,
    ) -> None:
        """Entfernt die Reaktion eines Mitglieds (z.B. wenn die Voraussetzung fehlt)."""
        channel = guild.get_channel(payload.channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            return
        try:
            message = await channel.fetch_message(payload.message_id)
            await message.remove_reaction(payload.emoji, member)
        except discord.Forbidden:
            logger.warning(
                "Reaction Role: keine Berechtigung, Reaktion in %s zu entfernen.", guild.id
            )
        except discord.HTTPException:
            logger.debug("Reaction Role: Reaktion entfernen fehlgeschlagen.", exc_info=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id is None:
            return
        binding = self.db.get_reaction_role(
            payload.guild_id, payload.message_id, emoji_key(payload.emoji)
        )
        if not binding:
            return
        role_id, _ = binding
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        role = guild.get_role(role_id)
        member = guild.get_member(payload.user_id)
        if member is None:
            try:
                member = await guild.fetch_member(payload.user_id)
            except discord.HTTPException:
                return
        if role is None or member.bot:
            return
        try:
            await member.remove_roles(role, reason="Reaction Role entfernt")
        except discord.Forbidden:
            logger.warning("Reaction Role: keine Berechtigung, %s in %s zu entfernen.", role.id, guild.id)
        except discord.HTTPException:
            logger.exception("Reaction Role: Entfernen fehlgeschlagen.")

    # --- Slash-Commands -------------------------------------------------------

    group = app_commands.Group(
        name="reactionrole",
        description="Reaction Roles verwalten (Nachricht + Emoji → Rolle).",
        guild_only=True,
        default_permissions=discord.Permissions(manage_roles=True),
    )

    @group.command(name="add", description="Bindet ein Emoji an einer Nachricht an eine Rolle.")
    @app_commands.describe(
        message_id="ID der Nachricht (Entwicklermodus → Rechtsklick → ID kopieren)",
        emoji="Emoji (Standard-Emoji oder Server-Emoji)",
        role="Rolle, die vergeben werden soll",
        channel="Channel der Nachricht (Standard: aktueller)",
        required_role="Optional: nur Mitglieder mit dieser Rolle bekommen die Reaction Role",
    )
    async def rr_add(
        self,
        interaction: discord.Interaction,
        message_id: str,
        emoji: str,
        role: discord.Role,
        channel: discord.TextChannel | None = None,
        required_role: discord.Role | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        target = channel or interaction.channel
        if not message_id.isdigit():
            await interaction.followup.send("⚠️ Ungültige Nachrichten-ID.", ephemeral=True)
            return
        if role >= interaction.guild.me.top_role:  # type: ignore[union-attr]
            await interaction.followup.send(
                "⚠️ Diese Rolle steht über meiner höchsten Rolle — ich kann sie nicht vergeben. "
                "Zieh meine Bot-Rolle höher.",
                ephemeral=True,
            )
            return
        try:
            await self.bind(
                interaction.guild,  # type: ignore[arg-type]
                target.id,  # type: ignore[union-attr]
                int(message_id),
                emoji,
                role.id,
                required_role.id if required_role else None,
            )
        except (discord.NotFound, ValueError):
            await interaction.followup.send(
                "⚠️ Nachricht nicht gefunden — stimmt die ID und der Channel?", ephemeral=True
            )
            return
        except discord.Forbidden:
            await interaction.followup.send(
                "⚠️ Ich darf in dem Channel keine Reaktion hinzufügen.", ephemeral=True
            )
            return
        except discord.HTTPException:
            await interaction.followup.send(
                "⚠️ Das sieht nicht nach einem gültigen Emoji aus (oder ich kann dieses Server-Emoji nicht nutzen).",
                ephemeral=True,
            )
            return
        extra = f" (nur für {required_role.mention})" if required_role else ""
        await interaction.followup.send(
            f"✅ {emoji} an Nachricht `{message_id}` → {role.mention} gebunden{extra}.", ephemeral=True
        )

    @group.command(name="remove", description="Entfernt eine Reaction-Role-Bindung.")
    @app_commands.describe(message_id="ID der Nachricht", emoji="Das gebundene Emoji")
    async def rr_remove(self, interaction: discord.Interaction, message_id: str, emoji: str) -> None:
        if not message_id.isdigit():
            await interaction.response.send_message("⚠️ Ungültige Nachrichten-ID.", ephemeral=True)
            return
        ok = self.unbind(interaction.guild_id, int(message_id), emoji)  # type: ignore[arg-type]
        msg = "🗑️ Bindung entfernt." if ok else "⚠️ Keine passende Bindung gefunden."
        await interaction.response.send_message(msg, ephemeral=True)

    @group.command(name="list", description="Zeigt alle Reaction-Role-Bindungen dieses Servers.")
    async def rr_list(self, interaction: discord.Interaction) -> None:
        rows = self.db.list_reaction_roles(interaction.guild_id)
        if not rows:
            await interaction.response.send_message(
                "Noch keine Reaction Roles. Lege welche mit `/reactionrole add` an.", ephemeral=True
            )
            return
        lines = []
        for channel_id, message_id, emoji, role_id, required_role_id in rows:
            disp = emoji if ":" not in emoji else f"<:{emoji}>"
            req = f" · nur <@&{required_role_id}>" if required_role_id else ""
            lines.append(f"• {disp} → <@&{role_id}>  (Nachricht `{message_id}`{req})")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ReactionRolesCog(bot))

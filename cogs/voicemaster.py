"""Join-to-Create Voice-System mit kostenlosen Besitzer-Steuerungen.

Mitglieder betreten einen konfigurierten Lobby-Channel. Yami erstellt daraufhin
einen persönlichen Sprachkanal, verschiebt das Mitglied hinein und löscht den
Channel automatisch, sobald er leer ist. Besitzer können Name, Limit,
Sichtbarkeit, Zugang und Eigentümer ohne Premium-Abonnement verwalten.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

logger = logging.getLogger("oaken-tower-bot")

DEFAULT_CATEGORY_NAME = "Yami Voice"
DEFAULT_LOBBY_NAME = "➕ Eigenen Channel erstellen"
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")
_SPACE_RE = re.compile(r"\s+")


def clean_voice_name(value: str, fallback: str = "Eigener Voice") -> str:
    """Bereinigt User-Eingaben für einen lesbaren Discord-Channelnamen."""
    cleaned = _SPACE_RE.sub(" ", _CONTROL_RE.sub("", value)).strip()
    return (cleaned or fallback)[:100]


def default_voice_name(display_name: str) -> str:
    return clean_voice_name(f"🔊 {display_name}s Lounge")


def is_join_to_create_trigger(config: dict, channel_id: int | None) -> bool:
    """True nur für den aktivierten und exakt konfigurierten Lobby-Channel."""
    return bool(
        config.get("enabled")
        and channel_id is not None
        and channel_id == config.get("lobby_id")
    )


class RenameVoiceModal(discord.ui.Modal, title="Voice-Channel umbenennen"):
    name = discord.ui.TextInput(
        label="Neuer Channelname",
        placeholder="Gaming Lounge",
        min_length=1,
        max_length=100,
    )

    def __init__(self, cog: "VoiceMasterCog") -> None:
        super().__init__(timeout=180)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.rename_owned_channel(interaction, str(self.name))


class LimitVoiceModal(discord.ui.Modal, title="User-Limit einstellen"):
    limit = discord.ui.TextInput(
        label="Limit (0 = unbegrenzt)",
        placeholder="0 bis 99",
        min_length=1,
        max_length=2,
    )

    def __init__(self, cog: "VoiceMasterCog") -> None:
        super().__init__(timeout=180)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = str(self.limit).strip()
        if not raw.isdigit() or not 0 <= int(raw) <= 99:
            await interaction.response.send_message(
                "⚠️ Bitte gib eine Zahl zwischen 0 und 99 ein.", ephemeral=True
            )
            return
        await self.cog.set_owned_limit(interaction, int(raw))


class VoiceControlView(discord.ui.View):
    """Persistentes Steuerpult; der aktuelle Voice-Channel wird beim Klick ermittelt."""

    def __init__(self, cog: "VoiceMasterCog") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Umbenennen",
        emoji="✏️",
        style=discord.ButtonStyle.secondary,
        custom_id="yami_voice:rename",
    )
    async def rename(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        channel, _row = await self.cog.require_owner(interaction, respond=False)
        if channel is None:
            await interaction.response.send_message(
                "⛔ Du musst Besitzer deines aktuellen Yami-Voice-Channels sein.", ephemeral=True
            )
            return
        await interaction.response.send_modal(RenameVoiceModal(self.cog))

    @discord.ui.button(
        label="User-Limit",
        emoji="👥",
        style=discord.ButtonStyle.secondary,
        custom_id="yami_voice:limit",
    )
    async def limit(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        channel, _row = await self.cog.require_owner(interaction, respond=False)
        if channel is None:
            await interaction.response.send_message(
                "⛔ Du musst Besitzer deines aktuellen Yami-Voice-Channels sein.", ephemeral=True
            )
            return
        await interaction.response.send_modal(LimitVoiceModal(self.cog))

    @discord.ui.button(
        label="Sperren",
        emoji="🔒",
        style=discord.ButtonStyle.primary,
        custom_id="yami_voice:lock",
    )
    async def lock(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog.toggle_lock(interaction)

    @discord.ui.button(
        label="Verstecken",
        emoji="👻",
        style=discord.ButtonStyle.primary,
        custom_id="yami_voice:hide",
    )
    async def hide(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog.toggle_hidden(interaction)

    @discord.ui.button(
        label="Übernehmen",
        emoji="👑",
        style=discord.ButtonStyle.success,
        custom_id="yami_voice:claim",
    )
    async def claim(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog.claim_channel(interaction)


class VoiceMasterCog(commands.Cog):
    """Join-to-Create und Besitzer-Steuerung für temporäre Voice-Channels."""

    voice = app_commands.Group(
        name="voice",
        description="Persönliche Voice-Channels erstellen und verwalten.",
        guild_only=True,
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]
        self._creation_locks: set[int] = set()
        self._diagnostics_done = False

    async def cog_load(self) -> None:
        self.bot.add_view(VoiceControlView(self))
        self.cleanup_loop.start()

    async def cog_unload(self) -> None:
        self.cleanup_loop.cancel()

    def _member_voice_channel(self, interaction: discord.Interaction) -> discord.VoiceChannel | None:
        user = interaction.user
        if not isinstance(user, discord.Member) or user.voice is None:
            return None
        channel = user.voice.channel
        return channel if isinstance(channel, discord.VoiceChannel) else None

    async def require_owner(
        self, interaction: discord.Interaction, *, respond: bool = True
    ) -> tuple[discord.VoiceChannel | None, sqlite3.Row | None]:
        channel = self._member_voice_channel(interaction)
        row = self.db.get_temp_voice_channel(channel.id) if channel else None
        if channel is not None and row is not None and int(row["owner_id"]) == interaction.user.id:
            return channel, row
        if respond:
            await interaction.response.send_message(
                "⛔ Du musst Besitzer deines aktuellen Yami-Voice-Channels sein.", ephemeral=True
            )
        return None, row

    async def _audit(
        self,
        guild: discord.Guild,
        event_type: str,
        summary: str,
        *,
        actor: discord.Member | None = None,
        channel: discord.VoiceChannel | None = None,
        detail: str | None = None,
    ) -> None:
        audit = self.bot.get_cog("AuditCog")
        if audit is not None and hasattr(audit, "log"):
            await audit.log(  # type: ignore[attr-defined]
                guild,
                "voice",
                event_type,
                summary,
                actor=actor,
                channel=channel,
                detail=detail,
            )
            return
        self.db.add_audit_log(
            guild.id,
            "voice",
            event_type,
            summary,
            actor_id=actor.id if actor else None,
            channel_id=channel.id if channel else None,
            detail=detail,
        )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        config = self.db.get_voice_config(member.guild.id)
        if (
            isinstance(after.channel, discord.VoiceChannel)
            and is_join_to_create_trigger(config, after.channel.id)
        ):
            logger.info(
                "Join-to-Create-Trigger: User %s betrat Lobby %s auf Guild %s.",
                member.id,
                config["lobby_id"],
                member.guild.id,
            )
            await self._create_for_member(member, after.channel, config)

        if (
            isinstance(before.channel, discord.VoiceChannel)
            and before.channel.id != getattr(after.channel, "id", None)
        ):
            await self._delete_if_empty(before.channel)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Prüft die produktive Lobby-Konfiguration und benötigte Bot-Rechte einmalig."""
        if self._diagnostics_done:
            return
        self._diagnostics_done = True
        for guild in self.bot.guilds:
            config = self.db.get_voice_config(guild.id)
            if not config["enabled"]:
                continue
            lobby = guild.get_channel(config["lobby_id"])
            if not isinstance(lobby, discord.VoiceChannel):
                logger.warning(
                    "Yami Voice auf Guild %s ist aktiv, aber Lobby %s ist nicht erreichbar/kein Voice-Channel.",
                    guild.id,
                    config["lobby_id"],
                )
                continue
            me = guild.me
            if me is None:
                logger.warning("Yami Voice: Bot-Mitglied auf Guild %s nicht im Cache.", guild.id)
                continue
            permissions = lobby.permissions_for(me)
            missing = [
                label
                for label, allowed in (
                    ("ViewChannel", permissions.view_channel),
                    ("Connect", permissions.connect),
                    ("ManageChannels", permissions.manage_channels),
                    ("MoveMembers", permissions.move_members),
                )
                if not allowed
            ]
            if missing:
                logger.warning(
                    "Yami Voice Lobby %s (%s) auf Guild %s: fehlende Rechte: %s.",
                    lobby.name,
                    lobby.id,
                    guild.id,
                    ", ".join(missing),
                )
            else:
                logger.info(
                    "Yami Voice bereit: Lobby %s (%s), Kategorie %s, Guild %s.",
                    lobby.name,
                    lobby.id,
                    getattr(lobby.category, "id", None),
                    guild.id,
                )

    async def _create_for_member(
        self,
        member: discord.Member,
        lobby: discord.abc.Connectable,
        config: dict,
    ) -> None:
        if member.id in self._creation_locks:
            return
        self._creation_locks.add(member.id)
        channel: discord.VoiceChannel | None = None
        try:
            category = member.guild.get_channel(config["category_id"])
            if not isinstance(category, discord.CategoryChannel):
                category = getattr(lobby, "category", None)
            overwrites: dict[
                discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite
            ] = {
                member: discord.PermissionOverwrite(
                    view_channel=True,
                    connect=True,
                    speak=True,
                    stream=True,
                    manage_channels=True,
                    move_members=True,
                )
            }
            channel = await member.guild.create_voice_channel(
                default_voice_name(member.display_name),
                category=category,
                overwrites=overwrites,
                reason=f"Yami Join-to-Create für {member} ({member.id})",
            )
            self.db.add_temp_voice_channel(member.guild.id, channel.id, member.id)
            await member.move_to(channel, reason="Yami Join-to-Create")
            await self._send_panel(channel, member)
            await self._audit(
                member.guild,
                "temp_voice_create",
                f"✨ Persönlicher Voice-Channel **{channel.name}** für **{member}** erstellt",
                actor=member,
                channel=channel,
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.warning("Join-to-Create für %s fehlgeschlagen: %s", member.id, exc)
            if channel is not None:
                self.db.remove_temp_voice_channel(channel.id)
                try:
                    await channel.delete(reason="Join-to-Create fehlgeschlagen")
                except discord.HTTPException:
                    pass
        finally:
            self._creation_locks.discard(member.id)

    async def _send_panel(self, channel: discord.VoiceChannel, owner: discord.Member) -> None:
        embed = discord.Embed(
            title="🎙️ Dein persönlicher Voice-Channel",
            description=(
                f"{owner.mention}, dieser Channel gehört dir. Nutze die Buttons oder `/voice`-Befehle, "
                "um ihn kostenlos zu verwalten.\n\n"
                "**Zugriff:** `/voice permit`, `/voice reject`\n"
                "**Besitz:** `/voice transfer`, `/voice claim`\n"
                "Der Channel wird automatisch gelöscht, sobald er leer ist."
            ),
            color=0x8B5CF6,
        )
        embed.set_footer(text="Yami Voice · keine Premium-Sperren")
        try:
            await channel.send(
                embed=embed,
                view=VoiceControlView(self),
                allowed_mentions=discord.AllowedMentions(users=True),
            )
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Voice-Steuerpult konnte in Channel %s nicht gesendet werden.", channel.id)

    async def _delete_if_empty(self, channel: discord.VoiceChannel) -> None:
        row = self.db.get_temp_voice_channel(channel.id)
        if row is None:
            return
        if any(not member.bot for member in channel.members):
            return
        self.db.remove_temp_voice_channel(channel.id)
        try:
            await channel.delete(reason="Yami Voice: temporärer Channel ist leer")
        except discord.NotFound:
            pass
        except discord.HTTPException as exc:
            logger.warning("Temporärer Voice-Channel %s konnte nicht gelöscht werden: %s", channel.id, exc)

    async def rename_owned_channel(self, interaction: discord.Interaction, name: str) -> None:
        channel, _row = await self.require_owner(interaction)
        if channel is None:
            return
        cleaned = clean_voice_name(name)
        await channel.edit(name=cleaned, reason=f"Voice-Name durch {interaction.user}")
        await interaction.response.send_message(f"✅ Channel heißt jetzt **{cleaned}**.", ephemeral=True)

    async def set_owned_limit(self, interaction: discord.Interaction, limit: int) -> None:
        channel, _row = await self.require_owner(interaction)
        if channel is None:
            return
        await channel.edit(user_limit=limit, reason=f"Voice-Limit durch {interaction.user}")
        text = "unbegrenzt" if limit == 0 else str(limit)
        await interaction.response.send_message(f"✅ User-Limit: **{text}**.", ephemeral=True)

    async def toggle_lock(self, interaction: discord.Interaction) -> None:
        channel, _row = await self.require_owner(interaction)
        if channel is None or interaction.guild is None:
            return
        current = channel.overwrites_for(interaction.guild.default_role)
        locked = current.connect is False
        current.connect = None if locked else False
        await channel.set_permissions(
            interaction.guild.default_role,
            overwrite=current,
            reason=f"Voice {'entsperrt' if locked else 'gesperrt'} durch {interaction.user}",
        )
        await interaction.response.send_message(
            f"{'🔓 Channel entsperrt.' if locked else '🔒 Channel gesperrt.'}", ephemeral=True
        )

    async def toggle_hidden(self, interaction: discord.Interaction) -> None:
        channel, _row = await self.require_owner(interaction)
        if channel is None or interaction.guild is None:
            return
        current = channel.overwrites_for(interaction.guild.default_role)
        hidden = current.view_channel is False
        current.view_channel = None if hidden else False
        await channel.set_permissions(
            interaction.guild.default_role,
            overwrite=current,
            reason=f"Voice {'sichtbar' if hidden else 'versteckt'} durch {interaction.user}",
        )
        await interaction.response.send_message(
            f"{'👁️ Channel wieder sichtbar.' if hidden else '👻 Channel versteckt.'}", ephemeral=True
        )

    async def claim_channel(self, interaction: discord.Interaction) -> None:
        channel = self._member_voice_channel(interaction)
        row = self.db.get_temp_voice_channel(channel.id) if channel else None
        if channel is None or row is None or interaction.guild is None:
            await interaction.response.send_message(
                "⛔ Du bist in keinem persönlichen Yami-Voice-Channel.", ephemeral=True
            )
            return
        owner_id = int(row["owner_id"])
        if any(member.id == owner_id for member in channel.members):
            await interaction.response.send_message(
                "⛔ Der aktuelle Besitzer ist noch im Channel.", ephemeral=True
            )
            return
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("⛔ Nur Servermitglieder können übernehmen.", ephemeral=True)
            return
        await self._transfer_owner(channel, owner_id, interaction.user)
        await interaction.response.send_message("👑 Du hast den Channel übernommen.", ephemeral=True)

    async def _transfer_owner(
        self,
        channel: discord.VoiceChannel,
        old_owner_id: int,
        new_owner: discord.Member,
    ) -> None:
        guild = channel.guild
        old_owner = guild.get_member(old_owner_id)
        if old_owner is not None:
            await channel.set_permissions(old_owner, overwrite=None, reason="Voice-Besitz übertragen")
        await channel.set_permissions(
            new_owner,
            view_channel=True,
            connect=True,
            speak=True,
            stream=True,
            manage_channels=True,
            move_members=True,
            reason="Voice-Besitz übertragen",
        )
        self.db.set_temp_voice_owner(channel.id, new_owner.id)

    async def ensure_voice_setup(
        self,
        guild: discord.Guild,
        *,
        actor_label: str,
        category_id: int | None = None,
        lobby_id: int | None = None,
        lobby_name: str | None = None,
    ) -> tuple[discord.CategoryChannel, discord.VoiceChannel]:
        """Nutzt eine vorhandene Lobby oder erstellt eine neue und aktiviert Join-to-Create."""
        config = self.db.get_voice_config(guild.id)
        selected_lobby = guild.get_channel(lobby_id) if lobby_id else None
        if lobby_id is not None and not isinstance(selected_lobby, discord.VoiceChannel):
            raise ValueError("lobby_id must reference a voice channel")

        lobby = selected_lobby
        if not isinstance(lobby, discord.VoiceChannel) and config["lobby_id"]:
            lobby = guild.get_channel(config["lobby_id"])

        category = guild.get_channel(category_id) if category_id else None
        if not isinstance(category, discord.CategoryChannel) and isinstance(
            selected_lobby, discord.VoiceChannel
        ):
            category = selected_lobby.category
        if not isinstance(category, discord.CategoryChannel) and config["category_id"]:
            category = guild.get_channel(config["category_id"])
        if not isinstance(category, discord.CategoryChannel) and isinstance(
            lobby, discord.VoiceChannel
        ):
            category = lobby.category
        if not isinstance(category, discord.CategoryChannel):
            category = discord.utils.get(guild.categories, name=DEFAULT_CATEGORY_NAME)
        if category is None:
            category = await guild.create_category(
                DEFAULT_CATEGORY_NAME, reason=f"Voice-System eingerichtet durch {actor_label}"
            )

        if isinstance(lobby, discord.VoiceChannel):
            edit_options = {
                "category": category,
                "user_limit": 1,
                "reason": f"Join-to-Create aktualisiert durch {actor_label}",
            }
            if lobby_name is not None:
                edit_options["name"] = clean_voice_name(lobby_name, DEFAULT_LOBBY_NAME)
            await lobby.edit(**edit_options)
        else:
            lobby = await guild.create_voice_channel(
                clean_voice_name(lobby_name or DEFAULT_LOBBY_NAME, DEFAULT_LOBBY_NAME),
                category=category,
                user_limit=1,
                reason=f"Join-to-Create eingerichtet durch {actor_label}",
            )
        self.db.set_voice_config(
            guild.id,
            enabled=True,
            lobby_id=lobby.id,
            category_id=category.id,
        )
        return category, lobby

    @voice.command(name="setup", description="Erstellt und aktiviert den Join-to-Create-Channel.")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.describe(
        lobby="Optional: vorhandenen Voice-Channel als Join-to-Create-Lobby verwenden",
        kategorie="Optional: Kategorie für Lobby und persönliche Channels",
        lobby_name="Optional: Lobby umbenennen; leer lässt den vorhandenen Namen stehen",
    )
    async def voice_setup(
        self,
        interaction: discord.Interaction,
        lobby: discord.VoiceChannel | None = None,
        kategorie: discord.CategoryChannel | None = None,
        lobby_name: app_commands.Range[str, 1, 100] | None = None,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            return
        await interaction.response.defer(ephemeral=True)
        _category, configured_lobby = await self.ensure_voice_setup(
            guild,
            actor_label=str(interaction.user),
            category_id=kategorie.id if kategorie else None,
            lobby_id=lobby.id if lobby else None,
            lobby_name=str(lobby_name) if lobby_name is not None else None,
        )
        await interaction.followup.send(
            f"✅ Join-to-Create ist aktiv: {configured_lobby.mention}\n"
            "Wer den Channel betritt, bekommt automatisch einen persönlichen Voice-Channel.",
            ephemeral=True,
        )

    @voice.command(name="disable", description="Deaktiviert Join-to-Create.")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.describe(lobby_loeschen="Den bisherigen Lobby-Channel ebenfalls löschen")
    async def voice_disable(
        self, interaction: discord.Interaction, lobby_loeschen: bool = False
    ) -> None:
        guild = interaction.guild
        if guild is None:
            return
        config = self.db.get_voice_config(guild.id)
        lobby = guild.get_channel(config["lobby_id"]) if config["lobby_id"] else None
        lobby_id = config["lobby_id"]
        if lobby_loeschen and isinstance(lobby, discord.VoiceChannel):
            await lobby.delete(reason=f"Voice-System deaktiviert durch {interaction.user}")
            lobby_id = None
        self.db.set_voice_config(
            guild.id,
            enabled=False,
            lobby_id=lobby_id,
            category_id=config["category_id"],
        )
        await interaction.response.send_message("✅ Join-to-Create wurde deaktiviert.", ephemeral=True)

    @voice.command(name="status", description="Zeigt den Status des Voice-Systems.")
    async def voice_status(self, interaction: discord.Interaction) -> None:
        config = self.db.get_voice_config(interaction.guild_id)
        lobby = f"<#{config['lobby_id']}>" if config["lobby_id"] else "nicht eingerichtet"
        active = len(self.db.list_temp_voice_channels(interaction.guild_id))
        await interaction.response.send_message(
            f"🎙️ **Yami Voice**\nStatus: **{'aktiv' if config['enabled'] else 'aus'}**\n"
            f"Lobby: {lobby}\nAktive persönliche Channels: **{active}**",
            ephemeral=True,
        )

    @voice.command(name="panel", description="Zeigt das Steuerpult für deinen Voice-Channel.")
    async def voice_panel(self, interaction: discord.Interaction) -> None:
        channel, _row = await self.require_owner(interaction)
        if channel is None:
            return
        embed = discord.Embed(
            title="🎛️ Voice-Steuerpult",
            description="Verwalte deinen persönlichen Channel über die Buttons.",
            color=0x8B5CF6,
        )
        await interaction.response.send_message(embed=embed, view=VoiceControlView(self), ephemeral=True)

    @voice.command(name="name", description="Benennt deinen persönlichen Voice-Channel um.")
    @app_commands.describe(name="Neuer Channelname")
    async def voice_name(
        self, interaction: discord.Interaction, name: app_commands.Range[str, 1, 100]
    ) -> None:
        await self.rename_owned_channel(interaction, str(name))

    @voice.command(name="limit", description="Setzt das User-Limit (0 = unbegrenzt).")
    async def voice_limit(
        self, interaction: discord.Interaction, anzahl: app_commands.Range[int, 0, 99]
    ) -> None:
        await self.set_owned_limit(interaction, int(anzahl))

    @voice.command(name="lock", description="Sperrt deinen Channel für neue Mitglieder.")
    async def voice_lock(self, interaction: discord.Interaction) -> None:
        channel, _row = await self.require_owner(interaction)
        if channel is None or interaction.guild is None:
            return
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.connect = False
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message("🔒 Channel gesperrt.", ephemeral=True)

    @voice.command(name="unlock", description="Entsperrt deinen Channel.")
    async def voice_unlock(self, interaction: discord.Interaction) -> None:
        channel, _row = await self.require_owner(interaction)
        if channel is None or interaction.guild is None:
            return
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.connect = None
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message("🔓 Channel entsperrt.", ephemeral=True)

    @voice.command(name="hide", description="Versteckt deinen Channel für andere.")
    async def voice_hide(self, interaction: discord.Interaction) -> None:
        channel, _row = await self.require_owner(interaction)
        if channel is None or interaction.guild is None:
            return
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.view_channel = False
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message("👻 Channel versteckt.", ephemeral=True)

    @voice.command(name="reveal", description="Macht deinen Channel wieder sichtbar.")
    async def voice_reveal(self, interaction: discord.Interaction) -> None:
        channel, _row = await self.require_owner(interaction)
        if channel is None or interaction.guild is None:
            return
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.view_channel = None
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message("👁️ Channel wieder sichtbar.", ephemeral=True)

    @voice.command(name="permit", description="Erlaubt einem Mitglied Zugriff auf deinen Channel.")
    async def voice_permit(
        self, interaction: discord.Interaction, user: discord.Member
    ) -> None:
        channel, _row = await self.require_owner(interaction)
        if channel is None:
            return
        await channel.set_permissions(user, view_channel=True, connect=True)
        await interaction.response.send_message(
            f"✅ {user.mention} darf den Channel betreten.", ephemeral=True
        )

    @voice.command(name="reject", description="Entfernt und sperrt ein Mitglied aus deinem Channel.")
    async def voice_reject(
        self, interaction: discord.Interaction, user: discord.Member
    ) -> None:
        channel, _row = await self.require_owner(interaction)
        if channel is None:
            return
        if user.id == interaction.user.id:
            await interaction.response.send_message("⛔ Du kannst dich nicht selbst sperren.", ephemeral=True)
            return
        await channel.set_permissions(user, view_channel=False, connect=False)
        if user.voice and user.voice.channel and user.voice.channel.id == channel.id:
            await user.move_to(None, reason=f"Aus Voice entfernt durch {interaction.user}")
        await interaction.response.send_message(
            f"🚫 {user.mention} wurde aus dem Channel ausgeschlossen.", ephemeral=True
        )

    @voice.command(name="transfer", description="Überträgt deinen Channel an ein Mitglied darin.")
    async def voice_transfer(
        self, interaction: discord.Interaction, user: discord.Member
    ) -> None:
        channel, row = await self.require_owner(interaction)
        if channel is None or row is None:
            return
        if user.bot or user not in channel.members:
            await interaction.response.send_message(
                "⛔ Die Person muss als Mensch in deinem Voice-Channel sein.", ephemeral=True
            )
            return
        await self._transfer_owner(channel, int(row["owner_id"]), user)
        await interaction.response.send_message(
            f"👑 {user.mention} ist jetzt Besitzer des Channels.", ephemeral=True
        )

    @voice.command(name="claim", description="Übernimmt einen Channel, dessen Besitzer gegangen ist.")
    async def voice_claim(self, interaction: discord.Interaction) -> None:
        await self.claim_channel(interaction)

    @tasks.loop(minutes=10)
    async def cleanup_loop(self) -> None:
        """Bereinigt verwaiste DB-Zeilen und leer gebliebene Channels nach Neustarts."""
        for row in self.db.list_temp_voice_channels():
            guild = self.bot.get_guild(int(row["guild_id"]))
            channel = guild.get_channel(int(row["channel_id"])) if guild else None
            if channel is None:
                self.db.remove_temp_voice_channel(int(row["channel_id"]))
            elif isinstance(channel, discord.VoiceChannel):
                await self._delete_if_empty(channel)

    @cleanup_loop.before_loop
    async def before_cleanup_loop(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceMasterCog(bot))

"""LFG (Looking for Group): Gruppensuche per Post mit Join/Leave-Buttons.

/lfg start braucht Größe, Beschreibung und Voice-Channel. Optional kann eine Rolle
zum Pingen gewählt werden (sonst wird die per /lfg setrole konfigurierte LFG-Rolle
gepingt). Löst der Host die Gruppe auf, wird der Post automatisch gelöscht.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("oaken-tower-bot")

LFG_TIMEOUT = 3600.0  # Post läuft nach 1 h ab
BAR_MAX_SIZE = 12     # Fortschrittsbalken nur bis zu dieser Gruppengröße zeigen


class LFGView(discord.ui.View):
    """Eine Gruppensuche mit Join/Leave-Buttons."""

    def __init__(
        self,
        host: discord.Member,
        size: int,
        note: str,
        channel: discord.VoiceChannel,
    ) -> None:
        super().__init__(timeout=LFG_TIMEOUT)
        self.host = host
        self.size = size
        self.note = note
        self.channel = channel
        self.members: list[discord.Member] = [host]
        self.message: discord.Message | None = None
        self.closed = False

    def _set_join_disabled(self, disabled: bool) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.label == "Join":
                child.disabled = disabled

    def _bar(self) -> str:
        if self.size > BAR_MAX_SIZE:
            return ""
        return "🟩" * len(self.members) + "⬜" * (self.size - len(self.members))

    def render(self, timed_out: bool = False) -> discord.Embed:
        full = len(self.members) >= self.size
        if timed_out:
            color, status = 0x95A5A6, "⏱️ Abgelaufen."
        elif full:
            color, status = 0x2ECC71, "✅ Gruppe ist voll — viel Spaß!"
        else:
            color, status = 0x3498DB, f"🔎 Suche {self.size - len(self.members)} weitere…"

        embed = discord.Embed(title="🎮 Looking for Group", color=color)
        embed.set_author(name=f"{self.host.display_name} sucht eine Gruppe", icon_url=self.host.display_avatar.url)
        embed.set_thumbnail(url=self.host.display_avatar.url)
        embed.add_field(name="📝 Worum geht's?", value=self.note, inline=False)
        embed.add_field(name="🔊 Voice-Channel", value=self.channel.mention, inline=True)
        embed.add_field(name="👥 Plätze", value=f"{len(self.members)} / {self.size}", inline=True)

        bar = self._bar()
        members_str = "\n".join(
            f"{'👑' if m.id == self.host.id else '•'} {m.mention}" for m in self.members
        )
        value = (f"{bar}\n{members_str}" if bar else members_str)
        embed.add_field(name="Teilnehmer", value=value, inline=False)
        embed.add_field(name="Status", value=status, inline=False)
        embed.set_footer(text="Join/Leave per Button · Host kann mit Leave auflösen · läuft nach 1 h ab")
        return embed

    @discord.ui.button(label="Join", style=discord.ButtonStyle.success, emoji="✅")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if any(m.id == interaction.user.id for m in self.members):
            await interaction.response.send_message("Du bist schon in der Gruppe.", ephemeral=True)
            return
        if len(self.members) >= self.size:
            await interaction.response.send_message("Die Gruppe ist schon voll.", ephemeral=True)
            return
        self.members.append(interaction.user)
        if len(self.members) >= self.size:
            self._set_join_disabled(True)
        await interaction.response.edit_message(embed=self.render(), view=self)

    @discord.ui.button(label="Leave", style=discord.ButtonStyle.secondary, emoji="🚪")
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        # Host verlässt → Gruppe auflösen und Post löschen.
        if interaction.user.id == self.host.id:
            self.closed = True
            self.stop()
            await interaction.response.send_message(
                "🗑️ Gruppe aufgelöst — der Post wurde gelöscht.", ephemeral=True
            )
            try:
                await interaction.message.delete()
            except discord.HTTPException:
                pass
            return
        before = len(self.members)
        self.members = [m for m in self.members if m.id != interaction.user.id]
        if len(self.members) == before:
            await interaction.response.send_message("Du bist nicht in der Gruppe.", ephemeral=True)
            return
        self._set_join_disabled(False)
        await interaction.response.edit_message(embed=self.render(), view=self)

    async def on_timeout(self) -> None:
        if self.closed or self.message is None:
            return
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(embed=self.render(timed_out=True), view=self)
        except discord.HTTPException:
            pass


class LFGCog(commands.Cog):
    """/lfg start, /lfg role, /lfg setrole."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]

    lfg = app_commands.Group(name="lfg", description="Gruppensuche (Looking for Group).", guild_only=True)

    @lfg.command(name="start", description="Erstelle eine Gruppensuche.")
    @app_commands.describe(
        size="Maximale Gruppengröße (2–25)",
        beschreibung="Worum geht's? (z.B. Modus, Rang, Uhrzeit)",
        channel="Voice-Channel, in dem gespielt wird",
        rolle="Optional: diese Rolle pingen (statt der LFG-Rolle)",
    )
    async def start(
        self,
        interaction: discord.Interaction,
        size: app_commands.Range[int, 2, 25],
        beschreibung: str,
        channel: discord.VoiceChannel,
        rolle: discord.Role | None = None,
    ) -> None:
        # Ping-Ziel: gewählte Rolle, sonst die konfigurierte LFG-Rolle.
        if rolle is not None:
            ping_role = rolle
        else:
            role_id = self.db.get_lfg_role(interaction.guild_id)
            ping_role = interaction.guild.get_role(role_id) if role_id else None

        view = LFGView(interaction.user, size, beschreibung, channel)
        await interaction.response.send_message(
            content=ping_role.mention if ping_role else None,
            embed=view.render(),
            view=view,
            allowed_mentions=discord.AllowedMentions(roles=True),
        )
        view.message = await interaction.original_response()

    @lfg.command(name="role", description="Melde dich für LFG-Pings an oder ab.")
    async def role(self, interaction: discord.Interaction) -> None:
        role_id = self.db.get_lfg_role(interaction.guild_id)
        role = interaction.guild.get_role(role_id) if role_id else None
        if role is None:
            await interaction.response.send_message(
                "⚠️ Es ist keine LFG-Rolle gesetzt. Ein Admin kann sie mit `/lfg setrole` festlegen.",
                ephemeral=True,
            )
            return
        try:
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role, reason="LFG opt-out")
                await interaction.response.send_message(
                    f"🔕 Du bekommst keine {role.mention}-Pings mehr.", ephemeral=True
                )
            else:
                await interaction.user.add_roles(role, reason="LFG opt-in")
                await interaction.response.send_message(
                    f"🔔 Du bekommst jetzt {role.mention}-Pings.", ephemeral=True
                )
        except discord.Forbidden:
            await interaction.response.send_message(
                "⚠️ Mir fehlt die Berechtigung **Rollen verwalten** (oder die LFG-Rolle steht über meiner). "
                "Bitte einen Admin, das zu korrigieren.",
                ephemeral=True,
            )

    @lfg.command(name="setrole", description="Setzt die Rolle, die bei /lfg start gepingt wird.")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.describe(role="Die LFG-Ping-Rolle")
    async def setrole(self, interaction: discord.Interaction, role: discord.Role) -> None:
        self.db.set_lfg_role(interaction.guild_id, role.id)
        await interaction.response.send_message(
            f"✅ LFG-Rolle gesetzt: {role.mention}. Mitglieder können sich mit `/lfg role` an-/abmelden.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LFGCog(bot))

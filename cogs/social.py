"""Globales Freundes-System: Anfragen/Bestätigen, Liste, Friendship-Level.

Friendship-XP wächst v.a. durch Interactions (siehe cogs/interactions.py).
Level = XP // FXP_PER_LEVEL.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("oaken-tower-bot")

FXP_PER_LEVEL = 100


def friend_level(xp: int) -> int:
    return xp // FXP_PER_LEVEL


def level_progress(xp: int) -> tuple[int, int]:
    """(XP im aktuellen Level, XP fürs nächste)."""
    return xp % FXP_PER_LEVEL, FXP_PER_LEVEL


def friend_request_embed(requester: discord.abc.User, target: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="Eine neue Verbindung wartet",
        description=(
            f"{requester.mention} möchte dich in Yamikuns Freundeskreis aufnehmen.\n\n"
            "Gemeinsam sammelt ihr Freundschafts-XP und könnt eure öffentlichen Achievements vergleichen."
        ),
        color=0x8B5CF6,
    )
    embed.set_author(name=requester.display_name, icon_url=requester.display_avatar.url)
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.set_footer(text="Die Anfrage kann nur von der eingeladenen Person angenommen werden.")
    return embed


class FriendRequestView(discord.ui.View):
    def __init__(self, db, guild_id: int, requester_id: int, target_id: int) -> None:
        super().__init__(timeout=86_400)
        self.db = db
        self.guild_id = guild_id
        self.requester_id = requester_id
        self.target_id = target_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.target_id:
            return True
        await interaction.response.send_message(
            "Diese Einladung ist nicht für dich bestimmt.", ephemeral=True
        )
        return False

    @discord.ui.button(label="Freundschaft annehmen", emoji="🤝", style=discord.ButtonStyle.success)
    async def accept_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not self.db.accept_friend(self.guild_id, self.target_id, self.requester_id):
            await interaction.response.send_message(
                "Diese Freundschaftsanfrage ist nicht mehr offen.", ephemeral=True
            )
            return
        button.disabled = True
        button.label = "Freundschaft angenommen"
        embed = discord.Embed(
            title="Freundschaft geschlossen",
            description=(
                f"{interaction.user.mention} und <@{self.requester_id}> sind jetzt Teil desselben Freundeskreises.\n"
                "Zeit, gemeinsam Freundschafts-XP zu sammeln."
            ),
            color=0x22C55E,
        )
        embed.set_footer(text="Yamikun bewahrt diese Verbindung serverübergreifend auf.")
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()


class SocialCog(commands.Cog):
    """/friend (add, accept, remove, requests, list, level)."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]

    friend = app_commands.Group(
        name="friend", description="Serverübergreifende Freundesliste und Freundschaftslevel.", guild_only=True
    )

    @friend.command(name="add", description="Schicke jemandem eine Freundschaftsanfrage.")
    @app_commands.describe(user="Wen möchtest du als Freund:in hinzufügen?")
    async def add(self, interaction: discord.Interaction, user: discord.Member) -> None:
        if interaction.guild_id is None:
            return
        if user.bot or user.id == interaction.user.id:
            await interaction.response.send_message(
                "⚠️ Das geht nicht (nicht mit Bots oder dir selbst).", ephemeral=True
            )
            return
        code = self.db.send_friend_request(interaction.guild_id, interaction.user.id, user.id)
        if code == "already_friends":
            await interaction.response.send_message(
                f"Du bist bereits mit {user.mention} befreundet.", ephemeral=True
            )
        elif code == "already_pending":
            await interaction.response.send_message(
                f"Du hast {user.mention} bereits eine Anfrage geschickt.", ephemeral=True
            )
        elif code == "accepted_now":
            await interaction.response.send_message(
                f"🤝 {interaction.user.mention} und {user.mention} sind jetzt **befreundet**!"
            )
        else:  # requested
            view = FriendRequestView(
                self.db, interaction.guild_id, interaction.user.id, user.id
            )
            await interaction.response.send_message(
                content=user.mention,
                embed=friend_request_embed(interaction.user, user),
                view=view,
                allowed_mentions=discord.AllowedMentions(users=True),
            )

    @friend.command(name="accept", description="Nimm eine Freundschaftsanfrage an.")
    @app_commands.describe(user="Von wem?")
    async def accept(self, interaction: discord.Interaction, user: discord.Member) -> None:
        if self.db.accept_friend(interaction.guild_id, interaction.user.id, user.id):
            await interaction.response.send_message(
                f"🤝 {interaction.user.mention} und {user.mention} sind jetzt **befreundet**!"
            )
        else:
            await interaction.response.send_message(
                f"⚠️ Von {user.mention} liegt keine offene Anfrage vor.", ephemeral=True
            )

    @friend.command(name="remove", description="Entferne eine Freundschaft oder Anfrage.")
    @app_commands.describe(user="Wen?")
    async def remove(self, interaction: discord.Interaction, user: discord.Member) -> None:
        if self.db.remove_friend(interaction.guild_id, interaction.user.id, user.id):
            await interaction.response.send_message(
                f"💔 {user.mention} wurde aus deiner Freundesliste entfernt.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"⚠️ Mit {user.mention} besteht keine Freundschaft/Anfrage.", ephemeral=True
            )

    @friend.command(name="requests", description="Zeigt offene eingehende Freundschaftsanfragen.")
    async def requests(self, interaction: discord.Interaction) -> None:
        ids = self.db.list_incoming_requests(interaction.guild_id, interaction.user.id)
        if not ids:
            await interaction.response.send_message(
                "Keine offenen Anfragen.", ephemeral=True
            )
            return
        lines = [f"• <@{uid}> — `/friend accept`" for uid in ids]
        embed = discord.Embed(
            title="📬 Offene Freundschaftsanfragen", description="\n".join(lines), color=0x7C3AED
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @friend.command(name="list", description="Zeigt deine globalen Freunde und Friendship-Level.")
    @app_commands.describe(user="Optional: wessen Freundesliste? (Standard: du)")
    async def list_(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        target = user or interaction.user
        friends = self.db.list_friends(interaction.guild_id, target.id)
        if not friends:
            await interaction.response.send_message(
                f"{target.display_name} hat noch keine Freunde in der globalen Liste.", ephemeral=True
            )
            return
        lines = []
        for i, (other_id, xp) in enumerate(friends, start=1):
            member = interaction.guild.get_member(other_id)
            name = member.display_name if member else f"User {other_id}"
            lines.append(f"**{i}.** {name} — Friendship-Level **{friend_level(xp)}** ({xp} FXP)")
        embed = discord.Embed(
            title=f"👥 Globale Freunde von {target.display_name}",
            description="\n".join(lines),
            color=0x7C3AED,
        )
        await interaction.response.send_message(embed=embed)

    @friend.command(name="level", description="Zeigt euer Friendship-Level mit jemandem.")
    @app_commands.describe(user="Mit wem?")
    async def level(self, interaction: discord.Interaction, user: discord.Member) -> None:
        xp = self.db.friendship_xp(interaction.guild_id, interaction.user.id, user.id)
        into, need = level_progress(xp)
        row = self.db.get_friend_row(interaction.guild_id, interaction.user.id, user.id)
        status = "befreundet 🤝" if row and row["status"] == "accepted" else "noch nicht befreundet"
        embed = discord.Embed(
            title=f"Friendship: {interaction.user.display_name} & {user.display_name}",
            color=0xF8A5C2,
            description=(
                f"Level **{friend_level(xp)}** · {into}/{need} bis zum nächsten\n"
                f"Gesamt: **{xp}** Freundschafts-XP\nStatus: {status}"
            ),
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SocialCog(bot))

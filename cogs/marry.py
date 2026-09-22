"""Heiratsfunktion: /marry (Antrag mit Button), /divorce, /marriages.

Mehrere Ehen gleichzeitig sind erlaubt. Hochzeits-GIF kommt von nekos.best.
"""

from __future__ import annotations

import logging
import secrets
import time
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from cogs.nekos import fetch_gif_file

logger = logging.getLogger("oaken-tower-bot")

MARRY_GIF_CATEGORY = "kiss"   # nekos.best-Kategorie fürs Hochzeits-GIF
REJECT_GIF_CATEGORY = "cry"   # GIF bei Ablehnung
# Pro Abruf liefert nekos.best ein zufälliges GIF aus seiner jeweiligen Bibliothek.
# Mehrere Kategorien verhindern zusätzlich, dass abgelaufene Anträge monoton wirken.
ABANDONED_GIF_CATEGORIES = ("cry", "pout", "stare", "facepalm", "shrug")


class ProposalView(discord.ui.View):
    """Heiratsantrag – nur die angetragene Person darf antworten."""

    def __init__(self, cog: "MarryCog", proposer: discord.Member, target: discord.Member) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.proposer = proposer
        self.target = target
        self.message: discord.Message | None = None
        self.done = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.target.id:
            await interaction.response.send_message(
                "Diese Entscheidung liegt nicht bei dir. 💍", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Ja, ich will!", style=discord.ButtonStyle.success, emoji="💍")
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.done = True
        self.cog.db.add_marriage(interaction.guild_id, self.proposer.id, self.target.id, time.time())
        await interaction.response.defer()
        gif = await self.cog._fetch_gif(MARRY_GIF_CATEGORY)
        embed = discord.Embed(
            title="💖 Eine Hochzeit! 🎉",
            description=f"{self.proposer.mention} 💞 {self.target.mention} sind jetzt **verheiratet**!\nHerzlichen Glückwunsch! 🥂",
            color=0xFF6FA5,
        )
        if gif:
            embed.set_image(url=f"attachment://{gif.filename}")
        for child in self.children:
            child.disabled = True
        await interaction.edit_original_response(
            content=None, embed=embed, view=self, attachments=[gif] if gif else []
        )
        self.stop()

    @discord.ui.button(label="Nein…", style=discord.ButtonStyle.secondary, emoji="💔")
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.done = True
        await interaction.response.defer()
        gif = await self.cog._fetch_gif(REJECT_GIF_CATEGORY)
        embed = discord.Embed(
            description=f"💔 {self.target.mention} hat den Antrag von {self.proposer.mention} (vorerst) abgelehnt.",
            color=0x95A5A6,
        )
        if gif:
            embed.set_image(url=f"attachment://{gif.filename}")
        for child in self.children:
            child.disabled = True
        await interaction.edit_original_response(
            content=None, embed=embed, view=self, attachments=[gif] if gif else []
        )
        self.stop()

    async def on_timeout(self) -> None:
        if self.done or self.message is None:
            return
        self.done = True
        for child in self.children:
            child.disabled = True
        gif = await self.cog._fetch_gif(secrets.choice(ABANDONED_GIF_CATEGORIES))
        embed = discord.Embed(
            title="🥀 Am Altar allein gelassen …",
            description=(
                f"{self.proposer.mention}, du wurdest von {self.target.mention} "
                "am Altar allein gelassen.\n\n"
                "Der Heiratsantrag ist abgelaufen, ohne dass eine Antwort kam. 💔"
            ),
            color=0x6B5B73,
        )
        if gif:
            embed.set_image(url=f"attachment://{gif.filename}")
        embed.set_footer(text="Manche Liebesgeschichten brauchen wohl noch etwas Zeit.")
        try:
            await self.message.edit(
                content=None,
                embed=embed,
                view=self,
                attachments=[gif] if gif else [],
            )
        except discord.HTTPException:
            logger.warning("Abgelaufener Heiratsantrag konnte nicht aktualisiert werden.")
        finally:
            self.stop()


class MarryCog(commands.Cog):
    """/marry, /divorce, /marriages."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]
        self.session: Optional[aiohttp.ClientSession] = None

    async def cog_load(self) -> None:
        self.session = aiohttp.ClientSession()

    async def cog_unload(self) -> None:
        if self.session:
            await self.session.close()

    async def _fetch_gif(self, category: str) -> Optional[discord.File]:
        if self.session is None:
            return None
        try:
            return await fetch_gif_file(self.session, category, filename=f"{category}.gif")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Hochzeits-GIF-Abruf fehlgeschlagen: %s", exc)
            return None

    @app_commands.command(name="marry", description="Mache jemandem einen Heiratsantrag.")
    @app_commands.guild_only()
    @app_commands.describe(user="Wem möchtest du einen Antrag machen?")
    async def marry(self, interaction: discord.Interaction, user: discord.Member) -> None:
        if user.bot or user.id == interaction.user.id:
            await interaction.response.send_message(
                "⚠️ Das geht nicht (nicht mit Bots oder dir selbst).", ephemeral=True
            )
            return
        if self.db.are_married(interaction.guild_id, interaction.user.id, user.id):
            await interaction.response.send_message(
                f"💍 Ihr seid bereits verheiratet mit {user.mention}.", ephemeral=True
            )
            return
        view = ProposalView(self, interaction.user, user)
        embed = discord.Embed(
            title="💍 Ein Heiratsantrag!",
            description=f"{user.mention}, {interaction.user.mention} macht dir einen Antrag!\nWillst du? 💞",
            color=0xFF6FA5,
        )
        await interaction.response.send_message(
            content=user.mention, embed=embed, view=view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )
        view.message = await interaction.original_response()

    @app_commands.command(name="divorce", description="Lass dich von jemandem scheiden.")
    @app_commands.guild_only()
    @app_commands.describe(user="Von wem?")
    async def divorce(self, interaction: discord.Interaction, user: discord.Member) -> None:
        if self.db.remove_marriage(interaction.guild_id, interaction.user.id, user.id):
            await interaction.response.defer()
            gif = await self._fetch_gif(REJECT_GIF_CATEGORY)
            embed = discord.Embed(
                description=f"💔 {interaction.user.mention} und {user.mention} sind jetzt geschieden.",
                color=0x95A5A6,
            )
            if gif:
                embed.set_image(url=f"attachment://{gif.filename}")
            await interaction.edit_original_response(
                embed=embed, attachments=[gif] if gif else []
            )
        else:
            await interaction.response.send_message(
                "⚠️ Ihr seid gar nicht verheiratet.", ephemeral=True
            )

    @app_commands.command(name="marriages", description="Zeigt, mit wem jemand verheiratet ist.")
    @app_commands.guild_only()
    @app_commands.describe(user="Optional: wessen Ehen? (Standard: du)")
    async def marriages(
        self, interaction: discord.Interaction, user: discord.Member | None = None
    ) -> None:
        target = user or interaction.user
        rows = self.db.list_marriages(interaction.guild_id, target.id)
        if not rows:
            await interaction.response.send_message(
                f"{target.display_name} ist mit niemandem verheiratet. 💔", ephemeral=True
            )
            return
        lines = []
        for other_id, since in rows:
            member = interaction.guild.get_member(other_id)
            name = member.mention if member else f"<@{other_id}>"
            lines.append(f"💍 {name} — seit <t:{int(since)}:D>")
        embed = discord.Embed(
            title=f"💖 Ehen von {target.display_name}", description="\n".join(lines), color=0xFF6FA5
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MarryCog(bot))

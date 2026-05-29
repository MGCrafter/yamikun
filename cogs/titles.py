"""XP-Titel: durch Level freischaltbar, im Profil anzeigbar.

Befehle: /title list, /title set <titel>, /title clear.
Freigeschaltete Titel ergeben sich aus dem Level (siehe TITLE_TABLE).
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from cogs.leveling import level_from_total

# (benötigtes Level, Titel) — aufsteigend
TITLE_TABLE: list[tuple[int, str]] = [
    (5, "Grünschnabel"),
    (10, "Stammgast"),
    (20, "Veteran"),
    (30, "Profi"),
    (40, "Elite"),
    (50, "Legende"),
    (75, "Mythos"),
    (100, "Nightlord"),
]


def user_level(bot: commands.Bot, guild_id: int, user_id: int) -> int:
    xp = int(bot.db.get_user(guild_id, user_id)["xp"])  # type: ignore[attr-defined]
    return level_from_total(xp)[0]


def unlocked_titles(level: int) -> list[str]:
    return [title for lvl, title in TITLE_TABLE if level >= lvl]


async def _title_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    level = user_level(interaction.client, interaction.guild_id, interaction.user.id)  # type: ignore[arg-type]
    titles = unlocked_titles(level)
    return [
        app_commands.Choice(name=t, value=t)
        for t in titles
        if current.lower() in t.lower()
    ][:25]


class TitlesCog(commands.Cog):
    """/title (list, set, clear)."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]

    title = app_commands.Group(name="title", description="XP-Titel verwalten.", guild_only=True)

    @title.command(name="list", description="Zeigt alle Titel und ob du sie freigeschaltet hast.")
    async def title_list(self, interaction: discord.Interaction) -> None:
        level = user_level(self.bot, interaction.guild_id, interaction.user.id)
        equipped = self.db.get_title(interaction.guild_id, interaction.user.id)
        lines = []
        for lvl, name in TITLE_TABLE:
            if level >= lvl:
                mark = "✅" if name != equipped else "⭐ (aktiv)"
            else:
                mark = f"🔒 ab Level {lvl}"
            lines.append(f"**{name}** — {mark}")
        embed = discord.Embed(
            title="🏷️ Titel",
            description="\n".join(lines) + "\n\nMit `/title set` auswählen, mit `/title clear` entfernen.",
            color=0x5865F2,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @title.command(name="set", description="Wähle einen freigeschalteten Titel.")
    @app_commands.describe(titel="Welcher Titel? (nur freigeschaltete)")
    @app_commands.autocomplete(titel=_title_autocomplete)
    async def title_set(self, interaction: discord.Interaction, titel: str) -> None:
        level = user_level(self.bot, interaction.guild_id, interaction.user.id)
        if titel not in unlocked_titles(level):
            await interaction.response.send_message(
                "⚠️ Diesen Titel hast du noch nicht freigeschaltet.", ephemeral=True
            )
            return
        self.db.set_title(interaction.guild_id, interaction.user.id, titel)
        await interaction.response.send_message(
            f"🏷️ Dein Titel ist jetzt **{titel}**.", ephemeral=True
        )

    @title.command(name="clear", description="Entfernt deinen aktiven Titel.")
    async def title_clear(self, interaction: discord.Interaction) -> None:
        self.db.set_title(interaction.guild_id, interaction.user.id, None)
        await interaction.response.send_message("🏷️ Titel entfernt.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TitlesCog(bot))

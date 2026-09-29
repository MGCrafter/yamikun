"""Viewer account linking without a website login."""
import time

import discord
from discord import app_commands
from discord.ext import commands

from cogs.twitch import normalize_login
from twitch_chat.store import Store


class TwitchLinkCog(commands.Cog):
    def __init__(self, bot):
        self.store = Store(bot.db.conn)

    @app_commands.command(name="twitch-link", description="Verbinde dein Twitch-Konto mit deinen Discord-Coins.")
    @app_commands.describe(twitch_name="Dein Twitch-Login (kein Anzeigename)")
    async def twitch_link(self, interaction: discord.Interaction, twitch_name: str):
        login = normalize_login(twitch_name)
        if not login:
            await interaction.response.send_message("Bitte gib deinen gültigen Twitch-Login an.", ephemeral=True)
            return
        linked = self.store.conn.execute("SELECT twitch_id FROM twitch_chat_links WHERE discord_id=?", (interaction.user.id,)).fetchone()
        if linked:
            await interaction.response.send_message(
                "Dein Discord-Konto ist bereits mit Twitch verbunden. Prüfe im Twitch-Chat mit `!link` den Status "
                "und mit `!coins` dein gemeinsames Guthaben. Zum Wechseln trenne zuerst die Verbindung auf https://yamikun.eu/twitch.",
                ephemeral=True)
            return
        code = self.store.create_link_code(interaction.user.id, str(interaction.user), login, time.time())
        await interaction.response.send_message(
            f"Schreibe als **{login}** in einem Twitch-Chat mit Yami:\n`!link {code}`\n"
            "Der Code gilt 10 Minuten und nur für diesen Twitch-Login. Bei einem anderen Chat-Präfix ersetze `!`.\n"
            "Danach nutzt Twitch dein Discord-Guthaben und dasselbe Daily. Deine bisherigen Channel-Coins bleiben separat gespeichert.",
            ephemeral=True)


async def setup(bot):
    await bot.add_cog(TwitchLinkCog(bot))

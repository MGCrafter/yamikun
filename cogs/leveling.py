"""Leveling-System: XP aus Nachrichten und Voice, Coins als Level-Belohnung.

- XP pro Nachricht: zufällig zwischen XP_MIN und XP_MAX, mit Cooldown gegen Spam.
- XP pro Voice-Minute: VOICE_XP, solange man sinnvoll in einem Sprachkanal ist.
- Level-Kurve (MEE6-ähnlich): XP von Level n zu n+1 = 5·n² + 50·n + 100.
- Beim Level-Up gibt es COINS_PER_LEVEL · neues Level Coins.
- Level-Up-Meldungen gehen in einen konfigurierbaren Channel.
"""

from __future__ import annotations

import logging
import os
import random
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

logger = logging.getLogger("oaken-tower-bot")

# --- Einstellbare Werte -------------------------------------------------------
XP_MIN: int = 15
XP_MAX: int = 25
MESSAGE_COOLDOWN: float = 60.0       # Sekunden zwischen zwei XP-vergebenden Nachrichten
VOICE_XP: int = 5                    # XP pro Minute in Voice
COINS_PER_LEVEL: int = 100           # Coins beim Level-Up = COINS_PER_LEVEL · neues Level
COIN_EMOJI_NAME: str = "YamiToken"   # Custom-Emoji-Name für die Währung
COIN_FALLBACK: str = "🪙"


def xp_needed(level: int) -> int:
    """XP, die nötig sind, um von `level` auf `level + 1` zu kommen."""
    return 5 * (level**2) + 50 * level + 100


def level_from_total(total_xp: int) -> tuple[int, int]:
    """Errechnet (Level, XP innerhalb des aktuellen Levels) aus der Gesamt-XP."""
    level = 0
    remaining = total_xp
    while remaining >= xp_needed(level):
        remaining -= xp_needed(level)
        level += 1
    return level, remaining


LEVELUP_PLACEHOLDERS = ["{user}", "{user_name}", "{level}", "{coins}", "{server}"]


def render_levelup(
    template: str, member: discord.Member, level: int, coins_gained: int, server_name: str
) -> str:
    """Platzhalter im eigenen Level-Up-Text ersetzen (per replace, nie str.format)."""
    repl = {
        "{user}": member.mention,
        "{user_name}": member.display_name,
        "{level}": str(level),
        "{coins}": f"{coins_gained:,}".replace(",", "."),
        "{server}": server_name,
    }
    text = template
    for key, value in repl.items():
        text = text.replace(key, value)
    return text


class LevelingCog(commands.Cog):
    """XP/Level/Coins-Verwaltung samt Commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]
        self.voice_xp_loop.start()

    def cog_unload(self) -> None:
        self.voice_xp_loop.cancel()

    # --- Hilfen ---------------------------------------------------------------

    def coin(self, guild: discord.Guild | None) -> str:
        """Gibt das Coin-Emoji des Servers zurück (Fallback: 🪙)."""
        if guild is not None:
            emoji = discord.utils.get(guild.emojis, name=COIN_EMOJI_NAME)
            if emoji is not None:
                return str(emoji)
        return COIN_FALLBACK

    async def _award_xp(
        self, guild: discord.Guild, member: discord.Member, amount: int
    ) -> None:
        """Schreibt XP gut, behandelt Level-Ups inkl. Coins und Ankündigung."""
        # Aktiver XP-Boost aus dem Shop verdoppelt die XP.
        if self.db.get_expires(guild.id, member.id, "xpboost") > time.time():
            amount *= 2
        row = self.db.get_user(guild.id, member.id)
        old_level = int(row["level"])
        new_total = int(row["xp"]) + amount
        new_level, _ = level_from_total(new_total)

        coins = int(row["coins"])
        if new_level > old_level:
            gained = sum(COINS_PER_LEVEL * lvl for lvl in range(old_level + 1, new_level + 1))
            coins += gained
            self.db.update_user(
                guild.id, member.id, xp=new_total, level=new_level, coins=coins
            )
            await self._announce_levelup(guild, member, new_level, gained, coins)
        else:
            self.db.update_user(
                guild.id, member.id, xp=new_total, level=new_level, coins=coins
            )

    async def _announce_levelup(
        self,
        guild: discord.Guild,
        member: discord.Member,
        new_level: int,
        coins_gained: int,
        new_balance: int,
    ) -> None:
        cfg = self.db.get_levelup_config(guild.id)
        channel_id = cfg["channel_id"]
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            return
        # Ping steuert nur, ob eine Benachrichtigung ausgelöst wird — die Erwähnung
        # bleibt als Text sichtbar, wird aber bei "aus" nicht zugestellt.
        ping = cfg["ping"]
        mentions = (
            discord.AllowedMentions(users=True, everyone=False, roles=False)
            if ping else discord.AllowedMentions.none()
        )

        custom = (cfg["message"] or "").strip()
        if custom:
            text = render_levelup(custom, member, new_level, coins_gained, guild.name)
            try:
                await channel.send(content=text, allowed_mentions=mentions)
            except discord.Forbidden:
                logger.warning("Keine Berechtigung für Level-Up-Meldung in Channel %s.", channel_id)
            return

        coin = self.coin(guild)
        coins_fmt = f"{coins_gained:,}".replace(",", ".")
        balance_fmt = f"{new_balance:,}".replace(",", ".")

        embed = discord.Embed(
            title=f"🏆  Level {new_level} erreicht",
            description=f"**{member.display_name}** ist aufgestiegen!",
            color=0xA3E635,
        )
        embed.set_author(name="✦  LEVEL UP", icon_url=member.display_avatar.url)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="📈 Level", value=f"**{new_level}**", inline=True)
        embed.add_field(name="💰 Belohnung", value=f"+{coins_fmt} {coin}", inline=True)
        embed.add_field(name="💎 Kontostand", value=f"{balance_fmt} {coin}", inline=True)
        embed.set_footer(text="Bleib aktiv — jede Nachricht & Voice-Minute bringt XP.")

        try:
            await channel.send(
                content=member.mention if ping else None, embed=embed, allowed_mentions=mentions,
            )
        except discord.Forbidden:
            logger.warning("Keine Berechtigung für Level-Up-Meldung in Channel %s.", channel_id)

    # --- XP aus Nachrichten ---------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        row = self.db.get_user(message.guild.id, message.author.id)
        now = time.time()
        if now - float(row["last_msg_ts"]) < MESSAGE_COOLDOWN:
            return
        # Cooldown-Zeitstempel zuerst setzen, dann XP vergeben.
        self.db.update_user(
            message.guild.id,
            message.author.id,
            xp=int(row["xp"]),
            level=int(row["level"]),
            coins=int(row["coins"]),
            last_msg_ts=now,
        )
        await self._award_xp(
            message.guild, message.author, random.randint(XP_MIN, XP_MAX)
        )

    # --- XP aus Voice ---------------------------------------------------------

    @tasks.loop(minutes=1.0)
    async def voice_xp_loop(self) -> None:
        """Vergibt jede Minute XP an aktive Voice-Teilnehmer."""
        for guild in self.bot.guilds:
            afk_channel_id = guild.afk_channel.id if guild.afk_channel else None
            for vc in guild.voice_channels:
                if vc.id == afk_channel_id:
                    continue
                humans = [m for m in vc.members if not m.bot]
                if len(humans) < 2:
                    continue  # allein im Channel → keine XP
                for member in humans:
                    state = member.voice
                    if state and (state.self_deaf or state.deaf):
                        continue  # taub gestellt → nicht „aktiv"
                    await self._award_xp(guild, member, VOICE_XP)

    @voice_xp_loop.before_loop
    async def _before_voice_loop(self) -> None:
        await self.bot.wait_until_ready()

    # --- Öffentliche Commands -------------------------------------------------

    @app_commands.command(name="rank", description="Zeigt Level, XP-Fortschritt und Coins.")
    @app_commands.guild_only()
    @app_commands.describe(user="Wessen Rang? (Standard: du selbst)")
    async def rank(
        self, interaction: discord.Interaction, user: discord.Member | None = None
    ) -> None:
        target = user or interaction.user
        row = self.db.get_user(interaction.guild_id, target.id)
        level, into_level = level_from_total(int(row["xp"]))
        need = xp_needed(level)
        coin = self.coin(interaction.guild)

        embed = discord.Embed(color=0xA3E635)
        embed.set_author(name="✦  RANG", icon_url=target.display_avatar.url if isinstance(target, discord.Member) else None)
        embed.title = target.display_name
        embed.add_field(name="📈 Level", value=f"**{level}**", inline=True)
        embed.add_field(name="⚡ XP", value=f"{into_level} / {need}", inline=True)
        embed.add_field(name="💎 Coins", value=f"{int(row['coins'])} {coin}", inline=True)
        embed.set_footer(text=f"Gesamt-XP: {int(row['xp'])}")
        if isinstance(target, discord.Member):
            embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="leaderboard", description="Zeigt die Top 10 Mitglieder nach Gesamt-XP.")
    @app_commands.guild_only()
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        rows = self.db.leaderboard(interaction.guild_id, limit=10)
        if not rows:
            await interaction.response.send_message(
                "Noch keine XP gesammelt.", ephemeral=True
            )
            return
        coin = self.coin(interaction.guild)
        lines = []
        for i, r in enumerate(rows, start=1):
            member = interaction.guild.get_member(int(r["user_id"]))
            name = member.display_name if member else f"User {r['user_id']}"
            lines.append(
                f"**{i}.** {name} — Level {int(r['level'])} "
                f"({int(r['xp'])} XP, {int(r['coins'])} {coin})"
            )
        embed = discord.Embed(
            title="🏆  Leaderboard", description="\n".join(lines), color=0xA3E635
        )
        embed.set_footer(text="Top 10 nach XP · serverübergreifend")
        await interaction.response.send_message(embed=embed)

    # --- Mod-Befehlsgruppe /level ---------------------------------------------

    level = app_commands.Group(
        name="level",
        description="Leveling-Verwaltung (nur Mods).",
        guild_only=True,
        default_permissions=discord.Permissions(manage_channels=True),
    )

    @level.command(name="setchannel", description="Setzt den Channel für Level-Up-Meldungen.")
    @app_commands.describe(channel="Zielchannel für Level-Up-Ankündigungen")
    async def level_setchannel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        self.db.set_levelup_channel(interaction.guild_id, channel.id)
        logger.info("Level-Up-Channel in Guild %s gesetzt: %s", interaction.guild_id, channel.id)
        await interaction.response.send_message(
            f"✅ Level-Up-Meldungen erscheinen jetzt in {channel.mention}.", ephemeral=True
        )

    @level.command(
        name="message",
        description="Eigener Level-Up-Text (leer = Standard-Embed).",
    )
    @app_commands.describe(
        text="Platzhalter: {user} {user_name} {level} {coins} {server}. Leer lassen = Standard.",
    )
    async def level_message(self, interaction: discord.Interaction, text: str = "") -> None:
        msg = text.strip() or None
        self.db.set_levelup_message(interaction.guild_id, msg)
        if msg:
            preview = render_levelup(msg, interaction.user, 5, 500, interaction.guild.name)
            await interaction.response.send_message(
                f"✅ Eigener Level-Up-Text gesetzt. Vorschau:\n>>> {preview}",
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            await interaction.response.send_message(
                "✅ Level-Up-Text zurückgesetzt — es wird wieder das Standard-Embed verwendet.",
                ephemeral=True,
            )

    @level.command(name="ping", description="Soll der User beim Level-Up gepingt werden?")
    @app_commands.describe(aktiv="An = User wird benachrichtigt, Aus = stille Meldung.")
    async def level_ping(self, interaction: discord.Interaction, aktiv: bool) -> None:
        self.db.set_levelup_ping(interaction.guild_id, aktiv)
        await interaction.response.send_message(
            f"✅ Level-Up-Ping ist jetzt **{'an' if aktiv else 'aus'}**.", ephemeral=True
        )

    @level.command(name="coins", description="Vergibt oder entzieht Coins eines Users.")
    @app_commands.describe(user="Empfänger", amount="Anzahl Coins (auch negativ möglich)")
    async def level_coins(
        self, interaction: discord.Interaction, user: discord.Member, amount: int
    ) -> None:
        raw_owners = os.environ.get("WEB_OWNER_IDS", "").replace(" ", "")
        owner_ids = {int(value) for value in raw_owners.split(",") if value.isdigit()}
        if interaction.user.id not in owner_ids:
            await interaction.response.send_message(
                "⛔ Nur globale Owner dürfen Guthaben ändern.", ephemeral=True,
            )
            return
        new_balance = self.db.add_coins(interaction.guild_id, user.id, amount)
        coin = self.coin(interaction.guild)
        await interaction.response.send_message(
            f"✅ {user.mention} hat jetzt **{new_balance} {coin}** "
            f"({'+' if amount >= 0 else ''}{amount}).",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LevelingCog(bot))

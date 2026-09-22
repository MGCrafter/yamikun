"""Moderations-Befehle. Aktuell: /purge zum Aufräumen von Channels."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import re
import time

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("oaken-tower-bot")

MAX_PURGE = 100         # Discord-Limit für komfortables Bulk-Delete
SCAN_FACTOR = 10        # bei User-Filter so viel mehr Verlauf durchsuchen
SCAN_CAP = 1000

AUTO_MOD_DEFAULTS = {
    "new_member_join_minutes": 10,
    "new_member_account_hours": 24,
    "repeat_threshold": 3,
    "repeat_window_seconds": 20,
    "burst_threshold": 5,
    "burst_window_seconds": 10,
}

_MENTION_REPLACEMENTS = (
    (re.compile(r"<@!?\d+>"), "@user"),
    (re.compile(r"<@&\d+>"), "@role"),
    (re.compile(r"<#\d+>"), "#channel"),
)
_SPACE_RE = re.compile(r"\s+")
_MASS_MENTION_RE = re.compile(r"(?<!\S)@(everyone|here)\b", re.IGNORECASE)


def normalize_automod_content(content: str) -> str:
    """Normalisiert Nachrichtentext für Anti-Spam-Vergleiche."""
    normalized = content.strip().lower()
    for pattern, replacement in _MENTION_REPLACEMENTS:
        normalized = pattern.sub(replacement, normalized)
    return _SPACE_RE.sub(" ", normalized)


def contains_mass_mention(content: str) -> bool:
    """Erkennt echte @everyone/@here-Massenpings im User-Text."""
    return bool(_MASS_MENTION_RE.search(content))


def automod_should_ignore_member(member: discord.Member, exempt_role_ids: list[int]) -> bool:
    """Admins, Mods und konfigurierte Rollen werden vom AutoMod ignoriert."""
    perms = getattr(member, "guild_permissions", None)
    if perms and (perms.administrator or perms.manage_messages or perms.manage_guild):
        return True
    exempt = {int(role_id) for role_id in exempt_role_ids}
    return any(getattr(role, "id", None) in exempt for role in getattr(member, "roles", []))


def clamp_honeypot_delete_seconds(value: int) -> int:
    """Discord erlaubt beim Ban maximal 7 Tage Nachrichtenspanne."""
    return min(604800, max(0, int(value)))


@dataclass(frozen=True)
class AutomodDecision:
    reasons: list[str]

    @property
    def should_delete(self) -> bool:
        return bool(self.reasons)


class AutomodState:
    """Kleiner In-Memory-Zustand für Rolling-Window-Spam-Erkennung."""

    def __init__(
        self,
        *,
        new_member_join_minutes: int = AUTO_MOD_DEFAULTS["new_member_join_minutes"],
        new_member_account_hours: int = AUTO_MOD_DEFAULTS["new_member_account_hours"],
        repeat_threshold: int = AUTO_MOD_DEFAULTS["repeat_threshold"],
        repeat_window_seconds: int = AUTO_MOD_DEFAULTS["repeat_window_seconds"],
        burst_threshold: int = AUTO_MOD_DEFAULTS["burst_threshold"],
        burst_window_seconds: int = AUTO_MOD_DEFAULTS["burst_window_seconds"],
    ) -> None:
        self.new_member_join_minutes = new_member_join_minutes
        self.new_member_account_hours = new_member_account_hours
        self.repeat_threshold = repeat_threshold
        self.repeat_window_seconds = repeat_window_seconds
        self.burst_threshold = burst_threshold
        self.burst_window_seconds = burst_window_seconds
        self._messages: dict[tuple[int, int], deque[tuple[float, str]]] = defaultdict(deque)

    def is_new_member(
        self,
        *,
        joined_at: datetime | None,
        created_at: datetime | None,
        now: datetime | None = None,
    ) -> bool:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)

        if joined_at is not None:
            joined = joined_at if joined_at.tzinfo else joined_at.replace(tzinfo=timezone.utc)
            if current - joined <= timedelta(minutes=self.new_member_join_minutes):
                return True
        if created_at is not None:
            created = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
            if current - created <= timedelta(hours=self.new_member_account_hours):
                return True
        return False

    def record_message(
        self,
        guild_id: int,
        user_id: int,
        content: str,
        *,
        now: float | None = None,
        is_new_member: bool,
    ) -> AutomodDecision:
        current = time.time() if now is None else now
        key = (int(guild_id), int(user_id))
        normalized = normalize_automod_content(content)
        window = self._messages[key]
        max_window = max(self.repeat_window_seconds, self.burst_window_seconds)
        while window and current - window[0][0] > max_window:
            window.popleft()
        window.append((current, normalized))

        reasons: list[str] = []
        repeat_count = sum(
            1 for ts, text in window
            if text == normalized and current - ts <= self.repeat_window_seconds
        )
        if normalized and repeat_count >= self.repeat_threshold:
            reasons.append("repeat_spam")

        burst_count = sum(1 for ts, _ in window if current - ts <= self.burst_window_seconds)
        if is_new_member and burst_count >= self.burst_threshold:
            reasons.append("new_member_burst")

        return AutomodDecision(reasons)


class ModerationCog(commands.Cog):
    """Moderationswerkzeuge: Verwarnungen, AutoMod, Purge und Say."""

    automod = app_commands.Group(
        name="automod",
        description="Anti-Spam, neue User und Massenpings verwalten.",
        guild_only=True,
        default_permissions=discord.Permissions(manage_messages=True),
    )

    warn = app_commands.Group(
        name="warn",
        description="Verwarnungen eines Mitglieds verwalten.",
        guild_only=True,
        default_permissions=discord.Permissions(moderate_members=True),
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = getattr(bot, "db")
        self.automod_state = AutomodState()

    async def _log_moderation_action(
        self,
        guild: discord.Guild,
        event_type: str,
        summary: str,
        *,
        actor: discord.Member,
        target: discord.Member | None = None,
        channel: discord.abc.GuildChannel | None = None,
        detail: str | None = None,
    ) -> None:
        """Schreibt ins Web-Audit und sendet dasselbe Ereignis in den Audit-Channel."""
        audit = self.bot.get_cog("AuditCog")
        if audit is not None and hasattr(audit, "log"):
            await audit.log(  # type: ignore[attr-defined]
                guild,
                "members",
                event_type,
                summary,
                actor=actor,
                target=target,
                channel=channel,
                detail=detail,
            )
            return
        self.db.add_audit_log(
            guild.id,
            "members",
            event_type,
            summary,
            actor_id=actor.id,
            target_id=target.id if target else None,
            channel_id=channel.id if channel else None,
            detail=detail,
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        if not isinstance(message.author, discord.Member):
            return

        config = self.db.get_automod_config(message.guild.id)
        if not config["enabled"]:
            return
        if automod_should_ignore_member(message.author, list(config["exempt_role_ids"])):
            return

        if message.channel.id in set(config["honeypot_channel_ids"]):
            await self._handle_honeypot_message(message, config)
            return

        reasons: list[str] = []
        if config["delete_mass_mentions"] and contains_mass_mention(message.content):
            reasons.append("mass_mention")

        is_new = self.automod_state.is_new_member(
            joined_at=message.author.joined_at,
            created_at=message.author.created_at,
        )
        decision = self.automod_state.record_message(
            message.guild.id,
            message.author.id,
            message.content,
            is_new_member=is_new,
        )
        reasons.extend(reason for reason in decision.reasons if reason not in reasons)

        if reasons:
            await self._delete_and_flag(message, reasons)

    async def _handle_honeypot_message(self, message: discord.Message, config: dict) -> None:
        guild = message.guild
        if guild is None:
            return
        delete_seconds = clamp_honeypot_delete_seconds(config["honeypot_delete_seconds"])
        channel_id_for_log = getattr(message.channel, "id", None)
        detail = message.content[:900]

        try:
            await message.delete()
        except discord.Forbidden:
            logger.warning(
                "Honeypot konnte Nachricht %s in Channel %s nicht löschen: Missing Permissions.",
                message.id, channel_id_for_log,
            )
        except discord.HTTPException as exc:
            logger.warning("Honeypot-Löschung fehlgeschlagen (%s): %s", message.id, exc)

        action = "honeypot_delete"
        summary = f"Honeypot: Nachricht von {message.author} gelöscht."
        if config["honeypot_ban"]:
            try:
                await guild.ban(
                    message.author,
                    reason="Honeypot spam protection: wrote in protected channel",
                    delete_message_seconds=delete_seconds,
                )
                action = "honeypot_ban"
                summary = (
                    f"Honeypot: {message.author} gebannt; Nachrichten der letzten "
                    f"{delete_seconds // 3600}h gelöscht."
                )
            except discord.Forbidden:
                logger.warning("Honeypot-Ban fehlgeschlagen: Missing Permissions für User %s.", message.author.id)
                summary = f"Honeypot: Nachricht von {message.author} gelöscht, Ban fehlgeschlagen."
            except discord.HTTPException as exc:
                logger.warning("Honeypot-Ban fehlgeschlagen (%s): %s", message.author.id, exc)
                summary = f"Honeypot: Nachricht von {message.author} gelöscht, Ban fehlgeschlagen."

        self.db.add_audit_log(
            guild.id,
            "members",
            action,
            summary,
            actor_id=self.bot.user.id if self.bot.user else None,
            target_id=message.author.id,
            channel_id=channel_id_for_log,
            detail=detail,
        )
        await self._send_automod_log(message, "honeypot", detail, summary)
        logger.info(summary)

    async def _send_automod_log(
        self,
        message: discord.Message,
        reason_text: str,
        detail: str,
        summary: str | None = None,
    ) -> None:
        guild = message.guild
        if guild is None:
            return
        channel_id = self.db.get_audit_channel(guild.id)
        if channel_id is None:
            return
        channel = self.bot.get_channel(channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        embed = discord.Embed(
            title="🛡️ AutoMod-Flag",
            description=summary or f"Nachricht von {message.author.mention} gelöscht.",
            color=0xF97316,
        )
        channel_mention = getattr(message.channel, "mention", f"#{getattr(message.channel, 'id', '?')}")
        embed.add_field(name="Grund", value=reason_text, inline=False)
        embed.add_field(name="Channel", value=channel_mention, inline=True)
        embed.add_field(name="User-ID", value=str(message.author.id), inline=True)
        if detail:
            embed.add_field(name="Inhalt", value=detail[:1024], inline=False)
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            logger.warning("AutoMod-Audit-Meldung in Channel %s fehlgeschlagen.", channel_id)

    async def _delete_and_flag(self, message: discord.Message, reasons: list[str]) -> None:
        reason_text = ", ".join(reasons)
        try:
            await message.delete()
        except discord.Forbidden:
            logger.warning(
                "AutoMod konnte Nachricht %s in Channel %s nicht löschen: Missing Permissions.",
                message.id, getattr(message.channel, "id", "?"),
            )
            return
        except discord.HTTPException as exc:
            logger.warning("AutoMod-Löschung fehlgeschlagen (%s): %s", message.id, exc)
            return

        guild = message.guild
        if guild is None:
            return
        channel_id_for_log = getattr(message.channel, "id", None)
        summary = f"AutoMod: Nachricht von {message.author} gelöscht ({reason_text})."
        detail = message.content[:900]
        self.db.add_audit_log(
            guild.id,
            "messages",
            "automod_delete",
            summary,
            actor_id=self.bot.user.id if self.bot.user else None,
            target_id=message.author.id,
            channel_id=channel_id_for_log,
            detail=detail,
        )
        logger.info(summary)

        channel_id = self.db.get_audit_channel(guild.id)
        if channel_id is None:
            return
        channel = self.bot.get_channel(channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        embed = discord.Embed(
            title="🛡️ AutoMod-Flag",
            description=f"Nachricht von {message.author.mention} gelöscht.",
            color=0xF97316,
        )
        channel_mention = getattr(message.channel, "mention", f"#{channel_id_for_log}")
        embed.add_field(name="Grund", value=reason_text, inline=False)
        embed.add_field(name="Channel", value=channel_mention, inline=True)
        embed.add_field(name="User-ID", value=str(message.author.id), inline=True)
        if detail:
            embed.add_field(name="Inhalt", value=detail[:1024], inline=False)
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            logger.warning("AutoMod-Audit-Meldung in Channel %s fehlgeschlagen.", channel_id)

    @app_commands.command(
        name="purge",
        description="Löscht die letzten Nachrichten im Channel (optional nur von einem User).",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(
        anzahl="Wie viele Nachrichten löschen (1–100)",
        user="Optional: nur Nachrichten dieses Users löschen",
    )
    async def purge(
        self,
        interaction: discord.Interaction,
        anzahl: app_commands.Range[int, 1, MAX_PURGE],
        user: discord.Member | None = None,
    ) -> None:
        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            await interaction.response.send_message(
                "⚠️ In diesem Channel-Typ kann ich nicht löschen.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        matched = 0

        def check(message: discord.Message) -> bool:
            nonlocal matched
            if matched >= anzahl:
                return False
            if user is not None and message.author.id != user.id:
                return False
            matched += 1
            return True

        # Ohne Filter genau `anzahl` Nachrichten; mit Filter mehr Verlauf scannen.
        scan = anzahl if user is None else min(anzahl * SCAN_FACTOR, SCAN_CAP)
        try:
            deleted = await channel.purge(limit=scan, check=check, bulk=True)
        except discord.Forbidden:
            await interaction.followup.send(
                "⚠️ Mir fehlt die Berechtigung **Nachrichten verwalten** in diesem Channel.",
                ephemeral=True,
            )
            return
        except discord.HTTPException as exc:
            await interaction.followup.send(
                f"⚠️ Löschen fehlgeschlagen: {exc}. "
                "(Nachrichten älter als 14 Tage lassen sich nicht massenweise löschen.)",
                ephemeral=True,
            )
            return

        suffix = f" von {user.mention}" if user else ""
        logger.info(
            "Purge in Channel %s durch %s: %d Nachricht(en) gelöscht.",
            channel.id, interaction.user.id, len(deleted),
        )
        await interaction.followup.send(
            f"🧹 **{len(deleted)}** Nachricht(en){suffix} gelöscht.", ephemeral=True
        )

    @app_commands.command(name="say", description="Lässt den Bot eine Nachricht schreiben.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(
        text="Was soll der Bot sagen? Tippe \\n für einen Zeilenumbruch (\\n\\n = Leerzeile).",
        channel="Optional: Zielchannel",
    )
    async def say(
        self,
        interaction: discord.Interaction,
        text: str,
        channel: discord.TextChannel | None = None,
    ) -> None:
        target = channel or interaction.channel
        # Slash-Eingaben sind einzeilig: literales \n (und \r\n) in echte Umbrüche wandeln.
        text = text.replace("\\r\\n", "\n").replace("\\n", "\n")
        try:
            # @everyone/@here bewusst sperren (kein Massen-Ping über den Bot).
            await target.send(text, allowed_mentions=discord.AllowedMentions(everyone=False))
        except discord.Forbidden:
            await interaction.response.send_message(
                "⚠️ Mir fehlt die Berechtigung, in diesem Channel zu schreiben.", ephemeral=True
            )
            return
        logger.info("Say von %s in Channel %s: %s", interaction.user.id, target.id, text[:120])
        await interaction.response.send_message(f"✅ Gesendet in {target.mention}.", ephemeral=True)

    @warn.command(name="add", description="Verwarnt ein Mitglied und speichert den Grund.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(user="Mitglied, das verwarnt werden soll", grund="Grund der Verwarnung")
    async def warn_add(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        grund: app_commands.Range[str, 1, 1000],
    ) -> None:
        if user.bot or user.id == interaction.user.id:
            await interaction.response.send_message(
                "⛔ Bots und dich selbst kannst du nicht verwarnen.", ephemeral=True
            )
            return
        guild = interaction.guild
        moderator = interaction.user
        if guild is None or not isinstance(moderator, discord.Member):
            await interaction.response.send_message(
                "⛔ Dieser Befehl funktioniert nur auf einem Server.", ephemeral=True
            )
            return
        if user.id == guild.owner_id or (
            moderator.id != guild.owner_id and user.top_role >= moderator.top_role
        ):
            await interaction.response.send_message(
                "⛔ Dieses Mitglied steht in der Rollen-Hierarchie gleich hoch oder höher als du.",
                ephemeral=True,
            )
            return

        warning = self.db.add_warning(
            guild.id, user.id, moderator.id, str(grund), created_at=time.time()
        )
        count = len(self.db.list_warnings(guild.id, user.id))
        warning_id = int(warning["id"])
        reason = str(warning["reason"])
        await self._log_moderation_action(
            guild,
            "warning_add",
            f"⚠️ **{moderator}** verwarnte **{user}** (Warnung #{warning_id})",
            actor=moderator,
            target=user,
            channel=interaction.channel if isinstance(interaction.channel, discord.abc.GuildChannel) else None,
            detail=f"Grund: {reason}",
        )

        dm_delivered = True
        dm_embed = discord.Embed(
            title="⚠️ Du wurdest verwarnt",
            description=f"Du hast auf **{guild.name}** eine Verwarnung erhalten.",
            color=0xF59E0B,
        )
        dm_embed.add_field(name="Grund", value=reason, inline=False)
        dm_embed.add_field(name="Verwarnung", value=f"#{warning_id} · insgesamt {count}", inline=False)
        dm_embed.set_footer(text="Bitte halte dich künftig an die Serverregeln.")
        try:
            await user.send(embed=dm_embed)
        except (discord.Forbidden, discord.HTTPException):
            dm_delivered = False

        dm_note = (
            "Die Person wurde per DM informiert."
            if dm_delivered
            else "Eine DM konnte nicht zugestellt werden."
        )
        await interaction.response.send_message(
            f"✅ {user.mention} wurde verwarnt. **ID #{warning_id}** · "
            f"Verwarnungen: **{count}**\n{dm_note}",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @warn.command(name="list", description="Zeigt die Verwarnungen eines Mitglieds.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(user="Mitglied, dessen Verwarnungen du sehen möchtest")
    async def warn_list(self, interaction: discord.Interaction, user: discord.Member) -> None:
        rows = self.db.list_warnings(interaction.guild_id, user.id)
        if not rows:
            await interaction.response.send_message(
                f"✅ {user.mention} hat keine Verwarnungen.", ephemeral=True
            )
            return
        lines = [
            f"**#{row['id']}** · <t:{int(row['created_at'])}:d> · <@{row['moderator_id']}>\n"
            f"{row['reason']}"
            for row in rows[:10]
        ]
        embed = discord.Embed(
            title=f"⚠️ Verwarnungen von {user.display_name}",
            description="\n\n".join(lines),
            color=0xF59E0B,
        )
        if len(rows) > 10:
            embed.set_footer(
                text=f"Die 10 neuesten von insgesamt {len(rows)} Verwarnungen werden angezeigt."
            )
        else:
            embed.set_footer(text=f"Insgesamt {len(rows)} Verwarnung(en).")
        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @warn.command(name="remove", description="Entfernt eine Verwarnung anhand ihrer ID.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(warn_id="ID aus /warn list")
    async def warn_remove(self, interaction: discord.Interaction, warn_id: int) -> None:
        row = self.db.remove_warning(interaction.guild_id, warn_id)
        if row is None:
            await interaction.response.send_message(
                "⚠️ Auf diesem Server gibt es keine Verwarnung mit dieser ID.", ephemeral=True
            )
            return
        guild = interaction.guild
        moderator = interaction.user
        target = guild.get_member(int(row["user_id"])) if guild else None
        if guild is not None and isinstance(moderator, discord.Member):
            await self._log_moderation_action(
                guild,
                "warning_remove",
                f"♻️ **{moderator}** entfernte Verwarnung #{warn_id} für <@{row['user_id']}>",
                actor=moderator,
                target=target,
                channel=(
                    interaction.channel
                    if isinstance(interaction.channel, discord.abc.GuildChannel)
                    else None
                ),
                detail=f"Vorheriger Grund: {row['reason']}",
            )
        await interaction.response.send_message(
            f"✅ Verwarnung **#{warn_id}** wurde entfernt.", ephemeral=True
        )

    @warn.command(name="clear", description="Entfernt alle Verwarnungen eines Mitglieds.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(user="Mitglied, dessen Verwarnungen gelöscht werden sollen")
    async def warn_clear(self, interaction: discord.Interaction, user: discord.Member) -> None:
        removed = self.db.clear_warnings(interaction.guild_id, user.id)
        if removed:
            guild = interaction.guild
            moderator = interaction.user
            if guild is not None and isinstance(moderator, discord.Member):
                await self._log_moderation_action(
                    guild,
                    "warning_clear",
                    f"🧹 **{moderator}** entfernte alle {removed} Verwarnung(en) von **{user}**",
                    actor=moderator,
                    target=user,
                    channel=(
                        interaction.channel
                        if isinstance(interaction.channel, discord.abc.GuildChannel)
                        else None
                    ),
                )
        await interaction.response.send_message(
            f"✅ **{removed}** Verwarnung(en) von {user.mention} entfernt.",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @automod.command(name="status", description="Zeigt die aktuelle AutoMod-Konfiguration.")
    async def automod_status(self, interaction: discord.Interaction) -> None:
        config = self.db.get_automod_config(interaction.guild_id)
        roles = config["exempt_role_ids"]
        role_text = ", ".join(f"<@&{rid}>" for rid in roles) if roles else "keine"
        honeypot_channels = config["honeypot_channel_ids"]
        honeypot_text = ", ".join(f"<#{cid}>" for cid in honeypot_channels) if honeypot_channels else "keine"
        status = "an" if config["enabled"] else "aus"
        mentions = "an" if config["delete_mass_mentions"] else "aus"
        await interaction.response.send_message(
            "🛡️ **AutoMod**\n"
            f"Status: **{status}**\n"
            f"@everyone/@here löschen: **{mentions}**\n"
            f"Honeypot-Channels: {honeypot_text}\n"
            f"Honeypot-Ban: **{'an' if config['honeypot_ban'] else 'aus'}**, "
            f"Nachrichten löschen: **{config['honeypot_delete_seconds'] // 3600}h**\n"
            f"Gleiche Nachricht: {config['repeat_threshold']}x in {config['repeat_window_seconds']}s\n"
            f"Neue User: Join < {config['new_member_join_minutes']} min oder Account < "
            f"{config['new_member_account_hours']} h; Burst ab "
            f"{config['burst_threshold']} Nachrichten in {config['burst_window_seconds']}s\n"
            f"Ausgenommene Rollen: {role_text}",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @automod.command(name="enabled", description="Schaltet AutoMod an oder aus.")
    @app_commands.describe(aktiv="An = Spam/Massenpings löschen, Aus = nur normale Moderation")
    async def automod_enabled(self, interaction: discord.Interaction, aktiv: bool) -> None:
        self.db.set_automod_enabled(interaction.guild_id, aktiv)
        await interaction.response.send_message(
            f"✅ AutoMod ist jetzt **{'an' if aktiv else 'aus'}**.", ephemeral=True
        )

    @automod.command(
        name="massmentions",
        description="Schaltet das Löschen von @everyone/@here für normale User.",
    )
    @app_commands.describe(aktiv="An = @everyone/@here löschen, Aus = nicht anfassen")
    async def automod_massmentions(self, interaction: discord.Interaction, aktiv: bool) -> None:
        self.db.set_automod_mass_mentions(interaction.guild_id, aktiv)
        await interaction.response.send_message(
            f"✅ @everyone/@here-Unterdrückung ist jetzt **{'an' if aktiv else 'aus'}**.",
            ephemeral=True,
        )

    @automod.command(name="exempt_add", description="Nimmt eine Rolle vom AutoMod aus.")
    @app_commands.describe(role="Rolle, die AutoMod ignorieren soll")
    async def automod_exempt_add(self, interaction: discord.Interaction, role: discord.Role) -> None:
        roles = self.db.add_automod_exempt_role(interaction.guild_id, role.id)
        await interaction.response.send_message(
            f"✅ {role.mention} ist ausgenommen. Insgesamt: **{len(roles)}** Rolle(n).",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @automod.command(name="exempt_remove", description="Entfernt eine Ausnahme-Rolle vom AutoMod.")
    @app_commands.describe(role="Rolle, die nicht mehr ausgenommen sein soll")
    async def automod_exempt_remove(self, interaction: discord.Interaction, role: discord.Role) -> None:
        roles = self.db.remove_automod_exempt_role(interaction.guild_id, role.id)
        await interaction.response.send_message(
            f"✅ {role.mention} ist nicht mehr ausgenommen. Übrig: **{len(roles)}** Rolle(n).",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    @automod.command(
        name="honeypot_add",
        description="Fügt einen Honeypot-Channel hinzu: Wer dort schreibt, wird automatisch gebannt.",
    )
    @app_commands.describe(channel="Channel, in dem normale User nicht schreiben sollen")
    async def automod_honeypot_add(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ) -> None:
        channels = self.db.add_automod_honeypot_channel(interaction.guild_id, channel.id)
        await interaction.response.send_message(
            f"✅ {channel.mention} ist jetzt ein Honeypot-Channel. Insgesamt: **{len(channels)}** Channel.",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @automod.command(name="honeypot_remove", description="Entfernt einen Honeypot-Channel.")
    @app_commands.describe(channel="Channel, der nicht mehr als Honeypot dienen soll")
    async def automod_honeypot_remove(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ) -> None:
        channels = self.db.remove_automod_honeypot_channel(interaction.guild_id, channel.id)
        await interaction.response.send_message(
            f"✅ {channel.mention} ist kein Honeypot-Channel mehr. Übrig: **{len(channels)}** Channel.",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @automod.command(name="honeypot_config", description="Konfiguriert Ban und Nachrichtenlöschung für Honeypots.")
    @app_commands.describe(
        ban="An = User automatisch bannen; Aus = nur Nachricht löschen und loggen",
        delete_days="Nachrichten der letzten X Tage beim Ban löschen (0–7)",
    )
    async def automod_honeypot_config(
        self,
        interaction: discord.Interaction,
        ban: bool,
        delete_days: app_commands.Range[int, 0, 7] = 7,
    ) -> None:
        config = self.db.get_automod_config(interaction.guild_id)
        delete_seconds = clamp_honeypot_delete_seconds(delete_days * 24 * 60 * 60)
        self.db.set_automod_honeypot(
            interaction.guild_id,
            channel_ids=list(config["honeypot_channel_ids"]),
            ban=ban,
            delete_seconds=delete_seconds,
        )
        await interaction.response.send_message(
            f"✅ Honeypot: Ban **{'an' if ban else 'aus'}**, Nachrichtenlöschung **{delete_days} Tag(e)**.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationCog(bot))

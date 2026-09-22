"""Steam-artiges Achievement-System mit öffentlichen und geheimen Quests."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands


@dataclass(frozen=True, slots=True)
class Achievement:
    key: str
    title: str
    description: str
    category: str
    emoji: str
    stat: str
    target: int
    secret: bool = False
    hint: str | None = None


ACHIEVEMENTS: tuple[Achievement, ...] = (
    Achievement("first_steps", "Erste Schritte", "Erreiche Level 1.", "Level", "🌱", "level", 1),
    Achievement("rising_star", "Aufgehender Stern", "Erreiche Level 5.", "Level", "⭐", "level", 5),
    Achievement("double_digits", "Zweistellig", "Erreiche Level 10.", "Level", "🔟", "level", 10),
    Achievement("tower_veteran", "Turm-Veteran", "Erreiche Level 20.", "Level", "🏰", "level", 20),
    Achievement("tower_legend", "Legende des Turms", "Erreiche Level 50.", "Level", "👑", "level", 50, True, "Manche Namen werden erst nach vielen Etagen zur Legende."),
    Achievement("beyond_the_peak", "Jenseits des Gipfels", "Erreiche Level 100.", "Level", "🌌", "level", 100, True, "Der höchste sichtbare Gipfel ist nicht das Ende."),
    Achievement("first_purse", "Klingelbeutel", "Besitze 1.000 Coins.", "Economy", "🪙", "coins", 1_000),
    Achievement("well_funded", "Gut gepolstert", "Besitze 10.000 Coins.", "Economy", "💰", "coins", 10_000),
    Achievement("dragon_hoard", "Drachenhort", "Besitze 50.000 Coins.", "Economy", "🐉", "coins", 50_000),
    Achievement("golden_silence", "Goldenes Schweigen", "Besitze 100.000 Coins.", "Economy", "🔐", "coins", 100_000, True, "Lass deine Münzen eine ungewöhnlich große Zahl flüstern."),
    Achievement("coin_constellation", "Münzkonstellation", "Besitze 1.000.000 Coins.", "Economy", "🌠", "coins", 1_000_000, True, "Auch ein Vermögen kann die Form eines Sternenbilds annehmen."),
    Achievement("game_on", "Game on!", "Spiele dein erstes Bot-Spiel.", "Games", "🎮", "games", 1),
    Achievement("regular_player", "Stammspieler", "Spiele 10 Bot-Spiele.", "Games", "🕹️", "games", 10),
    Achievement("winning_streak", "Gewinnertyp", "Gewinne 10 Bot-Spiele.", "Games", "🏅", "wins", 10),
    Achievement("lucky_century", "Das Haus kennt dich", "Spiele 100 Bot-Spiele.", "Games", "🎰", "games", 100, True, "Kehre oft genug an den Spieltisch zurück, bis du kein Gast mehr bist."),
    Achievement("victory_archive", "Archiv der Siege", "Gewinne 50 Bot-Spiele.", "Games", "📜", "wins", 50),
    Achievement("after_midnight", "Nach Mitternacht", "Spiele 500 Bot-Spiele.", "Games", "🌙", "games", 500, True, "Ein echter Dauergast zählt seine Runden irgendwann nicht mehr."),
    Achievement("hundred_crowns", "Hundert Kronen", "Gewinne 100 Bot-Spiele.", "Games", "💯", "wins", 100, True, "Nicht jede Krone wird auf dem Kopf getragen."),
    Achievement("first_friend", "Nicht mehr allein", "Schließe deine erste Freundschaft über /friend add.", "Social", "🤝", "friends", 1),
    Achievement("social_circle", "Innerer Kreis", "Sei mit 5 Personen befreundet.", "Social", "🫂", "friends", 5),
    Achievement("full_table", "Voller Tisch", "Sei mit 10 Personen befreundet.", "Social", "🍽️", "friends", 10),
    Achievement("strong_bond", "Unzertrennlich", "Erreiche 500 Freundschafts-XP mit einer Person.", "Social", "💞", "friend_xp", 500),
    Achievement("soulbound", "Seelenverwandt", "Gehe eine Ehe auf dem Server ein.", "Social", "💍", "marriages", 1, True, "Manche Verbindungen gehen über Freundschaft hinaus."),
    Achievement("unspoken_pact", "Ungesagter Pakt", "Erreiche 1.000 Freundschafts-XP mit einer Person.", "Social", "🪢", "friend_xp", 1_000, True, "Pflege eine einzelne Verbindung weit über das Gewöhnliche hinaus."),
    Achievement("card_apprentice", "Sammlerlehrling", "Besitze insgesamt 10 Spielkarten.", "Sammlung", "🎴", "cards", 10),
    Achievement("card_curator", "Kurator", "Besitze insgesamt 50 Spielkarten.", "Sammlung", "🗃️", "cards", 50),
    Achievement("living_archive", "Lebendes Archiv", "Besitze insgesamt 250 Spielkarten.", "Sammlung", "📚", "cards", 250, True, "Eine Sammlung wird zum Archiv, wenn einzelne Karten kaum noch zu zählen sind."),
    Achievement("yami_vault", "Yamis Schatzkammer", "Besitze insgesamt 10 Yami-Karten.", "Sammlung", "✨", "yami_cards", 10),
    Achievement("yami_eclipse", "Yami-Finsternis", "Besitze insgesamt 50 Yami-Karten.", "Sammlung", "🌑", "yami_cards", 50, True, "Sammle genug von Yamis Glanz, bis er das Licht verdeckt."),
    Achievement("daily_week", "Sieben Tage Treue", "Erreiche eine Daily-Streak von 7 Tagen.", "Aktivität", "🔥", "daily_streak", 7),
    Achievement("daily_fortnight", "Zwei Wochen Rhythmus", "Erreiche eine Daily-Streak von 14 Tagen.", "Aktivität", "📅", "daily_streak", 14),
    Achievement("moon_cycle", "Ein ganzer Mond", "Erreiche eine Daily-Streak von 30 Tagen.", "Aktivität", "🌕", "daily_streak", 30, True, "Lass keinen Tag verstreichen, bis der Mond seinen Kreis vollendet hat."),
)


def achievement_payload(
    achievement: Achievement, snapshot: dict[str, int], unlocked_at: float | None
) -> dict:
    """Sicheres API-/UI-Modell; verrät bei gesperrten Secrets weder Ziel noch Fortschritt."""
    unlocked = unlocked_at is not None
    hidden = achievement.secret and not unlocked
    current = min(max(0, int(snapshot.get(achievement.stat, 0))), achievement.target)
    progress = None if hidden else {
        "current": current,
        "target": achievement.target,
        "percent": round((current / achievement.target) * 100),
    }
    return {
        "id": achievement.key,
        "title": "Geheimes Achievement" if hidden else achievement.title,
        "description": (
            "Details werden erst nach dem Freischalten enthüllt." if hidden else achievement.description
        ),
        "category": achievement.category,
        "emoji": "❔" if hidden else achievement.emoji,
        "secret": achievement.secret,
        "unlocked": unlocked,
        "unlocked_at": unlocked_at,
        "progress": progress,
        "hint": achievement.hint if hidden else None,
    }


def can_view_achievements(db, guild_id: int, viewer_id: int, target_id: int) -> bool:
    """Eigene Sammlung oder die Sammlung eines bestätigten /friend-add-Freundes."""
    if viewer_id == target_id:
        return True
    row = db.get_friend_row(guild_id, viewer_id, target_id)
    return bool(row and row["status"] == "accepted")


def sync_user_achievements(
    db, guild_id: int, user_id: int, *, notify_limit: int | None = None
) -> list[Achievement]:
    """Persistiert erfüllte Quests und liefert nur live neu zu meldende Achievements.

    Beim ersten Kontakt werden bereits erfüllte Ziele absichtlich still nachgetragen.
    So bekommen langjährige Mitglieder keine Nachrichtenlawine und anschließend auch
    nicht bei jeder Aktion genau ein altes Achievement nachgereicht.
    """
    snapshot = db.achievement_snapshot(guild_id, user_id)
    unlocked = db.get_unlocked_achievements(user_id)
    eligible = [
        item for item in ACHIEVEMENTS
        if item.key not in unlocked and snapshot.get(item.stat, 0) >= item.target
    ]

    if not db.achievements_initialized(user_id):
        for item in eligible:
            db.unlock_achievement(user_id, item.key)
        db.mark_achievements_initialized(user_id)
        return []

    if notify_limit is not None:
        eligible = eligible[:max(0, notify_limit)]
    newly_unlocked: list[Achievement] = []
    for item in eligible:
        if db.unlock_achievement(user_id, item.key):
            newly_unlocked.append(item)
    return newly_unlocked


def user_achievement_payload(db, guild_id: int, user_id: int) -> list[dict]:
    sync_user_achievements(db, guild_id, user_id)
    snapshot = db.achievement_snapshot(guild_id, user_id)
    unlocked = db.get_unlocked_achievements(user_id)
    return [achievement_payload(item, snapshot, unlocked.get(item.key)) for item in ACHIEVEMENTS]


def friend_achievement_payload(db, guild_id: int, user_id: int) -> list[dict]:
    """Öffentliche Vergleichsansicht; geheime Erfolge verlassen die API nie."""
    return [item for item in user_achievement_payload(db, guild_id, user_id) if not item["secret"]]


def _bar(percent: int, width: int = 10) -> str:
    filled = min(width, max(0, round(percent / 100 * width)))
    return "▰" * filled + "▱" * (width - filled)


def achievement_embeds(
    db, guild_id: int, member: discord.abc.User, *, include_secrets: bool = True
) -> list[discord.Embed]:
    items = (
        user_achievement_payload(db, guild_id, member.id)
        if include_secrets
        else friend_achievement_payload(db, guild_id, member.id)
    )
    unlocked_count = sum(1 for item in items if item["unlocked"])
    chunks = [items[index:index + 20] for index in range(0, len(items), 20)] or [[]]
    embeds: list[discord.Embed] = []
    for page, chunk in enumerate(chunks, start=1):
        embed = discord.Embed(
            title=f"🏆 Achievements · {member.display_name}" if page == 1 else f"🏆 Weitere Achievements · {member.display_name}",
            description=(
                f"**{unlocked_count}/{len(items)}** freigeschaltet · "
                f"{round(unlocked_count / max(1, len(items)) * 100)} % komplett\n"
                + (
                    "Öffentliche Quests zeigen ihren Weg. Geheime Prüfungen geben dir einen Hinweis und bleiben vor Freunden verborgen."
                    if include_secrets
                    else "Im Freundesvergleich werden ausschließlich öffentliche Achievements gezeigt."
                )
            ) if page == 1 else None,
            color=0xF4B942,
        )
        if page == 1:
            embed.set_thumbnail(url=member.display_avatar.url)
        for item in chunk:
            if item["unlocked"]:
                timestamp = int(item["unlocked_at"])
                value = f"{item['description']}\n✅ Freigeschaltet <t:{timestamp}:R>"
                prefix = item["emoji"]
            elif item["progress"] is None:
                value = item["description"]
                if item.get("hint"):
                    value += f"\n💡 **Tipp:** {item['hint']}"
                prefix = "🔒"
            else:
                progress = item["progress"]
                value = (
                    f"{item['description']}\n`{_bar(progress['percent'])}` "
                    f"**{progress['current']:,}/{progress['target']:,}**"
                ).replace(",", ".")
                prefix = "▫️"
            embed.add_field(name=f"{prefix} {item['title']}", value=value, inline=False)
        embed.set_footer(
            text=f"Seite {page}/{len(chunks)} · Globaler Fortschritt · Freunde über /friend add vergleichen"
        )
        embeds.append(embed)
    return embeds


def _unlock_embed(item: Achievement, member: discord.abc.User) -> discord.Embed:
    return discord.Embed(
        title="🏆 Achievement freigeschaltet!",
        description=f"## {item.emoji} {item.title}\n{item.description}",
        color=0xF4B942,
        timestamp=datetime.now(timezone.utc),
    ).set_footer(text=f"Glückwunsch, {member.display_name}!")


class AchievementCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]
        self.web_base_url = os.environ.get("WEB_BASE_URL", "").rstrip("/")

    @app_commands.command(name="achievements", description="Zeigt Quests, Fortschritt und geheime Achievements.")
    @app_commands.guild_only()
    @app_commands.describe(user="Optional: ein bestätigter Freund aus /friend add")
    async def achievements(
        self, interaction: discord.Interaction, user: discord.Member | None = None
    ) -> None:
        if interaction.guild_id is None:
            return
        target = user or interaction.user
        if not can_view_achievements(
            self.db, interaction.guild_id, interaction.user.id, target.id
        ):
            await interaction.response.send_message(
                "🔒 Du kannst nur deine eigenen Achievements oder die bestätigter Freunde ansehen.",
                ephemeral=True,
            )
            return

        view = None
        if self.web_base_url:
            view = discord.ui.View()
            view.add_item(discord.ui.Button(
                label="Auf der Website ansehen",
                emoji="🌐",
                url=f"{self.web_base_url}/u/{interaction.guild_id}/achievements",
            ))
        response_kwargs = {
            "embeds": achievement_embeds(
                self.db,
                interaction.guild_id,
                target,
                include_secrets=target.id == interaction.user.id,
            ),
            "ephemeral": True,
            "allowed_mentions": discord.AllowedMentions.none(),
        }
        if view is not None:
            response_kwargs["view"] = view
        await interaction.response.send_message(**response_kwargs)

    @commands.Cog.listener()
    async def on_app_command_completion(
        self, interaction: discord.Interaction, _command: app_commands.Command
    ) -> None:
        if interaction.guild_id is None or interaction.user.bot:
            return
        new = sync_user_achievements(
            self.db, interaction.guild_id, interaction.user.id, notify_limit=1
        )
        if not new:
            return
        try:
            await interaction.followup.send(
                embed=_unlock_embed(new[0], interaction.user), ephemeral=True
            )
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        # Leveling- und andere Listener dürfen ihre DB-Änderung zuerst abschließen.
        await asyncio.sleep(0.35)
        new = sync_user_achievements(
            self.db, message.guild.id, message.author.id, notify_limit=1
        )
        if not new:
            return
        try:
            await message.reply(
                embed=_unlock_embed(new[0], message.author),
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.Forbidden, discord.HTTPException):
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AchievementCog(bot))

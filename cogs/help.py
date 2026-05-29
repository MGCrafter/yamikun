"""Interaktives /help mit Kategorie-Dropdown."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

# Kategorie-Key → (Emoji, Titel, Kurzbeschreibung fürs Dropdown, Liste (command, beschreibung))
CATEGORIES: dict[str, dict] = {
    "gambling": {
        "emoji": "🎮",
        "title": "Gambling",
        "short": "Glücksspiele mit Coins",
        "commands": [
            ("/coinflip <head/tail> <einsatz>", "Münzwurf — bei richtigem Tipp Einsatz verdoppelt (48 %)."),
            ("/blackjack <einsatz>", "Blackjack gegen den Dealer (Hit/Stand/Double/Split, BJ 3:2)."),
            ("/slots <einsatz>", "3-Walzen-Slot, nur drei Gleiche gewinnen (Jackpot 🪙 ×100)."),
        ],
    },
    "economy": {
        "emoji": "💰",
        "title": "Economy & Shop",
        "short": "Daily, Coins überweisen, Shop",
        "commands": [
            ("/daily", "Tägliche Coin-Belohnung mit Streak (+Wochen-Bonus)."),
            ("/pay @user <betrag>", "Coins an jemanden überweisen (1:1)."),
            ("/shop", "Zeigt kaufbare Items."),
            ("/buy <item>", "Kauft Glücksbringer oder XP-Boost."),
        ],
    },
    "leveling": {
        "emoji": "📊",
        "title": "Leveling & Profil",
        "short": "XP, Rang, Profil",
        "commands": [
            ("/rank [user]", "Level, XP-Fortschritt und Coins."),
            ("/leaderboard", "Top 10 nach XP."),
            ("/profile [user]", "Profilseite: Level, Coins, Rang, Statistiken, Titel, Ehen, Bio."),
            ("/setbio <text>", "Eigene Profil-Bio setzen."),
            ("/setcolor <hex>", "Profil-Akzentfarbe wählen (z.B. #FF8800)."),
            ("/title list / set / clear", "XP-Titel anzeigen und auswählen (durch Level freischaltbar)."),
        ],
    },
    "social": {
        "emoji": "👥",
        "title": "Social & Interactions",
        "short": "Freunde & GIF-Aktionen",
        "commands": [
            ("/friend add / accept / remove", "Freundschaftsanfragen verwalten."),
            ("/friend requests / list / level", "Anfragen, Freundesliste, Friendship-Level."),
            ("/hug · /pat · /kiss · /slap · /highfive @user", "GIF-Aktionen (+Freundschafts-XP)."),
            ("/marry @user · /divorce @user · /marriages", "Heiraten (mit GIF), scheiden, Ehen anzeigen."),
        ],
    },
    "lfg": {
        "emoji": "🎯",
        "title": "LFG — Looking for Group",
        "short": "Gruppensuche",
        "commands": [
            ("/lfg start <size> <beschreibung> <channel> [rolle]", "Gruppensuche mit Join-Buttons."),
            ("/lfg role", "Selbst für LFG-Pings an-/abmelden."),
            ("/lfg setrole @rolle", "LFG-Ping-Rolle festlegen (Mods)."),
        ],
    },
    "cards": {
        "emoji": "🎴",
        "title": "Sammelkarten",
        "short": "Karten erspielen & sammeln",
        "commands": [
            ("/gamecards [user]", "Deine erspielten Sammelkarten."),
            ("/gamecard <karte>", "Zeigt eine einzelne erspielte Karte (Bild & Seltenheit)."),
        ],
    },
    "booster": {
        "emoji": "📦",
        "title": "Booster & Yami-Karten",
        "short": "Packs kaufen, öffnen, sammeln",
        "commands": [
            ("/booster buy <typ> [anzahl]", "Booster-Packs mit Coins kaufen."),
            ("/booster open <typ>", "Ein Pack öffnen → zufällige Karten."),
            ("/booster packs", "Deine ungeöffneten Packs."),
            ("/booster collection [user]", "Deine Yami-Karten-Sammlung."),
            ("/booster card <karte>", "Eine Yami-Karte ansehen."),
        ],
    },
    "fun": {
        "emoji": "🎲",
        "title": "Fun & Sonstiges",
        "short": "Spaß-Befehle",
        "commands": [
            ("/8ball <frage>", "Antwort der magischen Miesmuschel."),
            ("/insult [@user]", "Zufällige harmlose Beleidigung."),
            ("/whoisguilty <verdächtige>", "Der Bot ermittelt den Schuldigen aus den Gepingten."),
            ("/existential [stil]", "Cursed Weisheiten, Fake-deep Quotes & philosophischer Unsinn."),
            ("/summondemon", "Beschwöre Yami — glücklich oder erzürnt? (Cooldown)"),
        ],
    },
    "admin": {
        "emoji": "🛠️",
        "title": "Moderation & Admin",
        "short": "Nur für Mods/Admins",
        "commands": [
            ("/purge <anzahl> [user]", "Löscht 1–100 Nachrichten (optional nur eines Users)."),
            ("/say <text> [channel]", "Lässt den Bot eine Nachricht schreiben."),
            ("/level setchannel #channel", "Channel für Level-Up-Meldungen."),
            ("/level give @user <coins>", "Coins vergeben/entziehen."),
            ("/gamereward addgame / removegame / listgames", "Spiele für Karten-Rewards verwalten."),
            ("/gamereward addcard / removecard / listcards", "Karten pro Spiel anlegen/entfernen/anzeigen."),
            ("/gamereward setchannel [#channel]", "Channel für Karten-Drop-Meldungen (sonst DM)."),
            ("/yamicard add / remove / list", "Yami-Karten (für Booster-Packs) verwalten."),
        ],
    },
    "tools": {
        "emoji": "🧹",
        "title": "Auto-Delete & Announcer",
        "short": "Code-Cleanup & Announcements",
        "commands": [
            ("/oaken on / off / status", "Auto-Delete alter Oaken-Codes im Channel."),
            ("/oaken newgame / endgame", "1v1-Spiel mit Rundenzählung starten/beenden."),
            ("/oaken reset", "Code-Tracking zurücksetzen (Mods)."),
            ("/announce channel / add / list / remove", "Quellen (YouTube/RSS) verwalten (Mods)."),
            ("/announce post <link> [text]", "Link manuell in den Announce-Channel posten (Mods)."),
        ],
    },
}


def _category_embed(bot_name: str, key: str) -> discord.Embed:
    cat = CATEGORIES[key]
    lines = [f"**{cmd}**\n{desc}" for cmd, desc in cat["commands"]]
    return discord.Embed(
        title=f"{cat['emoji']} {cat['title']}",
        description="\n\n".join(lines),
        color=0x5865F2,
    ).set_footer(text=f"{bot_name} · /help")


def _overview_embed(bot_name: str) -> discord.Embed:
    lines = [f"{c['emoji']} **{c['title']}** — {c['short']}" for c in CATEGORIES.values()]
    return discord.Embed(
        title=f"📖 {bot_name} — Hilfe",
        description="Wähle unten eine Kategorie ▼\n\n" + "\n".join(lines),
        color=0x5865F2,
    ).set_footer(text="Tipp: Tippe „/“ im Chat, um alle Commands direkt zu sehen.")


class HelpSelect(discord.ui.Select):
    def __init__(self, bot_name: str) -> None:
        self.bot_name = bot_name
        options = [
            discord.SelectOption(
                label=cat["title"], value=key, emoji=cat["emoji"], description=cat["short"]
            )
            for key, cat in CATEGORIES.items()
        ]
        super().__init__(placeholder="Wähle eine Kategorie…", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            embed=_category_embed(self.bot_name, self.values[0]), view=self.view
        )


class HelpView(discord.ui.View):
    def __init__(self, bot_name: str) -> None:
        super().__init__(timeout=180)
        self.add_item(HelpSelect(bot_name))


class HelpCog(commands.Cog):
    """/help."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="Zeigt alle Befehle des Bots.")
    async def help(self, interaction: discord.Interaction) -> None:
        bot_name = interaction.client.user.display_name if interaction.client.user else "Bot"
        await interaction.response.send_message(
            embed=_overview_embed(bot_name), view=HelpView(bot_name), ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))

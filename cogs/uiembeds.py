"""Gemeinsame, hochwertige Reward-Embeds im Loot-Drop-/Battlepass-Stil.

Discord-Embeds können keine Gradients/Glows — der „Premium-Gaming"-Look entsteht
über klare Hierarchie: Badge-Zeile (Autor), großer Reward-Titel, Chip-artige
Felder (Spiel / Bestand) und ein motivierender Footer. Bewusst sparsam mit Emojis.
"""

from __future__ import annotations

import discord

# Akzentfarben (Embed-Leiste links) — abgestimmt auf das Webpanel-Theme.
LIME = 0xA3E635
VIOLET = 0x7C3AED
GOLD = 0xF1C40F


def pretty_game(game: str | None) -> str:
    """'league of legends' -> 'League Of Legends'."""
    return " ".join(w.capitalize() for w in (game or "").split()) or "—"


def reward_embed(
    *,
    badge: str,
    title: str,
    member: discord.abc.User | None = None,
    description: str | None = None,
    game: str | None = None,
    total: int | None = None,
    total_label: str = "Im Inventar",
    hint: str | None = None,
    footer: str = "Weiterspielen schaltet mehr Drops frei.",
    color: int = LIME,
) -> discord.Embed:
    """Baut eine Reward-Card. `badge` = kleine Kategorie-Zeile, `title` = großer Reward."""
    embed = discord.Embed(title=title, description=description, color=color)
    if member is not None:
        embed.set_author(name=badge, icon_url=member.display_avatar.url)
    else:
        embed.set_author(name=badge)
    if game is not None:
        embed.add_field(name="🎮 Spiel", value=f"`{pretty_game(game)}`", inline=True)
    if total is not None:
        embed.add_field(name=f"📦 {total_label}", value=f"**{total}**", inline=True)
    if hint:
        embed.add_field(name="​", value=hint, inline=False)
    embed.set_footer(text=footer)
    return embed

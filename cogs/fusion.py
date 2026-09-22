"""Karten-Fusion: 5 Karten einer Seltenheit → 1 zufällige der nächsthöheren.

Kette: Common → Uncommon → Rare → Epic → Legendary. **Stopp bei Legendary** —
Mythic ist NICHT per Fusion erreichbar.

- Sammelkarten (`/gamecards`): fusioniert innerhalb **eines Spiels** (Ergebnis ist
  eine zufällige Karte der nächsten Seltenheit aus demselben Spiel-Pool).
- Yami-Karten (`/booster collection`): fusioniert im globalen Yami-Pool.

Die Kernfunktionen `fuse_game` / `fuse_yami` werden auch vom Webpanel-User-Dashboard
genutzt.
"""

from __future__ import annotations

import random

import discord
from discord import app_commands
from discord.ext import commands

from cogs.gamecards import RARITIES, build_game_catalog, build_full_catalog

FUSE_COST = 5
# Aufstiegs-Kette (Mythic bewusst NICHT enthalten → kein Mythic per Fusion).
FUSE_NEXT: dict[str, str] = {
    "common": "uncommon",
    "uncommon": "rare",
    "rare": "epic",
    "epic": "legendary",
}
FUSABLE = list(FUSE_NEXT)  # common, uncommon, rare, epic

ERRORS = {
    "no_next": "Diese Seltenheit lässt sich nicht fusionieren (Legendary ist das Maximum).",
    "not_enough": f"Du brauchst **{FUSE_COST}** Karten dieser Seltenheit.",
    "no_target": "Es gibt keine Karte der nächsthöheren Seltenheit in diesem Pool.",
    "no_cards": "Hier gibt es keine Karten.",
}


def _plan_and_target(catalog: dict, owned: dict[str, int], from_rarity: str):
    """Berechnet (Verbrauchsplan {cid:anzahl}, Ziel-Pool, Ziel-Seltenheit) oder Fehlercode."""
    if from_rarity not in FUSE_NEXT:
        return None, "no_next"
    to_rarity = FUSE_NEXT[from_rarity]
    src = [cid for cid in owned if catalog.get(cid) and catalog[cid][1] == from_rarity]
    if sum(owned[cid] for cid in src) < FUSE_COST:
        return None, "not_enough"
    target_pool = [cid for cid, (_n, r, _u) in catalog.items() if r == to_rarity]
    if not target_pool:
        return None, "no_target"
    plan: dict[str, int] = {}
    remaining = FUSE_COST
    for cid in src:
        if remaining <= 0:
            break
        take = min(remaining, owned[cid])
        plan[cid] = take
        remaining -= take
    return (plan, target_pool, to_rarity), None


def fuse_game(db, guild_id: int, user_id: int, game: str, from_rarity: str) -> dict:
    catalog = build_game_catalog(db, guild_id, game)
    if not catalog:
        return {"ok": False, "error": "no_cards"}
    owned = db.get_collection(guild_id, user_id)
    res, err = _plan_and_target(catalog, owned, from_rarity)
    if err:
        return {"ok": False, "error": err}
    plan, target_pool, _to = res
    for cid, amt in plan.items():
        db.remove_card(guild_id, user_id, cid, amt)
    result_cid = random.choice(target_pool)
    db.add_card(guild_id, user_id, result_cid)
    name, rarity, url = catalog[result_cid]
    return {"ok": True, "result": {"id": result_cid, "name": name, "rarity": rarity, "url": url}}


def fuse_yami(db, guild_id: int, user_id: int, from_rarity: str) -> dict:
    catalog = {cid: (n, r, u) for cid, n, r, u in db.list_server_cards(guild_id)}
    if not catalog:
        return {"ok": False, "error": "no_cards"}
    owned = db.get_server_collection(guild_id, user_id)
    res, err = _plan_and_target(catalog, owned, from_rarity)
    if err:
        return {"ok": False, "error": err}
    plan, target_pool, _to = res
    for cid, amt in plan.items():
        db.remove_server_card_owned(guild_id, user_id, cid, amt)
    result_cid = random.choice(target_pool)
    db.add_server_card_owned(guild_id, user_id, result_cid)
    name, rarity, url = catalog[result_cid]
    return {"ok": True, "result": {"id": result_cid, "name": name, "rarity": rarity, "url": url}}


def fusable_counts(catalog: dict, owned: dict[str, int]) -> dict[str, int]:
    """Wie viele Karten je fusionierbarer Seltenheit besitzt der User (für die UI)."""
    counts = {r: 0 for r in FUSABLE}
    for cid, n in owned.items():
        c = catalog.get(cid)
        if c and c[1] in counts:
            counts[c[1]] += n
    return counts


def _result_embed(member: discord.abc.User, from_rarity: str, result: dict, source: str) -> discord.Embed:
    rin = RARITIES.get(from_rarity, RARITIES["common"])
    rout = RARITIES.get(result["rarity"], RARITIES["common"])
    embed = discord.Embed(
        title=f"{rout['emoji']}  {result['name']}",
        description=(
            f"**{FUSE_COST}× {rin['emoji']} {rin['label']}** → "
            f"**{rout['emoji']} {rout['label']}**\n_{source}_"
        ),
        color=rout["color"],
    )
    embed.set_author(name="✦  FUSION", icon_url=member.display_avatar.url)
    if result.get("url"):
        embed.set_image(url=result["url"])
    embed.set_footer(text="Glückwunsch zur aufgewerteten Karte!")
    return embed


async def _owned_game_autocomplete(interaction: discord.Interaction, current: str):
    db = interaction.client.db  # type: ignore[attr-defined]
    owned = db.get_collection(interaction.guild_id, interaction.user.id)
    catalog = build_full_catalog(db, interaction.guild_id)
    games = sorted({
        g for cid in owned
        for g in [_game_of_card(db, interaction.guild_id, cid)]
        if g and current.lower() in g.lower()
    })
    _ = catalog  # nur zur Klarheit
    return [app_commands.Choice(name=g, value=g) for g in games][:25]


def _game_of_card(db, guild_id: int, card_id: str) -> str | None:
    for cid, _n, _r, _u, game in db.list_custom_cards(guild_id):
        if cid == card_id:
            return game
    return None


class FusionCog(commands.Cog):
    """/fuse — Karten zu höheren Seltenheiten fusionieren."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]

    fuse = app_commands.Group(
        name="fuse",
        description=f"{FUSE_COST} Karten einer Seltenheit → 1 der nächsten (bis Legendary).",
        guild_only=True,
    )

    _RARITY_CHOICES = [app_commands.Choice(name=RARITIES[r]["label"], value=r) for r in FUSABLE]

    @fuse.command(name="cards", description="Erspielte Sammelkarten eines Spiels fusionieren.")
    @app_commands.describe(spiel="Welches Spiel?", seltenheit="Welche Seltenheit fusionieren?")
    @app_commands.autocomplete(spiel=_owned_game_autocomplete)
    @app_commands.choices(seltenheit=_RARITY_CHOICES)
    async def fuse_cards(
        self, interaction: discord.Interaction, spiel: str, seltenheit: app_commands.Choice[str],
    ) -> None:
        res = fuse_game(self.db, interaction.guild_id, interaction.user.id, spiel, seltenheit.value)
        if not res["ok"]:
            await interaction.response.send_message(f"⚠️ {ERRORS.get(res['error'], 'Fusion fehlgeschlagen.')}", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=_result_embed(interaction.user, seltenheit.value, res["result"], f"Sammelkarten · {spiel}")
        )

    @fuse.command(name="yami", description="Yami-Karten fusionieren.")
    @app_commands.describe(seltenheit="Welche Seltenheit fusionieren?")
    @app_commands.choices(seltenheit=_RARITY_CHOICES)
    async def fuse_yami_cmd(
        self, interaction: discord.Interaction, seltenheit: app_commands.Choice[str],
    ) -> None:
        res = fuse_yami(self.db, interaction.guild_id, interaction.user.id, seltenheit.value)
        if not res["ok"]:
            await interaction.response.send_message(f"⚠️ {ERRORS.get(res['error'], 'Fusion fehlgeschlagen.')}", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=_result_embed(interaction.user, seltenheit.value, res["result"], "Yami-Karten")
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FusionCog(bot))

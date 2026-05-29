"""Yami-Karten: Sammelkarten über Booster-Packs (mit Coins gekauft).

Eigenständiges System, getrennt von den Spiel-Reward-Karten:
- Eigener Kartenpool (Yami-Karten, per /yamicard von Mods angelegt, mit Bild-URL).
- Packs werden mit Coins gekauft (/booster buy), gesammelt und später geöffnet
  (/booster open) → gewichtete Zufallskarten je nach Pack-Tier.
- Eigene Sammlung via /booster collection.
"""

from __future__ import annotations

import logging
import random
import re

import discord
from discord import app_commands
from discord.ext import commands

from cogs.gamecards import RARITIES, RARITY_ORDER

logger = logging.getLogger("oaken-tower-bot")

COIN_EMOJI_NAME = "YamiToken"
COIN_FALLBACK = "🪙"

# Pack-Tiers: Preis, Kartenanzahl und Seltenheits-Gewichte
PACKS: dict[str, dict] = {
    "standard": {
        "label": "Standard-Pack", "emoji": "📦", "price": 2000, "cards": 5,
        "weights": {"common": 50, "uncommon": 28, "rare": 15, "epic": 6, "legendary": 1, "mythic": 0.2},
    },
    "premium": {
        "label": "Premium-Pack", "emoji": "✨", "price": 5000, "cards": 5,
        "weights": {"common": 20, "uncommon": 30, "rare": 30, "epic": 15, "legendary": 4, "mythic": 1},
    },
}


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _slug(name: str) -> str | None:
    s = re.sub(r"[^a-z0-9]+", "", name.lower())
    return f"srv_{s}" if s else None


def _catalog(db, guild_id: int) -> dict[str, tuple[str, str, str | None]]:
    return {cid: (name, rarity, url) for cid, name, rarity, url in db.list_server_cards(guild_id)}


def _roll(catalog: dict[str, tuple[str, str, str | None]], weights: dict[str, int]) -> str:
    present = [r for r in weights if any(c[1] == r for c in catalog.values())]
    w = [weights[r] for r in present]
    rarity = random.choices(present, weights=w, k=1)[0]
    pool = [cid for cid, c in catalog.items() if c[1] == rarity]
    return random.choice(pool)


async def _server_card_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    cur = current.lower()
    cards = interaction.client.db.list_server_cards(interaction.guild_id)  # type: ignore[attr-defined]
    return [
        app_commands.Choice(name=f"{RARITIES[rarity]['emoji']} {name}", value=cid)
        for cid, name, rarity, _ in cards
        if cur in name.lower()
    ][:25]


class BoosterCog(commands.Cog):
    """/booster (buy, open, packs, collection, card) + /yamicard (Mods)."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]

    def _coin(self, guild: discord.Guild | None) -> str:
        if guild is not None:
            emoji = discord.utils.get(guild.emojis, name=COIN_EMOJI_NAME)
            if emoji is not None:
                return str(emoji)
        return COIN_FALLBACK

    def _card_embed(self, name: str, rarity: str, url: str | None, *, owned: int | None = None) -> discord.Embed:
        r = RARITIES.get(rarity, RARITIES["common"])
        embed = discord.Embed(
            title=f"{r['emoji']} {name}",
            description=f"Seltenheit: **{r['label']}**"
            + (f"\nIn deiner Sammlung: **{owned}×**" if owned is not None else ""),
            color=r["color"],
        )
        if url:
            embed.set_image(url=url)
        return embed

    # --- /booster (öffentlich) ------------------------------------------------

    booster = app_commands.Group(name="booster", description="Booster-Packs kaufen, öffnen & sammeln.", guild_only=True)

    @booster.command(name="buy", description="Kaufe Booster-Packs mit Coins.")
    @app_commands.describe(typ="Welches Pack?", anzahl="Wie viele? (Standard 1)")
    @app_commands.choices(typ=[app_commands.Choice(name=PACKS[p]["label"], value=p) for p in PACKS])
    async def buy(
        self, interaction: discord.Interaction, typ: app_commands.Choice[str],
        anzahl: app_commands.Range[int, 1, 100] = 1,
    ) -> None:
        pack = PACKS[typ.value]
        coin = self._coin(interaction.guild)
        cost = pack["price"] * anzahl
        balance = int(self.db.get_user(interaction.guild_id, interaction.user.id)["coins"])
        if cost > balance:
            await interaction.response.send_message(
                f"⚠️ Du hast nur **{_fmt(balance)}** {coin}, brauchst aber **{_fmt(cost)}**.",
                ephemeral=True,
            )
            return
        self.db.add_coins(interaction.guild_id, interaction.user.id, -cost)
        total = self.db.add_packs(interaction.guild_id, interaction.user.id, typ.value, anzahl)
        await interaction.response.send_message(
            f"✅ **{anzahl}× {pack['emoji']} {pack['label']}** gekauft (−{_fmt(cost)} {coin}).\n"
            f"Du besitzt jetzt **{total}**. Öffne mit `/booster open typ:{pack['label']}`.",
            ephemeral=True,
        )

    @booster.command(name="open", description="Öffne ein Booster-Pack.")
    @app_commands.describe(typ="Welches Pack öffnen?")
    @app_commands.choices(typ=[app_commands.Choice(name=PACKS[p]["label"], value=p) for p in PACKS])
    async def open(self, interaction: discord.Interaction, typ: app_commands.Choice[str]) -> None:
        pack = PACKS[typ.value]
        catalog = _catalog(self.db, interaction.guild_id)
        if not catalog:
            await interaction.response.send_message(
                "⚠️ Es gibt noch keine Yami-Karten. Ein Mod kann welche mit `/yamicard add` anlegen.",
                ephemeral=True,
            )
            return
        if not self.db.consume_pack(interaction.guild_id, interaction.user.id, typ.value):
            await interaction.response.send_message(
                f"⚠️ Du hast kein **{pack['label']}**. Kaufe eins mit `/booster buy`.", ephemeral=True
            )
            return

        drawn = [_roll(catalog, pack["weights"]) for _ in range(pack["cards"])]
        for cid in drawn:
            self.db.add_server_card_owned(interaction.guild_id, interaction.user.id, cid)

        lines = [f"{RARITIES[catalog[cid][1]]['emoji']} **{catalog[cid][0]}**" for cid in drawn]
        best = min(drawn, key=lambda cid: RARITY_ORDER.index(catalog[cid][1]))
        bname, brar, burl = catalog[best]
        embed = discord.Embed(
            title=f"{pack['emoji']} {pack['label']} geöffnet!",
            description="\n".join(lines),
            color=RARITIES[brar]["color"],
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        if burl:
            embed.set_image(url=burl)
            embed.set_footer(text=f"Highlight: {bname} ({RARITIES[brar]['label']})")
        await interaction.response.send_message(embed=embed)

    @booster.command(name="packs", description="Zeigt deine ungeöffneten Packs.")
    async def packs(self, interaction: discord.Interaction) -> None:
        owned = self.db.list_packs(interaction.guild_id, interaction.user.id)
        owned = {t: n for t, n in owned.items() if t in PACKS}
        if not owned:
            await interaction.response.send_message(
                "Du hast keine Packs. Kaufe welche mit `/booster buy`. 📦", ephemeral=True
            )
            return
        lines = [f"{PACKS[t]['emoji']} **{PACKS[t]['label']}**: {n}×" for t, n in owned.items()]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @booster.command(name="collection", description="Zeigt deine Yami-Karten-Sammlung.")
    @app_commands.describe(user="Optional: wessen Sammlung? (Standard: du)")
    async def collection(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        target = user or interaction.user
        coll = self.db.get_server_collection(interaction.guild_id, target.id)
        if not coll:
            await interaction.response.send_message(
                f"{target.display_name} hat noch keine Yami-Karten. Öffne Booster-Packs! 🎴",
                ephemeral=True,
            )
            return
        catalog = _catalog(self.db, interaction.guild_id)
        lines = []
        for rar in RARITY_ORDER:
            owned = [(cid, coll[cid]) for cid in coll if catalog.get(cid, ("", "common", None))[1] == rar]
            if owned:
                r = RARITIES[rar]
                items = ", ".join(f"{catalog.get(cid, (cid, '', None))[0]} ×{c}" for cid, c in owned)
                lines.append(f"{r['emoji']} **{r['label']}**: {items}")
        total = sum(coll.values())
        embed = discord.Embed(
            title=f"🎴 Yami-Sammlung von {target.display_name}",
            description="\n".join(lines) or "_leer_",
            color=0x5865F2,
        )
        embed.set_footer(text=f"{len(coll)}/{len(catalog)} verschiedene · {total} Karten gesamt")
        await interaction.response.send_message(embed=embed)

    @booster.command(name="card", description="Zeigt eine Yami-Karte.")
    @app_commands.describe(karte="Welche Karte?")
    @app_commands.autocomplete(karte=_server_card_autocomplete)
    async def card(self, interaction: discord.Interaction, karte: str) -> None:
        catalog = _catalog(self.db, interaction.guild_id)
        card_id = karte if karte in catalog else next(
            (cid for cid, (name, _, _) in catalog.items() if name.lower() == karte.lower()), None
        )
        if card_id is None:
            await interaction.response.send_message("⚠️ Diese Karte gibt es nicht.", ephemeral=True)
            return
        name, rarity, url = catalog[card_id]
        owned = self.db.get_server_collection(interaction.guild_id, interaction.user.id).get(card_id, 0)
        await interaction.response.send_message(embed=self._card_embed(name, rarity, url, owned=owned))

    # --- /yamicard (Mods) ---------------------------------------------------

    yamicard = app_commands.Group(
        name="yamicard",
        description="Yami-Karten verwalten (nur Mods).",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @yamicard.command(name="add", description="Legt eine Yami-Karte an.")
    @app_commands.describe(name="Kartenname", seltenheit="Seltenheit", bild_url="Bild-URL (Pflicht, http/https)")
    @app_commands.choices(seltenheit=[app_commands.Choice(name=RARITIES[r]["label"], value=r) for r in RARITIES])
    async def add(
        self, interaction: discord.Interaction, name: str,
        seltenheit: app_commands.Choice[str], bild_url: str,
    ) -> None:
        card_id = _slug(name)
        if card_id is None:
            await interaction.response.send_message("⚠️ Ungültiger Name.", ephemeral=True)
            return
        if not bild_url.startswith(("http://", "https://")):
            await interaction.response.send_message(
                "⚠️ Die Bild-URL muss mit http(s):// beginnen.", ephemeral=True
            )
            return
        self.db.add_server_card(interaction.guild_id, card_id, name, seltenheit.value, bild_url)
        await interaction.response.send_message(
            content="✅ Yami-Karte angelegt:",
            embed=self._card_embed(name, seltenheit.value, bild_url),
            ephemeral=True,
        )

    @yamicard.command(name="remove", description="Entfernt eine Yami-Karte.")
    @app_commands.describe(karte="Welche Karte entfernen?")
    @app_commands.autocomplete(karte=_server_card_autocomplete)
    async def remove(self, interaction: discord.Interaction, karte: str) -> None:
        if self.db.remove_server_card(interaction.guild_id, karte):
            await interaction.response.send_message("🗑️ Yami-Karte entfernt.", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ Diese Karte gibt es nicht.", ephemeral=True)

    @yamicard.command(name="list", description="Zeigt alle Yami-Karten.")
    async def list_(self, interaction: discord.Interaction) -> None:
        cards = self.db.list_server_cards(interaction.guild_id)
        if not cards:
            await interaction.response.send_message(
                "Es gibt noch keine Yami-Karten. Anlegen mit `/yamicard add`.", ephemeral=True
            )
            return
        by_rar: dict[str, list[str]] = {}
        for _cid, name, rarity, _url in cards:
            by_rar.setdefault(rarity, []).append(name)
        lines = [
            f"{RARITIES[r]['emoji']} **{RARITIES[r]['label']}**: " + ", ".join(by_rar[r])
            for r in RARITY_ORDER if r in by_rar
        ]
        embed = discord.Embed(title="🎴 Yami-Karten", description="\n".join(lines), color=0x5865F2)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BoosterCog(bot))

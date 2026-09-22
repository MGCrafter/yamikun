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
from cogs.uiembeds import reward_embed, VIOLET

logger = logging.getLogger("oaken-tower-bot")

COIN_EMOJI_NAME = "YamiToken"
COIN_FALLBACK = "🪙"

# Fallback-Emote für Spiel-Booster, wenn pro Spiel keins im Webpanel gesetzt ist.
GAME_BOOSTER_FALLBACK = "🎴"
# Optionale Standard-Emotes für bekannte Spiele (nur, solange im Webpanel nichts
# eigenes hinterlegt wurde). Schlüssel kleingeschrieben (wie der gespeicherte Spielname).
# Bewusst leer — kein hardcodiertes Spiel-Emote mehr; pro Spiel im Webpanel setzbar,
# sonst der allgemeine Fallback (🎴).
DEFAULT_GAME_BOOSTER_EMOJI: dict[str, str] = {}


def resolve_booster_emoji(guild, db, game: str) -> str:
    """Anzeige-Emote für das Spiel-Booster eines Spiels.

    Reihenfolge: im Webpanel gesetzter Wert → Standard für bekannte Spiele → Fallback 🎴.
    Ein gespeicherter Wert kann ein Emoji-*Name* (Server-Emoji) oder ein direkter
    Wert sein (Unicode-Emoji oder fertiges ``<:name:id>``)."""
    value = db.get_reward_game_emoji(guild.id, game) if guild is not None else None
    if not value:
        value = DEFAULT_GAME_BOOSTER_EMOJI.get(game.strip().lower())
    if not value:
        return GAME_BOOSTER_FALLBACK
    if guild is not None:
        emoji = discord.utils.get(guild.emojis, name=value)
        if emoji is not None:
            return str(emoji)
    return value

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

# Spiel-Booster: ziehen aus dem erspielten Karten-Pool EINES Spiels (custom_cards).
# Bewusst teuer, damit das Erspielen sich weiterhin lohnt — der Pack ist nur die
# Alternative für Leute mit ausgeschalteter Aktivität, kein Ersatz fürs Spielen.
GAMECARD_PACK: dict = {
    "label": "Spiel-Booster", "emoji": "🎴", "price": 200_000, "cards": 5,
    "weights": {"common": 50, "uncommon": 28, "rare": 15, "epic": 6, "legendary": 1, "mythic": 0.2},
}

# Godpack — extrem seltener Sonderfall beim Spiel-Booster: EINE Karte, ausschließlich
# Legendary oder Mythic, wobei Mythic noch einmal viel seltener ist.
GODPACK_CHANCE = 0.002  # 0,2 % pro geöffnetem Spiel-Booster
GODPACK_WEIGHTS = {"legendary": 97, "mythic": 3}


def _game_pack_type(game: str) -> str:
    """Pack-Typ-Schlüssel für ein Spiel — enthält den Spielnamen, damit beim Öffnen
    der richtige Karten-Pool gezogen werden kann."""
    return "game:" + game.strip().lower()


def _is_game_pack(pack_type: str) -> bool:
    return pack_type.startswith("game:")


def _game_of(pack_type: str) -> str:
    return pack_type[len("game:"):]


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


async def _game_with_cards_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Spiele, für die es erspielte Karten gibt (nur die lassen sich als Pack kaufen)."""
    db = interaction.client.db  # type: ignore[attr-defined]
    games = sorted({g for _cid, _n, _r, _u, g in db.list_custom_cards(interaction.guild_id) if g})
    cur = current.lower()
    return [app_commands.Choice(name=g, value=g) for g in games if cur in g][:25]


async def _owned_game_pack_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Spiel-Booster, die der User besitzt."""
    db = interaction.client.db  # type: ignore[attr-defined]
    owned = db.list_packs(interaction.guild_id, interaction.user.id)
    cur = current.lower()
    out: list[app_commands.Choice[str]] = []
    for pt, n in owned.items():
        if _is_game_pack(pt):
            g = _game_of(pt)
            if cur in g:
                out.append(app_commands.Choice(name=f"{g} ({n}×)", value=g))
    return out[:25]


def _reveal_order(catalog: dict, drawn: list[str]) -> list[tuple[str, str, str | None]]:
    """Gezogene Karten zum Aufdecken sortieren: häufigste zuerst, RARSTE ZULETZT.

    RARITY_ORDER ist von selten→häufig (Index 0 = am seltensten), daher absteigend
    nach Index sortieren, damit die seltenste Karte am Ende kommt.
    """
    ordered = sorted(drawn, key=lambda cid: RARITY_ORDER.index(catalog[cid][1]), reverse=True)
    return [(catalog[cid][0], catalog[cid][1], catalog[cid][2]) for cid in ordered]


def _maybe_godpack(catalog: dict) -> list[str] | None:
    """Godpack-Wurf für EINEN Spiel-Booster: mit GODPACK_CHANCE eine einzelne
    Legendary/Mythic-Karte. Gibt [card_id] zurück, sonst None (= normales Pack)."""
    if random.random() >= GODPACK_CHANCE:
        return None
    pool = {cid: c for cid, c in catalog.items() if c[1] in GODPACK_WEIGHTS}
    if not pool:
        return None
    rarities = list(GODPACK_WEIGHTS)
    rar = random.choices(rarities, weights=[GODPACK_WEIGHTS[r] for r in rarities], k=1)[0]
    cands = [cid for cid, c in pool.items() if c[1] == rar] or list(pool)
    return [random.choice(cands)]


def _bulk_summary(
    catalog: dict, drawn: list[str], *, title: str, color: int,
    godpacks: int = 0, member: discord.abc.User | None = None, footer: str | None = None,
) -> discord.Embed:
    """Zusammenfassung beim Öffnen mehrerer Packs auf einmal (statt Einzel-Reveal)."""
    counts: dict[str, int] = {}
    for cid in drawn:
        r = catalog[cid][1]
        counts[r] = counts.get(r, 0) + 1
    dist = "\n".join(
        f"{RARITIES[r]['emoji']} **{RARITIES[r]['label']}**: {counts[r]}"
        for r in RARITY_ORDER if counts.get(r)
    ) or "—"
    best = sorted(drawn, key=lambda c: RARITY_ORDER.index(catalog[c][1]))[:5]
    highlights = " · ".join(f"{RARITIES[catalog[c][1]]['emoji']} {catalog[c][0]}" for c in best)
    embed = discord.Embed(title=title, color=color)
    if member is not None:
        embed.set_author(name="✦  PACKS GEÖFFNET", icon_url=member.display_avatar.url)
    embed.add_field(name=f"📦 {len(drawn)} Karten", value=dist, inline=False)
    if highlights:
        embed.add_field(name="🌟 Highlights (seltenste)", value=highlights, inline=False)
    if godpacks:
        embed.add_field(name="✨ Godpacks", value=f"**{godpacks}**", inline=False)
    embed.set_footer(text=footer or "Glück gehabt? Öffne mehr Packs!")
    return embed


class RevealView(discord.ui.View):
    """Deckt die Karten eines Packs einzeln auf — die seltenste zuletzt (Überraschung)."""

    def __init__(
        self, opener_id: int, opener_name: str, opener_icon: str | None,
        cards: list[tuple[str, str, str | None]], title: str, *, godpack: bool = False,
        summary: discord.Embed | None = None,
    ) -> None:
        super().__init__(timeout=300)
        self.opener_id = opener_id
        self.opener_name = opener_name
        self.opener_icon = opener_icon
        self.cards = cards
        self.title = title
        self.godpack = godpack
        self.summary = summary
        self.idx = 0
        # „Übersicht"-Button nur bei mehreren Karten + vorhandener Zusammenfassung.
        if summary is None:
            self.remove_item(self._skip)
        # Bei nur einer Karte (z.B. Godpack) gibt es nichts durchzuklicken.
        if len(self.cards) <= 1:
            self._next.disabled = True
            self._next.label = "Fertig ✓"

    def embed(self) -> discord.Embed:
        name, rarity, url = self.cards[self.idx]
        r = RARITIES.get(rarity, RARITIES["common"])
        total = len(self.cards)
        color = 0xFFD700 if self.godpack else r["color"]
        desc = f"Seltenheit: **{r['label']}**\nKarte **{self.idx + 1}/{total}**"
        embed = discord.Embed(title=f"{r['emoji']} {name}", description=desc, color=color)
        if url:
            embed.set_image(url=url)
        embed.set_author(
            name=("✨ GODPACK ✨ " if self.godpack else "") + self.title,
            icon_url=self.opener_icon or discord.utils.MISSING,
        )
        if self.idx >= total - 1:
            embed.set_footer(
                text=("Ein GODPACK! 🌟" if self.godpack
                      else "Das war die letzte — und seltenste — Karte! 🎉")
            )
        else:
            embed.set_footer(text="Tippe „Weiter ▶“, um die nächste Karte aufzudecken.")
        return embed

    @discord.ui.button(label="Weiter ▶", style=discord.ButtonStyle.primary)
    async def _next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.opener_id:
            await interaction.response.send_message("Das ist nicht dein Pack. 😉", ephemeral=True)
            return
        if self.idx < len(self.cards) - 1:
            self.idx += 1
        if self.idx >= len(self.cards) - 1:
            button.disabled = True
            button.label = "Fertig ✓"
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="⏭ Übersicht", style=discord.ButtonStyle.secondary)
    async def _skip(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if interaction.user.id != self.opener_id:
            await interaction.response.send_message("Das ist nicht dein Pack. 😉", ephemeral=True)
            return
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(embed=self.summary, view=self)


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
        # Kosten atomar abbuchen (nur wenn das Guthaben reicht) – verhindert Races.
        if not self.db.spend_coins(interaction.guild_id, interaction.user.id, cost):
            await interaction.response.send_message(
                f"⚠️ Du hast nur **{_fmt(balance)}** {coin}, brauchst aber **{_fmt(cost)}**.",
                ephemeral=True,
            )
            return
        total = self.db.add_packs(interaction.guild_id, interaction.user.id, typ.value, anzahl)
        await interaction.response.send_message(
            embed=reward_embed(
                badge="🛒  PACK GEKAUFT",
                title=f"{pack['emoji']}  +{anzahl} {pack['label']}",
                member=interaction.user,
                description=f"Gekauft für **{_fmt(cost)}** {coin}.",
                total=total,
                total_label="Packs im Inventar",
                hint=f"Öffnen mit `/booster open typ:{pack['label']}`",
                footer="Öffne dein Pack und sammle Yami-Karten.",
                color=VIOLET,
            ),
            ephemeral=True,
        )

    @booster.command(name="open", description="Öffne ein oder mehrere Booster-Packs.")
    @app_commands.describe(typ="Welches Pack öffnen?", anzahl="Wie viele auf einmal? (Standard 1)")
    @app_commands.choices(typ=[app_commands.Choice(name=PACKS[p]["label"], value=p) for p in PACKS])
    async def open(
        self, interaction: discord.Interaction, typ: app_commands.Choice[str],
        anzahl: app_commands.Range[int, 1, 100] = 1,
    ) -> None:
        pack = PACKS[typ.value]
        # Mehrere Packs können >3s dauern → Interaction sofort defern (15-Min-Frist).
        await interaction.response.defer()
        catalog = _catalog(self.db, interaction.guild_id)
        if not catalog:
            await interaction.followup.send(
                "⚠️ Es gibt noch keine Yami-Karten. Ein Mod kann welche mit `/yamicard add` anlegen.",
                ephemeral=True,
            )
            return

        all_drawn: list[str] = []
        opened = 0
        for _ in range(anzahl):
            if not self.db.consume_pack(interaction.guild_id, interaction.user.id, typ.value):
                break  # keine weiteren Packs vorhanden
            opened += 1
            for _ in range(pack["cards"]):
                cid = _roll(catalog, pack["weights"])
                all_drawn.append(cid)
                self.db.add_server_card_owned(interaction.guild_id, interaction.user.id, cid)

        if opened == 0:
            await interaction.followup.send(
                f"⚠️ Du hast kein **{pack['label']}**. Kaufe eins mit `/booster buy`.", ephemeral=True
            )
            return

        if opened == 1:
            # Ein Pack → Karten einzeln aufdecken (seltenste zuletzt).
            view = RevealView(
                interaction.user.id, interaction.user.display_name,
                interaction.user.display_avatar.url,
                _reveal_order(catalog, all_drawn), f"{pack['emoji']} {pack['label']} geöffnet!",
            )
            await interaction.followup.send(embed=view.embed(), view=view)
        else:
            # Mehrere Packs → einzeln durchklicken, „⏭ Übersicht" springt zur Zusammenfassung.
            top = min(all_drawn, key=lambda c: RARITY_ORDER.index(catalog[c][1]))
            summary = _bulk_summary(
                catalog, all_drawn,
                title=f"{pack['emoji']}  {opened}× {pack['label']} geöffnet",
                color=RARITIES[catalog[top][1]]["color"], member=interaction.user,
            )
            view = RevealView(
                interaction.user.id, interaction.user.display_name,
                interaction.user.display_avatar.url,
                _reveal_order(catalog, all_drawn),
                f"{pack['emoji']} {opened}× {pack['label']}", summary=summary,
            )
            await interaction.followup.send(embed=view.embed(), view=view)

    @booster.command(name="buygame", description="Kaufe einen Spiel-Booster mit Karten eines bestimmten Spiels (200.000 Coins).")
    @app_commands.describe(spiel="Für welches Spiel?", anzahl="Wie viele? (Standard 1)")
    @app_commands.autocomplete(spiel=_game_with_cards_autocomplete)
    async def buygame(
        self, interaction: discord.Interaction, spiel: str,
        anzahl: app_commands.Range[int, 1, 100] = 1,
    ) -> None:
        cards = self.db.list_custom_cards_for_game(interaction.guild_id, spiel)
        if not cards:
            await interaction.response.send_message(
                f"⚠️ Für **{spiel}** gibt es keine Karten (oder das Spiel existiert nicht).", ephemeral=True
            )
            return
        coin = self._coin(interaction.guild)
        cost = GAMECARD_PACK["price"] * anzahl
        balance = int(self.db.get_user(interaction.guild_id, interaction.user.id)["coins"])
        # Kosten atomar abbuchen (nur wenn das Guthaben reicht) – verhindert Races.
        if not self.db.spend_coins(interaction.guild_id, interaction.user.id, cost):
            await interaction.response.send_message(
                f"⚠️ Du hast nur **{_fmt(balance)}** {coin}, brauchst aber **{_fmt(cost)}**.", ephemeral=True
            )
            return
        total = self.db.add_packs(interaction.guild_id, interaction.user.id, _game_pack_type(spiel), anzahl)
        emote = resolve_booster_emoji(interaction.guild, self.db, spiel)
        await interaction.response.send_message(
            embed=reward_embed(
                badge="🛒  SPIEL-BOOSTER GEKAUFT",
                title=f"{emote}  +{anzahl} Spiel-Booster",
                member=interaction.user,
                description=f"Gekauft für **{_fmt(cost)}** {coin}.",
                game=spiel,
                total=total,
                total_label="Booster im Inventar",
                hint=f"Öffnen mit `/booster opengame spiel:{spiel}`",
                color=VIOLET,
            ),
            ephemeral=True,
        )

    @booster.command(name="opengame", description="Öffne ein oder mehrere Spiel-Booster — Karten landen in deiner Sammlung.")
    @app_commands.describe(spiel="Welches Spiel-Booster öffnen?", anzahl="Wie viele auf einmal? (Standard 1)")
    @app_commands.autocomplete(spiel=_owned_game_pack_autocomplete)
    async def opengame(
        self, interaction: discord.Interaction, spiel: str,
        anzahl: app_commands.Range[int, 1, 100] = 1,
    ) -> None:
        # Mehrere Packs können >3s dauern → Interaction sofort defern (15-Min-Frist).
        await interaction.response.defer()
        catalog = {
            cid: (name, rarity, url)
            for cid, name, rarity, url in self.db.list_custom_cards_for_game(interaction.guild_id, spiel)
        }
        if not catalog:
            await interaction.followup.send(
                f"⚠️ Für **{spiel}** gibt es keine Karten mehr.", ephemeral=True
            )
            return

        all_drawn: list[str] = []
        opened = 0
        godpacks = 0
        for _ in range(anzahl):
            if not self.db.consume_pack(interaction.guild_id, interaction.user.id, _game_pack_type(spiel)):
                break
            opened += 1
            gp = _maybe_godpack(catalog)  # sehr seltener Godpack pro Pack
            cards = gp if gp is not None else [
                _roll(catalog, GAMECARD_PACK["weights"]) for _ in range(GAMECARD_PACK["cards"])
            ]
            if gp is not None:
                godpacks += 1
            for cid in cards:
                self.db.add_card(interaction.guild_id, interaction.user.id, cid)
                all_drawn.append(cid)

        if opened == 0:
            await interaction.followup.send(
                f"⚠️ Du hast kein **Spiel-Booster ({spiel})**. Kaufe eins mit `/booster buygame`.", ephemeral=True
            )
            return

        emote = resolve_booster_emoji(interaction.guild, self.db, spiel)
        if opened == 1:
            godpack = godpacks == 1
            title = (f"✨ GODPACK ✨ ({spiel})" if godpack
                     else f"{emote} Spiel-Booster ({spiel}) geöffnet!")
            view = RevealView(
                interaction.user.id, interaction.user.display_name,
                interaction.user.display_avatar.url,
                _reveal_order(catalog, all_drawn), title, godpack=godpack,
            )
            await interaction.followup.send(
                content=("🌟 **Ein GODPACK!** 🌟" if godpack else None),
                embed=view.embed(), view=view,
            )
        else:
            top = min(all_drawn, key=lambda c: RARITY_ORDER.index(catalog[c][1]))
            summary = _bulk_summary(
                catalog, all_drawn,
                title=f"{emote}  {opened}× Spiel-Booster ({spiel})",
                color=RARITIES[catalog[top][1]]["color"], godpacks=godpacks,
                member=interaction.user,
                footer="Die Karten sind in deiner /gamecards-Sammlung.",
            )
            view = RevealView(
                interaction.user.id, interaction.user.display_name,
                interaction.user.display_avatar.url,
                _reveal_order(catalog, all_drawn),
                f"{emote} {opened}× Spiel-Booster ({spiel})", summary=summary,
            )
            await interaction.followup.send(
                content=("🌟 **GODPACK dabei!** 🌟" if godpacks else None),
                embed=view.embed(), view=view,
            )

    @booster.command(name="packs", description="Zeigt deine ungeöffneten Packs.")
    async def packs(self, interaction: discord.Interaction) -> None:
        owned = self.db.list_packs(interaction.guild_id, interaction.user.id)
        yami = {t: n for t, n in owned.items() if t in PACKS}
        games = {t: n for t, n in owned.items() if _is_game_pack(t)}
        if not yami and not games:
            await interaction.response.send_message(
                "Du hast keine Packs. Kaufe welche mit `/booster buy` oder `/booster buygame`. 📦",
                ephemeral=True,
            )
            return
        lines = [f"{PACKS[t]['emoji']} **{PACKS[t]['label']}**: {n}×" for t, n in yami.items()]
        lines += [
            f"{resolve_booster_emoji(interaction.guild, self.db, _game_of(t))} "
            f"**Spiel-Booster ({_game_of(t)})**: {n}×"
            for t, n in games.items()
        ]
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
            color=0x7C3AED,
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
        embed = discord.Embed(title="🎴 Yami-Karten", description="\n".join(lines), color=0x7C3AED)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BoosterCog(bot))

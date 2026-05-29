"""Spiel-Rewards: Sammelkarten fürs Spielen konfigurierter Spiele.

- Karten sind PRO SPIEL: spielt jemand Spiel X, droppen nur die (eigenen) Karten von X.
- Hat ein Spiel keine Karten, droppt nichts (kein eingebautes Set mehr).
- Jede Karte hat eine eigene Bild-URL (Pflicht beim Anlegen).
- Pro 30 Min Spielzeit gibt es 1 zufällige Karte, max. 12/Tag.
- Erkennung via Presence (braucht das privilegierte Presence Intent).
"""

from __future__ import annotations

import datetime
import logging
import random
import re
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

logger = logging.getLogger("oaken-tower-bot")

CARD_INTERVAL = 1800
DAILY_CAP = 12
SETTLE_MINUTES = 10.0

RARITIES: dict[str, dict] = {
    "common":    {"label": "Common",    "emoji": "⚪", "color": 0xB0B0B0, "weight": 50},
    "uncommon":  {"label": "Uncommon",  "emoji": "🟢", "color": 0x2ECC71, "weight": 28},
    "rare":      {"label": "Rare",      "emoji": "🔵", "color": 0x3498DB, "weight": 15},
    "epic":      {"label": "Epic",      "emoji": "🟣", "color": 0x9B59B6, "weight": 6},
    "legendary": {"label": "Legendary", "emoji": "🟡", "color": 0xF1C40F, "weight": 1},
    "mythic":    {"label": "Mythic",    "emoji": "🔴", "color": 0xE74C3C, "weight": 0.3},
}
RARITY_ORDER = ["mythic", "legendary", "epic", "rare", "uncommon", "common"]


def build_game_catalog(db, guild_id: int, game: str | None) -> dict[str, tuple[str, str, str | None]]:
    """Karten eines Spiels (nur eigene Karten). Ohne Karten droppt nichts."""
    if not game:
        return {}
    return {
        cid: (name, rarity, url)
        for cid, name, rarity, url in db.list_custom_cards_for_game(guild_id, game)
    }


def build_full_catalog(db, guild_id: int) -> dict[str, tuple[str, str, str | None]]:
    """Alle Karten der Guild (für Anzeige/Sammlung)."""
    return {
        cid: (name, rarity, url)
        for cid, name, rarity, url, _game in db.list_custom_cards(guild_id)
    }


def _slug(game: str, name: str) -> str | None:
    g = re.sub(r"[^a-z0-9]+", "", game.lower())
    n = re.sub(r"[^a-z0-9]+", "", name.lower())
    return f"custom_{g}_{n}" if n else None


def _today() -> str:
    return datetime.date.today().isoformat()


def _roll_card(catalog: dict[str, tuple[str, str, str | None]]) -> str:
    rarities = [r for r in RARITIES if any(c[1] == r for c in catalog.values())]
    weights = [RARITIES[r]["weight"] for r in rarities]
    rarity = random.choices(rarities, weights=weights, k=1)[0]
    pool = [cid for cid, c in catalog.items() if c[1] == rarity]
    return random.choice(pool)


async def _card_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    catalog = build_full_catalog(interaction.client.db, interaction.guild_id)  # type: ignore[attr-defined]
    cur = current.lower()
    return [
        app_commands.Choice(name=f"{RARITIES[rarity]['emoji']} {name}", value=cid)
        for cid, (name, rarity, _) in catalog.items()
        if cur in name.lower()
    ][:25]


async def _custom_card_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    cur = current.lower()
    cards = interaction.client.db.list_custom_cards(interaction.guild_id)  # type: ignore[attr-defined]
    return [
        app_commands.Choice(name=f"{name} ({game or '—'})", value=cid)
        for cid, name, _rar, _url, game in cards
        if cur in name.lower()
    ][:25]


async def _game_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    games = interaction.client.db.list_reward_games(interaction.guild_id)  # type: ignore[attr-defined]
    return [app_commands.Choice(name=g, value=g) for g in games if current.lower() in g][:25]


async def _owned_card_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    db = interaction.client.db  # type: ignore[attr-defined]
    collection = db.get_collection(interaction.guild_id, interaction.user.id)
    catalog = build_full_catalog(db, interaction.guild_id)
    cur = current.lower()
    out: list[app_commands.Choice[str]] = []
    for cid, count in collection.items():
        name, rarity, _ = catalog.get(cid, (cid, "common", None))
        if cur in name.lower():
            out.append(
                app_commands.Choice(name=f"{RARITIES[rarity]['emoji']} {name} ×{count}", value=cid)
            )
    return out[:25]


class CardPaginator(discord.ui.View):
    """Blättert durch die besessenen Karten einer Sammlung (eine Karte pro Seite)."""

    def __init__(
        self,
        cog: "GameCardsCog",
        *,
        viewer_id: int,
        owner: discord.abc.User,
        cards: list[tuple[str, str, str | None, str | None, int]],
    ) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.viewer_id = viewer_id
        self.owner = owner
        self.cards = cards  # (name, rarity, url, game, count)
        self.index = 0
        self.message: discord.Message | None = None
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.prev_button.disabled = self.index <= 0
        self.next_button.disabled = self.index >= len(self.cards) - 1

    def embed(self) -> discord.Embed:
        name, rarity, url, game, count = self.cards[self.index]
        embed = self.cog._embed_for(name, rarity, url, owned=count)
        embed.set_author(name=f"Sammlung von {self.owner.display_name}")
        embed.set_footer(
            text=f"{game or '—'} · Karte {self.index + 1}/{len(self.cards)}"
        )
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.viewer_id:
            await interaction.response.send_message(
                "Das sind nicht deine Buttons 🙂", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(emoji="◀", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.index = max(0, self.index - 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(emoji="▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.index = min(len(self.cards) - 1, self.index + 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.embed(), view=self)


class TradeOfferSelect(discord.ui.Select):
    """Dropdown, mit dem der angefragte User seine Gegen-Karte wählt."""

    def __init__(self, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Wähle deine Karte zum Tauschen…", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: "TradeView" = self.view  # type: ignore[assignment]
        if interaction.user.id != view.partner.id:
            await interaction.response.send_message(
                "Nur die angefragte Person wählt hier eine Karte.", ephemeral=True
            )
            return
        view.partner_card = self.values[0]
        view.confirmed.clear()  # neue Auswahl → beide müssen erneut bestätigen
        await interaction.response.edit_message(embed=view.embed(), view=view)


class TradeView(discord.ui.View):
    """Beidseitiger Kartentausch mit Bestätigung durch beide Seiten."""

    def __init__(
        self,
        cog: "GameCardsCog",
        *,
        initiator: discord.Member,
        partner: discord.Member,
        initiator_card: str,
        catalog: dict[str, tuple[str, str, str | None]],
        partner_options: list[discord.SelectOption],
    ) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.initiator = initiator
        self.partner = partner
        self.initiator_card = initiator_card
        self.partner_card: str | None = None
        self.catalog = catalog
        self.confirmed: set[int] = set()
        self.message: discord.Message | None = None
        self.finished = False
        self.add_item(TradeOfferSelect(partner_options))

    def _label(self, cid: str | None) -> str:
        if cid is None:
            return "_noch nicht gewählt_"
        name, rarity, _ = self.catalog.get(cid, (cid, "common", None))
        return f"{RARITIES[rarity]['emoji']} **{name}**"

    def embed(self) -> discord.Embed:
        def mark(uid: int) -> str:
            return "✅" if uid in self.confirmed else "⬜"

        embed = discord.Embed(
            title="🔄 Kartentausch",
            description=(
                f"{mark(self.initiator.id)} {self.initiator.mention} bietet: {self._label(self.initiator_card)}\n"
                f"{mark(self.partner.id)} {self.partner.mention} bietet: {self._label(self.partner_card)}\n\n"
                "Beide müssen **Annehmen** klicken. Eine neue Kartenwahl setzt die Bestätigungen zurück."
            ),
            color=0x5865F2,
        )
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in (self.initiator.id, self.partner.id):
            await interaction.response.send_message(
                "Dieser Tausch gehört nicht dir 🙂", ephemeral=True
            )
            return False
        return True

    async def _finish(self, view_disabled: bool = True) -> None:
        self.finished = True
        if view_disabled:
            for child in self.children:
                child.disabled = True  # type: ignore[attr-defined]
        self.stop()

    async def on_timeout(self) -> None:
        if self.finished:
            return
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        if self.message is not None:
            try:
                await self.message.edit(content="⌛ Tausch abgelaufen.", view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="Annehmen", emoji="✅", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if self.partner_card is None:
            await interaction.response.send_message(
                f"{self.partner.mention} muss zuerst eine Karte auswählen.", ephemeral=True
            )
            return
        self.confirmed.add(interaction.user.id)
        if {self.initiator.id, self.partner.id}.issubset(self.confirmed):
            ok = self.cog.db.trade_cards(
                interaction.guild_id, self.initiator.id, self.initiator_card,
                self.partner.id, self.partner_card,
            )
            await self._finish()
            if ok:
                done = discord.Embed(
                    title="✅ Tausch abgeschlossen!",
                    description=(
                        f"{self.partner.mention} erhält {self._label(self.initiator_card)}\n"
                        f"{self.initiator.mention} erhält {self._label(self.partner_card)}"
                    ),
                    color=0x2ECC71,
                )
                await interaction.response.edit_message(content=None, embed=done, view=self)
            else:
                await interaction.response.edit_message(
                    content="⚠️ Tausch fehlgeschlagen — jemand besitzt seine Karte nicht mehr.",
                    embed=None, view=self,
                )
            return
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Ablehnen", emoji="❌", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._finish()
        await interaction.response.edit_message(
            content=f"❌ Tausch von {interaction.user.mention} abgebrochen.", embed=None, view=self
        )


class GameCardsCog(commands.Cog):
    """Sammelkarten als Spiel-Reward + /cards, /card, /gamereward."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]
        self.active: dict[tuple[int, int], tuple[float, str]] = {}  # key -> (start, game)

    async def cog_load(self) -> None:
        self.settle_loop.start()

    def cog_unload(self) -> None:
        self.settle_loop.cancel()

    def _embed_for(self, name: str, rarity: str, image_url: str | None, *, owned: int | None = None, prefix: str = "") -> discord.Embed:
        r = RARITIES.get(rarity, RARITIES["common"])
        embed = discord.Embed(
            title=f"{prefix}{r['emoji']} {name}".strip(),
            description=f"Seltenheit: **{r['label']}**"
            + (f"\nIn deiner Sammlung: **{owned}×**" if owned is not None else ""),
            color=r["color"],
        )
        if image_url:
            embed.set_image(url=image_url)
        return embed

    # --- Presence-Tracking ----------------------------------------------------

    def _current_game(self, member: discord.Member) -> str | None:
        games = set(self.db.list_reward_games(member.guild.id))
        if not games:
            return None
        for act in member.activities:
            if act.type == discord.ActivityType.playing and act.name and act.name.lower() in games:
                return act.name.lower()
        return None

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member) -> None:
        if after.guild is None or after.bot:
            return
        key = (after.guild.id, after.id)
        current = self._current_game(after)
        now = time.time()
        if key in self.active:
            start, game = self.active[key]
            if current != game:  # gestoppt oder Spiel gewechselt
                del self.active[key]
                await self._credit(after.guild, after, now - start, game)
                if current is not None:
                    self.active[key] = (now, current)
        elif current is not None:
            self.active[key] = (now, current)

    @tasks.loop(minutes=SETTLE_MINUTES)
    async def settle_loop(self) -> None:
        now = time.time()
        for key in list(self.active):
            guild = self.bot.get_guild(key[0])
            member = guild.get_member(key[1]) if guild else None
            start, game = self.active.get(key, (now, ""))
            if member is None:
                self.active.pop(key, None)
                continue
            current = self._current_game(member)
            self.active.pop(key, None)
            await self._credit(member.guild, member, now - start, game)
            if current is not None:
                self.active[key] = (now, current)

    @settle_loop.before_loop
    async def _before_settle(self) -> None:
        await self.bot.wait_until_ready()

    async def _credit(self, guild: discord.Guild, member: discord.Member, seconds: float, game: str | None) -> None:
        secs = int(seconds)
        if secs <= 0:
            return
        catalog = build_game_catalog(self.db, guild.id, game)
        if not catalog:
            return  # keine Karten für dieses Spiel angelegt → nichts zu vergeben
        acc, day, cards_today = self.db.get_playtime(guild.id, member.id)
        today = _today()
        if day != today:
            day, cards_today = today, 0
        acc += secs
        granted: list[str] = []
        while acc >= CARD_INTERVAL and cards_today < DAILY_CAP:
            acc -= CARD_INTERVAL
            cards_today += 1
            cid = _roll_card(catalog)
            self.db.add_card(guild.id, member.id, cid)
            granted.append(cid)
        if cards_today >= DAILY_CAP:
            acc = min(acc, CARD_INTERVAL - 1)
        self.db.set_playtime(guild.id, member.id, acc, day, cards_today)
        if not granted:
            return
        # Ziel: konfigurierter Karten-Channel (öffentlich), sonst DM an den User.
        channel = None
        chan_id = self.db.get_card_channel(guild.id)
        if chan_id:
            ch = guild.get_channel(chan_id)
            if isinstance(ch, discord.abc.Messageable):
                channel = ch
        for cid in granted:
            name, rarity, url = catalog[cid]
            embed = self._embed_for(name, rarity, url, prefix="🎴 Neue Karte! ")
            if channel is not None:
                try:
                    await channel.send(
                        content=f"🎴 {member.mention} hat eine Karte erspielt!",
                        embed=embed,
                        allowed_mentions=discord.AllowedMentions(users=True),
                    )
                    continue
                except discord.Forbidden:
                    pass  # fällt unten auf DM zurück
            try:
                await member.send(embed=embed)
            except discord.HTTPException:
                pass

    # --- Sammlungs-Commands ---------------------------------------------------

    @app_commands.command(name="gamecards", description="Zeigt deine erspielten Sammelkarten.")
    @app_commands.guild_only()
    @app_commands.describe(user="Optional: wessen Sammlung? (Standard: du)")
    async def gamecards(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        target = user or interaction.user
        collection = self.db.get_collection(interaction.guild_id, target.id)
        if not collection:
            await interaction.response.send_message(
                f"{target.display_name} hat noch keine Karten. Spiel ein konfiguriertes Spiel, um welche zu erspielen! 🎴",
                ephemeral=True,
            )
            return
        # Vollständiger Katalog mit Spiel-Zuordnung für die Sortierung.
        catalog = {
            cid: (name, rarity, url, game)
            for cid, name, rarity, url, game in self.db.list_custom_cards(interaction.guild_id)
        }
        rar_index = {r: i for i, r in enumerate(RARITY_ORDER)}
        cards: list[tuple[str, str, str | None, str | None, int]] = []
        for cid, count in collection.items():
            name, rarity, url, game = catalog.get(cid, (cid, "common", None, None))
            cards.append((name, rarity, url, game, count))
        # Sortierung: nach Spiel, innerhalb davon nach Seltenheit (beste zuerst), dann Name.
        cards.sort(key=lambda c: ((c[3] or "").lower(), rar_index.get(c[1], len(RARITY_ORDER)), c[0].lower()))

        view = CardPaginator(self, viewer_id=interaction.user.id, owner=target, cards=cards)
        await interaction.response.send_message(embed=view.embed(), view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="gamecard", description="Zeigt eine einzelne erspielte Karte.")
    @app_commands.guild_only()
    @app_commands.describe(karte="Welche Karte?")
    @app_commands.autocomplete(karte=_card_autocomplete)
    async def gamecard(self, interaction: discord.Interaction, karte: str) -> None:
        catalog = build_full_catalog(self.db, interaction.guild_id)
        card_id = karte if karte in catalog else next(
            (cid for cid, (name, _, _) in catalog.items() if name.lower() == karte.lower()), None
        )
        if card_id is None:
            await interaction.response.send_message("⚠️ Diese Karte gibt es nicht.", ephemeral=True)
            return
        name, rarity, url = catalog[card_id]
        owned = self.db.get_collection(interaction.guild_id, interaction.user.id).get(card_id, 0)
        await interaction.response.send_message(embed=self._embed_for(name, rarity, url, owned=owned))

    @app_commands.command(name="trade", description="Tausche eine Karte mit einem anderen Mitglied.")
    @app_commands.guild_only()
    @app_commands.describe(user="Mit wem möchtest du tauschen?", karte="Welche deiner Karten bietest du an?")
    @app_commands.autocomplete(karte=_owned_card_autocomplete)
    async def trade(self, interaction: discord.Interaction, user: discord.Member, karte: str) -> None:
        if user.bot or user.id == interaction.user.id:
            await interaction.response.send_message(
                "⚠️ Du kannst nur mit anderen Mitgliedern tauschen.", ephemeral=True
            )
            return
        catalog = build_full_catalog(self.db, interaction.guild_id)
        # Eigene Karte validieren (per ID oder Name).
        card_id = karte if karte in catalog else next(
            (cid for cid, (name, _, _) in catalog.items() if name.lower() == karte.lower()), None
        )
        if card_id is None or self.db.get_collection(interaction.guild_id, interaction.user.id).get(card_id, 0) < 1:
            await interaction.response.send_message(
                "⚠️ Diese Karte besitzt du nicht.", ephemeral=True
            )
            return
        partner_collection = self.db.get_collection(interaction.guild_id, user.id)
        if not partner_collection:
            await interaction.response.send_message(
                f"⚠️ {user.display_name} hat noch keine Karten zum Tauschen.", ephemeral=True
            )
            return
        options: list[discord.SelectOption] = []
        for cid, count in partner_collection.items():
            name, rarity, _ = catalog.get(cid, (cid, "common", None))
            options.append(discord.SelectOption(
                label=name[:100], value=cid, emoji=RARITIES[rarity]["emoji"],
                description=f"{RARITIES[rarity]['label']} · {count}× im Besitz",
            ))
        options = options[:25]
        view = TradeView(
            self, initiator=interaction.user, partner=user,
            initiator_card=card_id, catalog=catalog, partner_options=options,
        )
        await interaction.response.send_message(
            content=f"🔄 {user.mention}, {interaction.user.mention} möchte mit dir tauschen!",
            embed=view.embed(), view=view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )
        view.message = await interaction.original_response()

    # --- Mod-Konfiguration /gamereward ----------------------------------------

    gamereward = app_commands.Group(
        name="gamereward",
        description="Karten-Rewards, Spiele & Karten verwalten (nur Mods).",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @gamereward.command(name="addgame", description="Fügt ein Spiel hinzu, das Karten gibt.")
    @app_commands.describe(spiel="Exakter Spielname (wie in Discord angezeigt), z.B. Lost Ark")
    async def addgame(self, interaction: discord.Interaction, spiel: str) -> None:
        self.db.add_reward_game(interaction.guild_id, spiel)
        note = "" if self.bot.intents.presences else (
            "\n⚠️ **Presence Intent ist aus** — der Bot kann noch nicht erkennen, wer spielt."
        )
        await interaction.response.send_message(
            f"✅ **{spiel}** ist eingetragen (1 Karte pro 30 Min, max. {DAILY_CAP}/Tag).\n"
            f"Lege jetzt Karten an: `/gamereward addcard spiel:{spiel} …` "
            f"(ohne Karten gibt es keine Drops).{note}",
            ephemeral=True,
        )

    @gamereward.command(name="removegame", description="Entfernt ein Belohnungs-Spiel.")
    @app_commands.describe(spiel="Welches Spiel entfernen?")
    @app_commands.autocomplete(spiel=_game_autocomplete)
    async def removegame(self, interaction: discord.Interaction, spiel: str) -> None:
        if self.db.remove_reward_game(interaction.guild_id, spiel):
            await interaction.response.send_message(f"🗑️ **{spiel}** entfernt.", ephemeral=True)
        else:
            await interaction.response.send_message(f"⚠️ **{spiel}** war nicht eingetragen.", ephemeral=True)

    @gamereward.command(name="listgames", description="Zeigt alle Belohnungs-Spiele.")
    async def listgames(self, interaction: discord.Interaction) -> None:
        games = self.db.list_reward_games(interaction.guild_id)
        status = "🟢 aktiv" if self.bot.intents.presences else "🔴 Presence Intent aus"
        text = ("\n".join(f"• {g}" for g in games)) if games else "_keine eingetragen_"
        embed = discord.Embed(
            title="🎮 Karten-Belohnungs-Spiele",
            description=f"{text}\n\nTracking: {status}\n1 Karte / 30 Min · max. {DAILY_CAP}/Tag",
            color=0x5865F2,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @gamereward.command(name="setchannel", description="Channel für Karten-Drop-Meldungen (ohne Angabe: DMs).")
    @app_commands.describe(channel="Zielchannel — ohne Angabe gehen Drops wieder per DM raus")
    async def setchannel(
        self, interaction: discord.Interaction, channel: discord.TextChannel | None = None
    ) -> None:
        self.db.set_card_channel(interaction.guild_id, channel.id if channel else None)
        if channel:
            await interaction.response.send_message(
                f"✅ Karten-Drops werden jetzt in {channel.mention} angezeigt.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "✅ Karten-Drops werden wieder per DM verschickt.", ephemeral=True
            )

    @gamereward.command(name="addcard", description="Legt eine Karte für ein Spiel an.")
    @app_commands.describe(
        spiel="Zu welchem Spiel gehört die Karte?",
        name="Kartenname",
        seltenheit="Seltenheit der Karte",
        bild_url="Bild-URL der Karte (Pflicht, http/https)",
    )
    @app_commands.autocomplete(spiel=_game_autocomplete)
    @app_commands.choices(
        seltenheit=[app_commands.Choice(name=RARITIES[r]["label"], value=r) for r in RARITIES]
    )
    async def addcard(
        self,
        interaction: discord.Interaction,
        spiel: str,
        name: str,
        seltenheit: app_commands.Choice[str],
        bild_url: str,
    ) -> None:
        card_id = _slug(spiel, name)
        if card_id is None:
            await interaction.response.send_message(
                "⚠️ Ungültiger Name (mindestens ein Buchstabe/Ziffer nötig).", ephemeral=True
            )
            return
        if not bild_url.startswith(("http://", "https://")):
            await interaction.response.send_message(
                "⚠️ Die Bild-URL muss mit http(s):// beginnen.", ephemeral=True
            )
            return
        self.db.add_custom_card(interaction.guild_id, card_id, name, seltenheit.value, bild_url, spiel)
        await interaction.response.send_message(
            content=f"✅ Karte für **{spiel}** angelegt:",
            embed=self._embed_for(name, seltenheit.value, bild_url),
            ephemeral=True,
        )

    @gamereward.command(name="removecard", description="Entfernt eine eigene Karte.")
    @app_commands.describe(karte="Welche eigene Karte entfernen?")
    @app_commands.autocomplete(karte=_custom_card_autocomplete)
    async def removecard(self, interaction: discord.Interaction, karte: str) -> None:
        if self.db.remove_custom_card(interaction.guild_id, karte):
            await interaction.response.send_message("🗑️ Eigene Karte entfernt.", ephemeral=True)
        else:
            await interaction.response.send_message(
                "⚠️ Diese eigene Karte gibt es nicht (Standard-Karten lassen sich nicht entfernen).",
                ephemeral=True,
            )

    @gamereward.command(name="listcards", description="Zeigt die Karten eines Spiels.")
    @app_commands.describe(spiel="Welches Spiel?")
    @app_commands.autocomplete(spiel=_game_autocomplete)
    async def listcards(self, interaction: discord.Interaction, spiel: str) -> None:
        cards = self.db.list_custom_cards_for_game(interaction.guild_id, spiel)
        if not cards:
            await interaction.response.send_message(
                f"**{spiel}** hat noch keine eigenen Karten — es droppen die Standard-Karten. "
                f"Anlegen mit `/gamereward addcard spiel:{spiel} …`.",
                ephemeral=True,
            )
            return
        by_rar: dict[str, list[str]] = {}
        for _cid, name, rarity, _url in cards:
            by_rar.setdefault(rarity, []).append(name)
        lines = [
            f"{RARITIES[r]['emoji']} **{RARITIES[r]['label']}**: " + ", ".join(by_rar[r])
            for r in RARITY_ORDER if r in by_rar
        ]
        embed = discord.Embed(
            title=f"🎴 Karten von {spiel}", description="\n".join(lines), color=0x5865F2
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GameCardsCog(bot))

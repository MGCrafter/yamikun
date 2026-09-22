"""Spiel-Rewards: Booster-Packs fürs Spielen konfigurierter Spiele.

- Rewards sind PRO SPIEL: spielt jemand Spiel X, gibt es Spiel-Booster für X.
- Pro 30 Min Spielzeit gibt es 1 Spiel-Booster-Pack, max. 12/Tag (je Spiel einstellbar).
- Der Pack landet im Inventar und wird vom User selbst mit `/booster opengame`
  geöffnet → zieht dann eine Karte aus dem (eigenen) Kartenpool des Spiels.
- Hat ein Spiel keine Karten, gibt es keine Packs (der Pack wäre leer).
- Jede Karte hat eine eigene Bild-URL (Pflicht beim Anlegen).
- Das Booster-Emote ist pro Spiel im Webpanel einstellbar.
- Erkennung via Presence (braucht das privilegierte Presence Intent).
"""

from __future__ import annotations

import datetime
import logging
import re
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

logger = logging.getLogger("oaken-tower-bot")

DEFAULT_INTERVAL_MIN = 30  # Minuten pro Karte (Standard für neue Spiele)
DEFAULT_DAILY_CAP = 12     # max. Karten/Tag (Standard für neue Spiele)
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

COIN_EMOJI_NAME = "YamiToken"
COIN_FALLBACK = "🪙"


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", ".")


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
        initiator_card: str | None,
        catalog: dict[str, tuple[str, str, str | None]],
        partner_options: list[discord.SelectOption],
        coins: int = 0,
    ) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.initiator = initiator
        self.partner = partner
        self.initiator_card = initiator_card
        self.partner_card: str | None = None
        self.catalog = catalog
        self.coins = coins  # Coins, die der Initiator zusätzlich an den Partner zahlt
        self.confirmed: set[int] = set()
        self.message: discord.Message | None = None
        self.finished = False
        self.add_item(TradeOfferSelect(partner_options))

    def _label(self, cid: str | None, *, none_text: str = "_nichts_") -> str:
        if cid is None:
            return none_text
        name, rarity, _ = self.catalog.get(cid, (cid, "common", None))
        return f"{RARITIES[rarity]['emoji']} **{name}**"

    def _initiator_offer(self) -> str:
        coin = self.cog._coin(self.initiator.guild)
        parts = []
        if self.initiator_card is not None:
            parts.append(self._label(self.initiator_card))
        if self.coins > 0:
            parts.append(f"**{_fmt(self.coins)}** {coin}")
        return " + ".join(parts) if parts else "_nichts_"

    def embed(self) -> discord.Embed:
        def mark(uid: int) -> str:
            return "✅" if uid in self.confirmed else "⬜"

        is_buy = self.initiator_card is None and self.coins > 0
        embed = discord.Embed(
            title="🛒 Kartenkauf" if is_buy else "🔄 Kartentausch",
            description=(
                f"{mark(self.initiator.id)} {self.initiator.mention} bietet: {self._initiator_offer()}\n"
                f"{mark(self.partner.id)} {self.partner.mention} bietet: "
                f"{self._label(self.partner_card, none_text='_noch nicht gewählt_')}\n\n"
                "Beide müssen **Annehmen** klicken. Eine neue Kartenwahl setzt die Bestätigungen zurück."
            ),
            color=0x7C3AED,
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
            ok = self.cog.db.trade_with_coins(
                interaction.guild_id, self.initiator.id, self.initiator_card,
                self.partner.id, self.partner_card, self.coins,
            )
            await self._finish()
            if ok:
                coin = self.cog._coin(self.initiator.guild)
                partner_gets = self._initiator_offer()
                initiator_gets = self._label(self.partner_card)
                done = discord.Embed(
                    title="✅ Handel abgeschlossen!",
                    description=(
                        f"{self.partner.mention} erhält {partner_gets}\n"
                        f"{self.initiator.mention} erhält {initiator_gets}"
                    ),
                    color=0x2ECC71,
                )
                await interaction.response.edit_message(content=None, embed=done, view=self)
            else:
                await interaction.response.edit_message(
                    content="⚠️ Handel fehlgeschlagen — jemandem fehlen Karte oder Coins.",
                    embed=None, view=self,
                )
            return
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Ablehnen", emoji="❌", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._finish()
        await interaction.response.edit_message(
            content=f"❌ Handel von {interaction.user.mention} abgebrochen.", embed=None, view=self
        )


class ConfirmDiscardView(discord.ui.View):
    """Sicherheitsabfrage vor dem Entfernen von Karten aus dem eigenen Inventar."""

    def __init__(
        self,
        cog: "GameCardsCog",
        *,
        user_id: int,
        card_id: str,
        card_name: str,
        amount: int | None,
        owned: int,
    ) -> None:
        super().__init__(timeout=60)
        self.cog = cog
        self.user_id = user_id
        self.card_id = card_id
        self.card_name = card_name
        self.amount = amount  # None = alle Exemplare
        self.owned = owned
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Das ist nicht deine Aktion 🙂", ephemeral=True)
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

    @discord.ui.button(label="Entfernen", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        remaining = self.cog.db.remove_card(
            interaction.guild_id, self.user_id, self.card_id, self.amount
        )
        removed = self.owned - remaining
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        rest = f" Verbleibend: **{remaining}×**." if remaining else ""
        await interaction.response.edit_message(
            content=f"🗑️ **{removed}× {self.card_name}** aus deiner Sammlung entfernt.{rest}",
            embed=None, view=self,
        )

    @discord.ui.button(label="Abbrechen", emoji="↩️", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(content="↩️ Abgebrochen.", embed=None, view=self)


class RewardServerSelect(discord.ui.Select):
    """Auswahl, auf welchem Server der User Karten-Drop-Meldungen bekommt."""

    def __init__(self, db, user_id: int, guilds: list[discord.Guild], current: int | None) -> None:
        self.db = db
        self.user_id = user_id
        options = [
            discord.SelectOption(
                label="Automatisch (erster Server)",
                value="auto",
                description="Der Bot wählt selbst einen passenden Server.",
                emoji="🎲",
                default=current is None,
            )
        ]
        for g in guilds[:24]:  # max. 25 Optionen inkl. "Automatisch"
            options.append(
                discord.SelectOption(
                    label=g.name[:100],
                    value=str(g.id),
                    emoji="📨",
                    default=g.id == current,
                )
            )
        super().__init__(placeholder="Server für Drop-Meldungen wählen…", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Das ist nicht deine Aktion 🙂", ephemeral=True)
            return
        choice = self.values[0]
        if choice == "auto":
            self.db.set_reward_notify_guild(self.user_id, None)
            msg = "✅ Drop-Meldungen kommen jetzt **automatisch** (erster passender Server)."
        else:
            gid = int(choice)
            self.db.set_reward_notify_guild(self.user_id, gid)
            guild = interaction.client.get_guild(gid)
            name = guild.name if guild else "diesem Server"
            msg = (
                f"✅ Drop-Meldungen bekommst du jetzt auf **{name}** — "
                "sofern dort das gespielte Spiel als Reward-Spiel eingetragen ist."
            )
        self.disabled = True
        await interaction.response.edit_message(content=msg, embed=None, view=self.view)


class RewardServerView(discord.ui.View):
    def __init__(self, db, user_id: int, guilds: list[discord.Guild], current: int | None) -> None:
        super().__init__(timeout=120)
        self.add_item(RewardServerSelect(db, user_id, guilds, current))


class GameCardsCog(commands.Cog):
    """Sammelkarten als Spiel-Reward + /cards, /card, /gamereward."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]
        # Global pro User: ein Spiel wird nur EINMAL gezählt, egal auf wie vielen Servern.
        # user_id -> (start, game, config_guild_id)  (config-Guild liefert Intervall/Cap/Channel)
        self.active: dict[int, tuple[float, str, int]] = {}

    async def cog_load(self) -> None:
        self.settle_loop.start()

    def cog_unload(self) -> None:
        self.settle_loop.cancel()

    def _coin(self, guild: discord.Guild | None) -> str:
        if guild is not None:
            emoji = discord.utils.get(guild.emojis, name=COIN_EMOJI_NAME)
            if emoji is not None:
                return str(emoji)
        return COIN_FALLBACK

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

    def _tracked_game(self, member: discord.Member) -> tuple[str, discord.Guild] | None:
        """Spielt der User ein Spiel, das auf IRGENDEINEM gemeinsamen Server als
        Reward-Spiel eingetragen ist? Gibt (spiel_lower, config_guild) zurück.

        Dadurch wird ein Spiel nur einmal gezählt, auch wenn der User auf mehreren
        Servern ist — die erste Guild, die das Spiel trackt, liefert die Konfiguration."""
        playing = [
            act.name.lower()
            for act in member.activities
            if act.type == discord.ActivityType.playing and act.name
        ]
        if not playing:
            return None
        pref = self.db.get_reward_notify_guild(member.id)  # Wunsch-Server (oder None)
        fallback: tuple[str, discord.Guild] | None = None
        for guild in self.bot.guilds:
            if guild.get_member(member.id) is None:
                continue
            match = next(
                (resolved for activity in playing if (resolved := self.db.match_reward_game(guild.id, activity))),
                None,
            )
            if match is None:
                continue
            if guild.id == pref:  # Wunsch-Server trackt das Spiel → gewinnt
                return match, guild
            if fallback is None:
                fallback = (match, guild)
        return fallback

    def _find_member(self, user_id: int) -> discord.Member | None:
        for guild in self.bot.guilds:
            member = guild.get_member(user_id)
            if member is not None:
                return member
        return None

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member) -> None:
        if after.bot:
            return
        info = self._tracked_game(after)  # (game, config_guild) oder None
        now = time.time()
        uid = after.id
        if uid in self.active:
            start, game, gid = self.active[uid]
            new_game = info[0] if info else None
            if new_game != game:  # gestoppt oder Spiel gewechselt
                del self.active[uid]
                guild = self.bot.get_guild(gid) or after.guild
                await self._credit(guild, after, now - start, game)
                if info is not None:
                    self.active[uid] = (now, info[0], info[1].id)
        elif info is not None:
            self.active[uid] = (now, info[0], info[1].id)

    @tasks.loop(minutes=SETTLE_MINUTES)
    async def settle_loop(self) -> None:
        now = time.time()
        for uid in list(self.active):
            start, game, gid = self.active.get(uid, (now, "", 0))
            member = self._find_member(uid)
            self.active.pop(uid, None)
            if member is None:
                continue
            guild = self.bot.get_guild(gid) or member.guild
            await self._credit(guild, member, now - start, game)
            info = self._tracked_game(member)
            if info is not None:
                self.active[uid] = (now, info[0], info[1].id)

    @settle_loop.before_loop
    async def _before_settle(self) -> None:
        await self.bot.wait_until_ready()

    async def _credit(self, guild: discord.Guild, member: discord.Member, seconds: float, game: str | None) -> None:
        secs = int(seconds)
        if secs <= 0:
            return
        catalog = build_game_catalog(self.db, guild.id, game)
        if not catalog:
            return  # keine Karten für dieses Spiel angelegt → Pack wäre leer, nichts vergeben
        interval_min, daily_cap = self.db.get_reward_game(guild.id, game)
        interval = max(1, interval_min) * 60  # Sekunden pro Booster-Pack
        acc, day, granted_today = self.db.get_playtime(guild.id, member.id, game)
        today = _today()
        if day != today:
            day, granted_today = today, 0
        acc += secs
        granted = 0  # in dieser Runde erspielte Packs
        while acc >= interval and granted_today < daily_cap:
            acc -= interval
            granted_today += 1
            granted += 1
        if granted_today >= daily_cap:
            acc = min(acc, interval - 1)
        self.db.set_playtime(guild.id, member.id, acc, day, granted_today, game)
        if granted <= 0:
            return
        # Statt direkter Karte gibt es jetzt Spiel-Booster-Packs, die der User selbst öffnet.
        from cogs.booster import resolve_booster_emoji

        from cogs.uiembeds import reward_embed, LIME

        pack_type = "game:" + (game or "").strip().lower()
        total = self.db.add_packs(guild.id, member.id, pack_type, granted)
        emote = resolve_booster_emoji(guild, self.db, game or "")
        embed = reward_embed(
            badge="⚡  REWARD FREIGESCHALTET",
            title=f"{emote}  +{granted} Spiel-Booster",
            member=member,
            description=f"**{member.display_name}** hat durchs Spielen einen Drop erhalten.",
            game=game,
            total=total,
            total_label="Booster im Inventar",
            hint=f"Öffnen mit `/booster opengame spiel:{game}`",
            color=LIME,
        )
        # Ziel: konfigurierter Karten-Channel (öffentlich), sonst DM an den User.
        channel = None
        chan_id = self.db.get_card_channel(guild.id)
        if chan_id:
            ch = guild.get_channel(chan_id)
            if isinstance(ch, discord.abc.Messageable):
                channel = ch
        if channel is not None:
            try:
                await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                return
            except discord.Forbidden:
                pass  # fällt auf DM zurück
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
                f"{target.display_name} hat noch keine Karten. Spiel ein konfiguriertes Spiel, "
                f"erspiel dir Booster und öffne sie mit `/booster opengame`! 🎴",
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

    @app_commands.command(name="discard", description="Entfernt Karten aus deiner Sammlung.")
    @app_commands.guild_only()
    @app_commands.describe(
        karte="Welche Karte entfernen?",
        anzahl="Wie viele Exemplare? (Standard: alle)",
    )
    @app_commands.autocomplete(karte=_owned_card_autocomplete)
    async def discard(
        self,
        interaction: discord.Interaction,
        karte: str,
        anzahl: app_commands.Range[int, 1, 100000] | None = None,
    ) -> None:
        catalog = build_full_catalog(self.db, interaction.guild_id)
        card_id = karte if karte in catalog else next(
            (cid for cid, (name, _, _) in catalog.items() if name.lower() == karte.lower()), None
        )
        owned = self.db.get_collection(interaction.guild_id, interaction.user.id).get(card_id, 0) if card_id else 0
        if card_id is None or owned < 1:
            await interaction.response.send_message(
                "⚠️ Diese Karte besitzt du nicht.", ephemeral=True
            )
            return
        name, rarity, url = catalog[card_id]
        amount = owned if anzahl is None else min(anzahl, owned)
        view = ConfirmDiscardView(
            self, user_id=interaction.user.id, card_id=card_id, card_name=name,
            amount=None if anzahl is None else amount, owned=owned,
        )
        await interaction.response.send_message(
            content=f"⚠️ Wirklich **{amount}× {name}** aus deiner Sammlung entfernen? "
                    "Das kann nicht rückgängig gemacht werden.",
            embed=self._embed_for(name, rarity, url, owned=owned),
            view=view, ephemeral=True,
        )
        view.message = await interaction.original_response()

    @app_commands.command(
        name="trade",
        description="Tausche oder kaufe eine Karte — optional mit Tokens drauf.",
    )
    @app_commands.guild_only()
    @app_commands.describe(
        user="Mit wem möchtest du handeln?",
        karte="Optional: welche deiner Karten bietest du an?",
        tokens="Optional: wie viele Coins legst du drauf / bietest du für den Kauf?",
    )
    @app_commands.autocomplete(karte=_owned_card_autocomplete)
    async def trade(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        karte: str | None = None,
        tokens: app_commands.Range[int, 0, 1_000_000_000] = 0,
    ) -> None:
        if user.bot or user.id == interaction.user.id:
            await interaction.response.send_message(
                "⚠️ Du kannst nur mit anderen Mitgliedern handeln.", ephemeral=True
            )
            return
        if karte is None and tokens <= 0:
            await interaction.response.send_message(
                "⚠️ Biete eine **Karte**, **Tokens** oder beides an.", ephemeral=True
            )
            return
        catalog = build_full_catalog(self.db, interaction.guild_id)
        card_id: str | None = None
        if karte is not None:
            card_id = karte if karte in catalog else next(
                (cid for cid, (name, _, _) in catalog.items() if name.lower() == karte.lower()), None
            )
            if card_id is None or self.db.get_collection(interaction.guild_id, interaction.user.id).get(card_id, 0) < 1:
                await interaction.response.send_message(
                    "⚠️ Diese Karte besitzt du nicht.", ephemeral=True
                )
                return
        coin = self._coin(interaction.guild)
        if tokens > 0:
            balance = int(self.db.get_user(interaction.guild_id, interaction.user.id)["coins"])
            if balance < tokens:
                await interaction.response.send_message(
                    f"⚠️ Du hast nur **{_fmt(balance)}** {coin}, willst aber **{_fmt(tokens)}** anbieten.",
                    ephemeral=True,
                )
                return
        partner_collection = self.db.get_collection(interaction.guild_id, user.id)
        if not partner_collection:
            await interaction.response.send_message(
                f"⚠️ {user.display_name} hat noch keine Karten zum Handeln.", ephemeral=True
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
            initiator_card=card_id, catalog=catalog, partner_options=options, coins=tokens,
        )
        verb = "kaufen" if card_id is None else "handeln"
        await interaction.response.send_message(
            content=f"🔄 {user.mention}, {interaction.user.mention} möchte mit dir {verb}!",
            embed=view.embed(), view=view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )
        view.message = await interaction.original_response()

    @app_commands.command(
        name="rewardserver",
        description="Wähle, auf welchem Server du deine Karten-Drop-Meldungen bekommst.",
    )
    async def rewardserver(self, interaction: discord.Interaction) -> None:
        uid = interaction.user.id
        guilds = [
            g for g in self.bot.guilds
            if g.get_member(uid) is not None and self.db.list_reward_games(g.id)
        ]
        if not guilds:
            await interaction.response.send_message(
                "Auf keinem deiner gemeinsamen Server sind Reward-Spiele eingerichtet — "
                "es gibt also nichts auszuwählen.",
                ephemeral=True,
            )
            return
        current = self.db.get_reward_notify_guild(uid)
        embed = discord.Embed(
            title="📨 Benachrichtigungs-Server",
            description=(
                "Wenn du ein Spiel spielst, das auf mehreren deiner Server als Reward-Spiel "
                "eingetragen ist, bekommst du den Drop nur **einmal**. Hier wählst du, welcher "
                "Server die Meldung zeigt (bzw. dir per DM schickt).\n\n"
                "Trackt dein Wunsch-Server das gespielte Spiel gerade nicht, fällt der Bot "
                "automatisch auf einen passenden Server zurück."
            ),
            color=0x7C3AED,
        )
        view = RewardServerView(self.db, uid, guilds, current)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # --- Mod-Konfiguration /gamereward ----------------------------------------

    gamereward = app_commands.Group(
        name="gamereward",
        description="Karten-Rewards, Spiele & Karten verwalten (nur Mods).",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @gamereward.command(
        name="addgame",
        description="Fügt ein Spiel hinzu oder ändert dessen Intervall/Tageslimit.",
    )
    @app_commands.describe(
        spiel="Exakter Spielname (wie in Discord angezeigt), z.B. League of Legends",
        intervall="Minuten Spielzeit pro Booster-Pack (Standard 30)",
        tageslimit="Maximale Booster pro Tag (Standard 12)",
    )
    async def addgame(
        self,
        interaction: discord.Interaction,
        spiel: str,
        intervall: app_commands.Range[int, 1, 1440] = DEFAULT_INTERVAL_MIN,
        tageslimit: app_commands.Range[int, 1, 100] = DEFAULT_DAILY_CAP,
    ) -> None:
        self.db.add_reward_game(interaction.guild_id, spiel, intervall, tageslimit)
        note = "" if self.bot.intents.presences else (
            "\n⚠️ **Presence Intent ist aus** — der Bot kann noch nicht erkennen, wer spielt."
        )
        await interaction.response.send_message(
            f"✅ **{spiel}** eingetragen: 1 Booster pro **{intervall} Min**, max. **{tageslimit}/Tag**.\n"
            f"Lege jetzt Karten an: `/gamereward addcard spiel:{spiel} …` "
            f"(ohne Karten wäre der Booster leer, daher gibt es ohne Karten keine Drops).\n"
            f"Booster-Emote pro Spiel stellst du im Webpanel ein.{note}",
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
        games = self.db.list_reward_games_full(interaction.guild_id)
        aliases = self.db.list_reward_game_aliases(interaction.guild_id)
        aliases_by_game: dict[str, list[str]] = {}
        for alias, game in aliases:
            aliases_by_game.setdefault(game, []).append(alias)
        status = "🟢 aktiv" if self.bot.intents.presences else "🔴 Presence Intent aus"

        def _line(g: str, iv: int, cap: int, emoji: str | None) -> str:
            from cogs.booster import resolve_booster_emoji
            em = resolve_booster_emoji(interaction.guild, self.db, g)
            alias_txt = ""
            if aliases_by_game.get(g):
                alias_txt = "\n  ↳ Alias: " + ", ".join(f"`{a}`" for a in aliases_by_game[g])
            return f"• {em} **{g}** — 1 Booster / {iv} Min · max. {cap}/Tag{alias_txt}"

        text = (
            "\n".join(_line(g, iv, cap, emoji) for g, iv, cap, emoji in games)
            if games else "_keine eingetragen_"
        )
        embed = discord.Embed(
            title="🎮 Booster-Belohnungs-Spiele",
            description=f"{text}\n\nTracking: {status}",
            color=0x7C3AED,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @gamereward.command(
        name="addalias",
        description="Fügt einem Reward-Spiel einen zweiten Discord-Aktivitätsnamen hinzu.",
    )
    @app_commands.describe(
        spiel="Das echte Reward-Spiel, dessen Karten/Booster vergeben werden sollen",
        alias="Zusätzlicher Discord-Name, z.B. Valorant Tracker",
    )
    @app_commands.autocomplete(spiel=_game_autocomplete)
    async def addalias(self, interaction: discord.Interaction, spiel: str, alias: str) -> None:
        spiel = spiel.strip()
        alias = alias.strip()
        if not spiel or not alias:
            await interaction.response.send_message("⚠️ Spiel und Alias dürfen nicht leer sein.", ephemeral=True)
            return
        if not self.db.is_reward_game(interaction.guild_id, spiel):
            await interaction.response.send_message(
                f"⚠️ **{spiel}** ist noch kein Reward-Spiel. Lege es zuerst mit `/gamereward addgame` an.",
                ephemeral=True,
            )
            return
        if spiel.lower() == alias.lower():
            await interaction.response.send_message(
                "⚠️ Der Alias ist identisch mit dem Spielnamen — dafür brauchst du keinen Alias.",
                ephemeral=True,
            )
            return
        self.db.add_reward_game_alias(interaction.guild_id, spiel, alias)
        await interaction.response.send_message(
            f"✅ **{alias}** zählt jetzt als **{spiel}**. Drops verwenden weiter die Karten und Booster von **{spiel}**.",
            ephemeral=True,
        )

    @gamereward.command(
        name="removealias",
        description="Entfernt einen zusätzlichen Discord-Aktivitätsnamen.",
    )
    @app_commands.describe(alias="Der zu entfernende Alias, z.B. Valorant Tracker")
    async def removealias(self, interaction: discord.Interaction, alias: str) -> None:
        alias = alias.strip()
        if self.db.remove_reward_game_alias(interaction.guild_id, alias):
            await interaction.response.send_message(f"🗑️ Alias **{alias}** entfernt.", ephemeral=True)
        else:
            await interaction.response.send_message(f"⚠️ Alias **{alias}** war nicht eingetragen.", ephemeral=True)

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

    @gamereward.command(
        name="givecard",
        description="Vergibt eine Karte direkt an ein Mitglied (z. B. für Giveaways).",
    )
    @app_commands.describe(
        user="Wer bekommt die Karte?",
        karte="Welche Karte vergeben?",
        anzahl="Wie viele Exemplare? (Standard 1)",
    )
    @app_commands.autocomplete(karte=_custom_card_autocomplete)
    async def givecard(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        karte: str,
        anzahl: app_commands.Range[int, 1, 100] = 1,
    ) -> None:
        if user.bot:
            await interaction.response.send_message(
                "⚠️ An Bots kannst du keine Karten vergeben.", ephemeral=True
            )
            return
        catalog = build_full_catalog(self.db, interaction.guild_id)
        # Karte per ID oder Name auflösen.
        card_id = karte if karte in catalog else next(
            (cid for cid, (name, _, _) in catalog.items() if name.lower() == karte.lower()), None
        )
        if card_id is None:
            await interaction.response.send_message("⚠️ Diese Karte gibt es nicht.", ephemeral=True)
            return
        new_count = self.db.add_card(interaction.guild_id, user.id, card_id, anzahl)
        name, rarity, url = catalog[card_id]
        amount_txt = "" if anzahl == 1 else f" ×{anzahl}"
        embed = self._embed_for(name, rarity, url, owned=new_count, prefix="🎁 Geschenk-Karte! ")
        await interaction.response.send_message(
            content=f"🎁 {user.mention} erhält **{name}**{amount_txt} von {interaction.user.mention}!",
            embed=embed,
            allowed_mentions=discord.AllowedMentions(users=True),
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
            title=f"🎴 Karten von {spiel}", description="\n".join(lines), color=0x7C3AED
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GameCardsCog(bot))

"""Profilseite (OwO-Style) und Bio-Verwaltung.

Zeigt Avatar, Level + XP-Fortschritt, Coins, Leaderboard-Platz, Coinflip-Statistik
und eine frei setzbare Bio.
"""

from __future__ import annotations

from copy import deepcopy

import discord
from discord import app_commands
from discord.ext import commands

from cogs.gamecards import RARITIES
from cogs.leveling import level_from_total, xp_needed

COIN_EMOJI_NAME = "YamiToken"
COIN_FALLBACK = "🪙"
BIO_MAX_LEN = 200
BAR_LENGTH = 14


def _game_catalog(db, guild_id: int) -> dict[str, tuple[str, str, str | None, str]]:
    """Erspielte Karten mit Spiel als card_id -> (name, rarity, url, game)."""
    cat: dict[str, tuple[str, str, str | None, str]] = {}
    for cid, name, rarity, url, game in db.list_custom_cards(guild_id):
        if game:  # nur Karten, die einem Spiel zugeordnet sind
            cat[cid] = (name, rarity, url, game)
    return cat


def _owned_by_game(db, guild_id: int, user_id: int) -> dict[str, list[tuple[str, str, str]]]:
    """Besessene Spielkarten gruppiert: {spiel: [(card_id, name, rarity), …]}, alphabetisch."""
    owned = db.get_collection(guild_id, user_id)
    cat = _game_catalog(db, guild_id)
    by_game: dict[str, list[tuple[str, str, str]]] = {}
    for cid, count in owned.items():
        if count <= 0 or cid not in cat:
            continue
        name, rarity, _url, game = cat[cid]
        by_game.setdefault(game, []).append((cid, name, rarity))
    for cards in by_game.values():
        cards.sort(key=lambda c: c[1].lower())
    return dict(sorted(by_game.items(), key=lambda kv: kv[0].lower()))


def _build_favs(db, guild_id: int, user_id: int) -> list[tuple[str, str, str, str, str | None]]:
    """Lieblingskarten als [(spiel, card_id, name, rarity, url)] — nur noch existierende."""
    cat = _game_catalog(db, guild_id)
    out: list[tuple[str, str, str, str, str | None]] = []
    for game, cid in db.get_fav_game_cards(guild_id, user_id).items():
        if cid in cat:
            name, rarity, url, _g = cat[cid]
            out.append((game, cid, name, rarity, url))
    return out


async def _fav_card_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    db = interaction.client.db  # type: ignore[attr-defined]
    by_game = _owned_by_game(db, interaction.guild_id, interaction.user.id)
    cur = current.lower()
    out: list[app_commands.Choice[str]] = []
    for game, cards in by_game.items():
        for cid, name, rarity in cards:
            if cur in name.lower() or cur in game.lower():
                emoji = RARITIES.get(rarity, RARITIES["common"])["emoji"]
                out.append(app_commands.Choice(name=f"{emoji} {name} · {game}"[:100], value=cid))
                if len(out) >= 25:
                    return out
    return out


class FavGameCardSelect(discord.ui.Select):
    """Karte eines bestimmten Spiels als Lieblingskarte wählen (oder entfernen)."""

    def __init__(self, db, owner_id: int, game: str, options: list[discord.SelectOption]) -> None:
        super().__init__(
            placeholder=f"Lieblingskarte für {game}…"[:150],
            min_values=1, max_values=1, options=options,
        )
        self.db = db
        self.owner_id = owner_id
        self.game = game

    async def callback(self, interaction: discord.Interaction) -> None:
        value = self.values[0]
        if value == "__none__":
            self.db.set_fav_game_card(interaction.guild_id, self.owner_id, self.game, None)
            await interaction.response.edit_message(
                content=f"⭐ Lieblingskarte für **{self.game}** entfernt.", view=None
            )
            return
        self.db.set_fav_game_card(interaction.guild_id, self.owner_id, self.game, value)
        await interaction.response.edit_message(
            content=f"⭐ Lieblingskarte für **{self.game}** gesetzt! Im `/profile` blätterst du mit ◀/▶ durch.",
            view=None,
        )


class FavGameSelect(discord.ui.Select):
    """Erst das Spiel wählen — danach erscheint die Kartenauswahl."""

    def __init__(self, db, owner_id: int, by_game: dict[str, list[tuple[str, str, str]]]) -> None:
        self.db = db
        self.owner_id = owner_id
        self.by_game = by_game
        options = [discord.SelectOption(label=g[:100], value=g, emoji="🎮") for g in list(by_game)[:25]]
        super().__init__(placeholder="Für welches Spiel?", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        game = self.values[0]
        cards = self.by_game.get(game, [])
        options = [discord.SelectOption(label="Keine / entfernen", value="__none__", emoji="🚫")]
        for cid, name, rarity in cards[:24]:  # 24 + Entfernen = max. 25
            options.append(discord.SelectOption(
                label=name[:100], value=cid, emoji=RARITIES.get(rarity, RARITIES["common"])["emoji"],
            ))
        view = discord.ui.View(timeout=120)
        view.add_item(FavGameCardSelect(self.db, self.owner_id, game, options))
        note = "" if len(cards) <= 24 else "\n_(Nur die ersten 24 — nutze `/setfavcard` für alle.)_"
        await interaction.response.edit_message(
            content=f"Wähle deine Lieblingskarte für **{game}**:{note}", view=view
        )


class ProfileView(discord.ui.View):
    """Profil mit Lieblingskarten-Carousel (◀/▶) und ⭐-Button (nur eigenes Profil)."""

    def __init__(self, db, owner_id: int, base_embed: discord.Embed,
                 favs: list[tuple[str, str, str, str, str | None]], is_self: bool) -> None:
        super().__init__(timeout=180)
        self.db = db
        self.owner_id = owner_id
        self.base_embed = base_embed
        self.favs = favs
        self.index = 0
        self.message: discord.Message | None = None
        if len(favs) <= 1:  # nichts zu blättern → Pfeile weg
            self.remove_item(self.prev)
            self.remove_item(self.next)
        if not is_self:  # fremde Profile: kein Setzen-Button
            self.remove_item(self.pick)

    def render(self) -> discord.Embed:
        # discord.Embed.copy() is shallow for internal field/image structures in
        # some discord.py versions.  Rendering the carousel repeatedly would then
        # append the favourite-card field back onto ``self.base_embed`` and make
        # the profile text grow with every ◀/▶ click.
        embed = discord.Embed.from_dict(deepcopy(self.base_embed.to_dict()))
        if self.favs:
            game, _cid, name, rarity, url = self.favs[self.index]
            r = RARITIES.get(rarity, RARITIES["common"])
            pos = f" ({self.index + 1}/{len(self.favs)})" if len(self.favs) > 1 else ""
            embed.add_field(name=f"⭐ Lieblingskarte · {game}{pos}", value=f"{r['emoji']} {name}", inline=False)
            if url:
                embed.set_image(url=url)
        return embed

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(emoji="◀", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.index = (self.index - 1) % len(self.favs)
        await interaction.response.edit_message(embed=self.render(), view=self)

    @discord.ui.button(emoji="▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.index = (self.index + 1) % len(self.favs)
        await interaction.response.edit_message(embed=self.render(), view=self)

    @discord.ui.button(label="Lieblingskarte", emoji="⭐", style=discord.ButtonStyle.secondary)
    async def pick(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Das ist nicht dein Profil 🙂", ephemeral=True)
            return
        by_game = _owned_by_game(self.db, interaction.guild_id, self.owner_id)
        if not by_game:
            await interaction.response.send_message(
                "Du besitzt noch keine Spielkarten — erspiel oder kauf welche! 🎴", ephemeral=True
            )
            return
        view = discord.ui.View(timeout=120)
        view.add_item(FavGameSelect(self.db, self.owner_id, by_game))
        await interaction.response.send_message(
            "Für welches Spiel willst du eine Lieblingskarte wählen?", view=view, ephemeral=True
        )


def _fmt(n: int) -> str:
    """Zahl mit Tausenderpunkten."""
    return f"{n:,}".replace(",", ".")


def _bar(fraction: float, length: int = BAR_LENGTH) -> str:
    """Text-Fortschrittsbalken aus █ und ░."""
    fraction = max(0.0, min(1.0, fraction))
    filled = round(fraction * length)
    return "█" * filled + "░" * (length - filled)


class ProfileCog(commands.Cog):
    """/profile und /setbio."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]

    def _coin(self, guild: discord.Guild | None) -> str:
        if guild is not None:
            emoji = discord.utils.get(guild.emojis, name=COIN_EMOJI_NAME)
            if emoji is not None:
                return str(emoji)
        return COIN_FALLBACK

    @app_commands.command(name="profile", description="Zeigt das Profil eines Users.")
    @app_commands.guild_only()
    @app_commands.describe(user="Wessen Profil? (Standard: du selbst)")
    async def profile(
        self, interaction: discord.Interaction, user: discord.Member | None = None
    ) -> None:
        target = user or interaction.user
        guild = interaction.guild
        coin = self._coin(guild)

        row = self.db.get_user(guild.id, target.id)
        total_xp = int(row["xp"])
        coins = int(row["coins"])
        level, into_level = level_from_total(total_xp)
        need = xp_needed(level)
        pos, total = self.db.rank_position(guild.id, target.id)
        bio = self.db.get_bio(guild.id, target.id)
        equipped_title = self.db.get_title(guild.id, target.id)
        spouses = self.db.list_marriages(guild.id, target.id)

        custom = self.db.get_profile_color(guild.id, target.id)
        if custom is not None:
            color = discord.Color(custom)
        elif target.color.value:
            color = target.color
        else:
            color = discord.Color(0x7C3AED)
        desc = bio or "*Keine Bio gesetzt — `/setbio` zum Setzen.*"
        if equipped_title:
            desc = f"🏷️ **{equipped_title}**\n{desc}"
        embed = discord.Embed(
            title=f"Profil von {target.display_name}",
            color=color,
            description=desc,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Level", value=f"**{level}**", inline=True)
        embed.add_field(name="Rang", value=f"#{pos} / {total}", inline=True)
        embed.add_field(name="Coins", value=f"{_fmt(coins)} {coin}", inline=True)

        frac = into_level / need if need else 0
        embed.add_field(
            name="XP-Fortschritt",
            value=f"`{_bar(frac)}`\n{_fmt(into_level)} / {_fmt(need)} XP "
            f"(gesamt {_fmt(total_xp)})",
            inline=False,
        )

        def stat_line(g: int, w: int, l: int) -> str:
            if g == 0:
                return "Noch nicht gespielt."
            return f"{_fmt(g)} Spiele\n{w}W / {l}L · {w / g * 100:.0f}%"

        for game_title, key in (("🪙 Coinflip", "coinflip"), ("🃏 Blackjack", "blackjack"), ("🎰 Slots", "slots")):
            g, w, l = self.db.get_game_stats(guild.id, target.id, key)
            embed.add_field(name=game_title, value=stat_line(g, w, l), inline=True)

        if spouses:
            names = []
            for other_id, _ in spouses[:5]:
                member = interaction.guild.get_member(other_id)
                names.append(member.mention if member else f"<@{other_id}>")
            suffix = f" +{len(spouses) - 5} weitere" if len(spouses) > 5 else ""
            embed.add_field(name="💍 Verheiratet mit", value=", ".join(names) + suffix, inline=False)

        # Lieblingskarten (eine je Spiel) als Showcase — durchblätterbar via ◀/▶.
        favs = _build_favs(self.db, guild.id, target.id)
        is_self = target.id == interaction.user.id
        view = ProfileView(self.db, interaction.user.id, embed, favs, is_self)
        rendered = view.render()
        if not favs and not is_self:  # nichts zu zeigen/blättern auf fremdem Profil
            await interaction.response.send_message(embed=rendered)
            return
        await interaction.response.send_message(embed=rendered, view=view)
        view.message = await interaction.original_response()

    @app_commands.command(
        name="setfavcard",
        description="Setzt deine Lieblingskarte für ein Spiel (Spiel wird aus der Karte erkannt).",
    )
    @app_commands.guild_only()
    @app_commands.describe(karte="Welche deiner erspielten Karten? (eine Lieblingskarte je Spiel)")
    @app_commands.autocomplete(karte=_fav_card_autocomplete)
    async def setfavcard(self, interaction: discord.Interaction, karte: str) -> None:
        cat = _game_catalog(self.db, interaction.guild_id)
        owned = self.db.get_collection(interaction.guild_id, interaction.user.id)
        # Treffer per ID oder per Name — nur besessene Spielkarten (Yami zählt hier nicht).
        card_id = karte if (karte in owned and karte in cat) else next(
            (cid for cid in owned if cid in cat and cat[cid][0].lower() == karte.lower()), None
        )
        if card_id is None:
            await interaction.response.send_message(
                "⚠️ Diese Spielkarte besitzt du nicht (Yami-Karten gehen hier nicht).", ephemeral=True
            )
            return
        name, rarity, url, game = cat[card_id]
        self.db.set_fav_game_card(interaction.guild_id, interaction.user.id, game, card_id)
        r = RARITIES.get(rarity, RARITIES["common"])
        embed = discord.Embed(
            title=f"⭐ Lieblingskarte für {game} gesetzt",
            description=f"{r['emoji']} **{name}**",
            color=r["color"],
        )
        if url:
            embed.set_image(url=url)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="setbio", description="Setzt deine Profil-Bio.")
    @app_commands.guild_only()
    @app_commands.describe(text=f"Dein Bio-Text (max. {BIO_MAX_LEN} Zeichen, leer = löschen)")
    async def setbio(self, interaction: discord.Interaction, text: str) -> None:
        text = text.strip()
        if len(text) > BIO_MAX_LEN:
            await interaction.response.send_message(
                f"⚠️ Die Bio darf höchstens **{BIO_MAX_LEN}** Zeichen lang sein "
                f"(deine: {len(text)}).",
                ephemeral=True,
            )
            return
        self.db.set_bio(interaction.guild_id, interaction.user.id, text or None)
        if text:
            await interaction.response.send_message("✅ Bio gespeichert.", ephemeral=True)
        else:
            await interaction.response.send_message("✅ Bio gelöscht.", ephemeral=True)

    @app_commands.command(name="setcolor", description="Setzt deine Profil-Akzentfarbe (Hex, z.B. #FF8800).")
    @app_commands.guild_only()
    @app_commands.describe(farbe="Hex-Farbe wie #FF8800 – oder 'reset' für Standard")
    async def setcolor(self, interaction: discord.Interaction, farbe: str) -> None:
        raw = farbe.strip().lower()
        if raw in ("reset", "clear", "standard"):
            self.db.set_profile_color(interaction.guild_id, interaction.user.id, None)
            await interaction.response.send_message(
                "🎨 Profilfarbe zurückgesetzt (nutzt jetzt deine Rollenfarbe).", ephemeral=True
            )
            return
        hexval = raw.lstrip("#")
        if len(hexval) != 6 or any(c not in "0123456789abcdef" for c in hexval):
            await interaction.response.send_message(
                "⚠️ Ungültige Farbe. Gib einen Hex-Code wie `#FF8800` an (oder `reset`).",
                ephemeral=True,
            )
            return
        value = int(hexval, 16)
        self.db.set_profile_color(interaction.guild_id, interaction.user.id, value)
        embed = discord.Embed(
            description=f"🎨 Profilfarbe gesetzt auf **#{hexval.upper()}**. Schau dir dein `/profile` an!",
            color=value,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProfileCog(bot))

"""Blackjack gegen den Bot-Dealer — mit Hit, Stand, Double Down und Split.

- Standard-Casino-Auszahlung: Gewinn 1:1, natürlicher Blackjack 3:2, Push = Einsatz zurück.
- Dealer zieht bis 17 (steht auf jeder 17, auch soft).
- Bedienung über Buttons; Karten werden als Unicode dargestellt (kein Custom-Emoji nötig).
- Coins sind dieselben wie im Leveling-/Coinflip-System.
"""

from __future__ import annotations

import logging
import random

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("oaken-tower-bot")

MAX_BET: int = 10000
GAME_TIMEOUT: float = 120.0
MAX_HANDS: int = 4
COIN_EMOJI_NAME = "YamiToken"
COIN_FALLBACK = "🪙"

RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
SUITS = ["♠", "♥", "♦", "♣"]
HIDDEN_CARD = "🂠"

Card = tuple[str, str]


def make_deck() -> list[Card]:
    deck = [(rank, suit) for suit in SUITS for rank in RANKS]
    random.shuffle(deck)
    return deck


def card_value(rank: str) -> int:
    if rank == "A":
        return 11
    if rank in ("10", "J", "Q", "K"):
        return 10
    return int(rank)


def hand_value(cards: list[Card]) -> int:
    """Bester Handwert; Asse zählen 11, werden bei Überschreiten zu 1."""
    total = sum(card_value(r) for r, _ in cards)
    aces = sum(1 for r, _ in cards if r == "A")
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def is_blackjack(cards: list[Card]) -> bool:
    return len(cards) == 2 and hand_value(cards) == 21


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _cards_str(cards: list[Card]) -> str:
    return " ".join(f"`{r}{s}`" for r, s in cards)


class Hand:
    def __init__(self, cards: list[Card], bet: int) -> None:
        self.cards = cards
        self.bet = bet
        self.done = False
        self.doubled = False


class BlackjackView(discord.ui.View):
    """Interaktive Blackjack-Runde eines einzelnen Spielers."""

    def __init__(self, cog: "BlackjackCog", interaction: discord.Interaction, bet: int) -> None:
        super().__init__(timeout=GAME_TIMEOUT)
        self.cog = cog
        self.db = cog.db
        self.guild = interaction.guild
        self.player = interaction.user
        self.coin = cog._coin(interaction.guild)
        self.message: discord.Message | None = None

        self.deck = make_deck()
        self.dealer: list[Card] = [self.deck.pop(), self.deck.pop()]
        self.hands: list[Hand] = [Hand([self.deck.pop(), self.deck.pop()], bet)]
        self.current = 0
        self.finished = False
        self.results: list[tuple[Hand, str, int]] = []
        self.new_balance = 0

    # --- Zugriff/Helpers ------------------------------------------------------

    def _balance(self) -> int:
        return int(self.db.get_user(self.guild.id, self.player.id)["coins"])

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player.id:
            await interaction.response.send_message(
                "Das ist nicht dein Blackjack-Spiel.", ephemeral=True
            )
            return False
        return True

    def _update_buttons(self) -> None:
        hand = self.hands[self.current]
        two = len(hand.cards) == 2
        balance = self._balance()
        can_double = two and balance >= hand.bet
        can_split = (
            two
            and card_value(hand.cards[0][0]) == card_value(hand.cards[1][0])
            and len(self.hands) < MAX_HANDS
            and balance >= hand.bet
        )
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.label == "Double":
                    child.disabled = not can_double
                elif child.label == "Split":
                    child.disabled = not can_split
                else:
                    child.disabled = False

    # --- Spielablauf ----------------------------------------------------------

    async def _refresh(self, interaction: discord.Interaction) -> None:
        """Nach einer Aktion: nächste Hand wählen oder Runde abrechnen."""
        while self.current < len(self.hands) and self.hands[self.current].done:
            self.current += 1
        if self.current >= len(self.hands):
            self._settle()
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(embed=self._render_final(), view=self)
            self.stop()
        else:
            self._update_buttons()
            await interaction.response.edit_message(embed=self._render(), view=self)

    def _settle(self) -> None:
        if self.finished:
            return
        # Dealer zieht bis 17.
        while hand_value(self.dealer) < 17:
            self.dealer.append(self.deck.pop())
        dv = hand_value(self.dealer)
        dealer_bj = is_blackjack(self.dealer)
        single = len(self.hands) == 1

        total_return = 0
        results: list[tuple[Hand, str, int]] = []
        for hand in self.hands:
            pv = hand_value(hand.cards)
            natural = single and is_blackjack(hand.cards)
            if pv > 21:
                outcome, ret = "bust", 0
            elif natural and not dealer_bj:
                outcome, ret = "blackjack", int(hand.bet * 2.5)
            elif dealer_bj and not natural:
                outcome, ret = "lose", 0
            elif dv > 21 or pv > dv:
                outcome, ret = "win", hand.bet * 2
            elif pv < dv:
                outcome, ret = "lose", 0
            else:
                outcome, ret = "push", hand.bet
            total_return += ret
            results.append((hand, outcome, ret))

        self.new_balance = self.db.add_coins(self.guild.id, self.player.id, total_return)
        self.results = results

        net = total_return - sum(h.bet for h in self.hands)
        outcome = "win" if net > 0 else "loss" if net < 0 else "push"
        self.db.record_game(self.guild.id, self.player.id, "blackjack", outcome)

        self.finished = True

    async def on_timeout(self) -> None:
        if self.finished:
            return
        for hand in self.hands:
            hand.done = True
        self._settle()
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(embed=self._render_final(timed_out=True), view=self)
            except discord.HTTPException:
                pass

    # --- Buttons --------------------------------------------------------------

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary, emoji="🃏")
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        hand = self.hands[self.current]
        hand.cards.append(self.deck.pop())
        if hand_value(hand.cards) >= 21:
            hand.done = True
        await self._refresh(interaction)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary, emoji="✋")
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.hands[self.current].done = True
        await self._refresh(interaction)

    @discord.ui.button(label="Double", style=discord.ButtonStyle.success, emoji="💰")
    async def double(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        hand = self.hands[self.current]
        if len(hand.cards) != 2 or self._balance() < hand.bet:
            await interaction.response.send_message(
                "⚠️ Double Down ist hier nicht möglich.", ephemeral=True
            )
            return
        self.db.add_coins(self.guild.id, self.player.id, -hand.bet)
        hand.bet *= 2
        hand.doubled = True
        hand.cards.append(self.deck.pop())
        hand.done = True
        await self._refresh(interaction)

    @discord.ui.button(label="Split", style=discord.ButtonStyle.success, emoji="✂️")
    async def split(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        hand = self.hands[self.current]
        if (
            len(hand.cards) != 2
            or card_value(hand.cards[0][0]) != card_value(hand.cards[1][0])
            or len(self.hands) >= MAX_HANDS
            or self._balance() < hand.bet
        ):
            await interaction.response.send_message(
                "⚠️ Splitten ist hier nicht möglich.", ephemeral=True
            )
            return
        self.db.add_coins(self.guild.id, self.player.id, -hand.bet)
        card_a, card_b = hand.cards
        new_hand = Hand([card_b, self.deck.pop()], hand.bet)
        hand.cards = [card_a, self.deck.pop()]
        self.hands.insert(self.current + 1, new_hand)
        # Gesplittete Asse bekommen je eine Karte und stehen dann.
        if card_a[0] == "A":
            hand.done = True
            new_hand.done = True
        await self._refresh(interaction)

    # --- Darstellung ----------------------------------------------------------

    def _render(self) -> discord.Embed:
        embed = discord.Embed(title="🃏 Blackjack", color=0x5865F2)
        embed.set_author(name=self.player.display_name, icon_url=self.player.display_avatar.url)
        shown = card_value(self.dealer[0][0])
        embed.add_field(
            name="Dealer",
            value=f"`{self.dealer[0][0]}{self.dealer[0][1]}` `{HIDDEN_CARD}`  (zeigt **{shown}**)",
            inline=False,
        )
        self._add_player_fields(embed, playing=True)
        embed.set_footer(text="Hit · Stand · Double · Split")
        return embed

    def _render_final(self, timed_out: bool = False) -> discord.Embed:
        dv = hand_value(self.dealer)
        total_bet = sum(h.bet for h in self.hands)
        net = sum(ret for _, _, ret in self.results) - total_bet
        color = 0x2ECC71 if net > 0 else 0xE74C3C if net < 0 else 0x95A5A6

        embed = discord.Embed(title="🃏 Blackjack — Ergebnis", color=color)
        embed.set_author(name=self.player.display_name, icon_url=self.player.display_avatar.url)
        dealer_note = " 💥 BUST" if dv > 21 else (" 🌟 Blackjack" if is_blackjack(self.dealer) else "")
        embed.add_field(
            name="Dealer",
            value=f"{_cards_str(self.dealer)}  (**{dv}**){dealer_note}",
            inline=False,
        )
        self._add_player_fields(embed, playing=False)

        net_str = f"+{_fmt(net)}" if net > 0 else _fmt(net)
        summary = f"Netto: **{net_str}** {self.coin} · Kontostand: **{_fmt(self.new_balance)}** {self.coin}"
        if timed_out:
            summary = "⏱️ Zeit abgelaufen.\n" + summary
        embed.description = summary
        return embed

    def _add_player_fields(self, embed: discord.Embed, playing: bool) -> None:
        labels = {
            "win": "✅ Gewonnen",
            "lose": "❌ Verloren",
            "push": "➖ Push",
            "blackjack": "🌟 Blackjack!",
            "bust": "💥 Bust",
        }
        outcomes = {id(h): o for h, o, _ in self.results}
        for i, hand in enumerate(self.hands):
            pv = hand_value(hand.cards)
            marker = "▶️ " if (playing and i == self.current) else ""
            base = "Deine Hand" if len(self.hands) == 1 else f"Hand {i + 1}"
            extra = " (Double)" if hand.doubled else ""
            name = f"{marker}{base} — Einsatz {_fmt(hand.bet)} {self.coin}{extra}"
            note = ""
            if not playing:
                note = "  →  " + labels.get(outcomes.get(id(hand), ""), "")
            elif pv > 21:
                note = "  💥 BUST"
            embed.add_field(name=name, value=f"{_cards_str(hand.cards)}  (**{pv}**){note}", inline=False)


class DuelChallengeView(discord.ui.View):
    """Herausforderung zum 1v1-Blackjack-Duell — Gegner nimmt per Button an."""

    def __init__(self, cog: "BlackjackCog", challenger: discord.Member, opponent: discord.Member, bet: int) -> None:
        super().__init__(timeout=60.0)
        self.cog = cog
        self.db = cog.db
        self.challenger = challenger
        self.opponent = opponent
        self.bet = bet
        self.coin = cog._coin(challenger.guild)
        self.message: discord.Message | None = None
        self.resolved = False

    def _balance(self, member: discord.Member) -> int:
        return int(self.db.get_user(member.guild.id, member.id)["coins"])

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in (self.challenger.id, self.opponent.id):
            await interaction.response.send_message("Diese Herausforderung gehört nicht dir.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        if self.resolved or self.message is None:
            return
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        try:
            await self.message.edit(content="⌛ Herausforderung abgelaufen.", embed=None, view=self)
        except discord.HTTPException:
            pass

    @discord.ui.button(label="Annehmen", emoji="✅", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message(
                "Nur die herausgeforderte Person kann annehmen.", ephemeral=True
            )
            return
        # Beide müssen den Einsatz noch aufbringen können.
        for member in (self.challenger, self.opponent):
            if self._balance(member) < self.bet:
                self.resolved = True
                for child in self.children:
                    child.disabled = True  # type: ignore[attr-defined]
                await interaction.response.edit_message(
                    content=f"⚠️ {member.mention} hat nicht mehr genug Coins für den Einsatz — Duell abgesagt.",
                    embed=None, view=self,
                )
                return
        self.resolved = True
        self.db.add_coins(self.challenger.guild.id, self.challenger.id, -self.bet)
        self.db.add_coins(self.opponent.guild.id, self.opponent.id, -self.bet)
        game = DuelGameView(self.cog, self.challenger, self.opponent, self.bet)
        game.message = self.message
        await interaction.response.edit_message(content=None, embed=game._render(), view=game)

    @discord.ui.button(label="Ablehnen", emoji="❌", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.resolved = True
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        who = "abgelehnt" if interaction.user.id == self.opponent.id else "zurückgezogen"
        await interaction.response.edit_message(
            content=f"❌ Duell {who}.", embed=None, view=self
        )


class DuelGameView(discord.ui.View):
    """Rundenbasiertes 1v1-Blackjack ohne Dealer: höhere Hand ≤21 gewinnt den Pot."""

    def __init__(self, cog: "BlackjackCog", challenger: discord.Member, opponent: discord.Member, bet: int) -> None:
        super().__init__(timeout=GAME_TIMEOUT)
        self.cog = cog
        self.db = cog.db
        self.guild = challenger.guild
        self.players: list[discord.Member] = [challenger, opponent]
        self.bet = bet
        self.coin = cog._coin(challenger.guild)
        self.message: discord.Message | None = None

        self.deck = make_deck()
        self.hands: dict[int, list[Card]] = {
            p.id: [self.deck.pop(), self.deck.pop()] for p in self.players
        }
        self.done: dict[int, bool] = {p.id: False for p in self.players}
        self.current = 0
        self.finished = False
        self.winner: discord.Member | None = None
        self.balances: dict[int, int] = {}
        # Wer schon mit 21 startet, ist sofort fertig.
        for p in self.players:
            if hand_value(self.hands[p.id]) >= 21:
                self.done[p.id] = True
        self._advance_to_active()

    def _current_player(self) -> discord.Member:
        return self.players[self.current]

    def _advance_to_active(self) -> None:
        for _ in range(len(self.players)):
            if not self.done[self._current_player().id]:
                return
            self.current = (self.current + 1) % len(self.players)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in (self.players[0].id, self.players[1].id):
            await interaction.response.send_message("Das ist nicht dein Duell.", ephemeral=True)
            return False
        if interaction.user.id != self._current_player().id and not self.finished:
            await interaction.response.send_message(
                f"⏳ Du bist nicht am Zug — {self._current_player().mention} spielt gerade.",
                ephemeral=True,
            )
            return False
        return True

    async def _after_action(self, interaction: discord.Interaction) -> None:
        if all(self.done.values()):
            self._settle()
            for child in self.children:
                child.disabled = True  # type: ignore[attr-defined]
            await interaction.response.edit_message(embed=self._render(final=True), view=self)
            self.stop()
            return
        # Nächsten spielbereiten Spieler wählen.
        if self.done[self._current_player().id]:
            self.current = (self.current + 1) % len(self.players)
            self._advance_to_active()
        await interaction.response.edit_message(embed=self._render(), view=self)

    def _settle(self) -> None:
        if self.finished:
            return
        p0, p1 = self.players
        v0, v1 = hand_value(self.hands[p0.id]), hand_value(self.hands[p1.id])
        bust0, bust1 = v0 > 21, v1 > 21
        bj0, bj1 = is_blackjack(self.hands[p0.id]), is_blackjack(self.hands[p1.id])
        if bust0 and bust1:
            winner = None
        elif bust0:
            winner = p1
        elif bust1:
            winner = p0
        elif bj0 and not bj1:
            winner = p0
        elif bj1 and not bj0:
            winner = p1
        elif v0 > v1:
            winner = p0
        elif v1 > v0:
            winner = p1
        else:
            winner = None

        if winner is None:  # Push → beide Einsätze zurück
            for p in self.players:
                self.balances[p.id] = self.db.add_coins(self.guild.id, p.id, self.bet)
                self.db.record_game(self.guild.id, p.id, "blackjack", "push")
        else:
            loser = p1 if winner.id == p0.id else p0
            self.balances[winner.id] = self.db.add_coins(self.guild.id, winner.id, self.bet * 2)
            self.balances[loser.id] = int(self.db.get_user(self.guild.id, loser.id)["coins"])
            self.db.record_game(self.guild.id, winner.id, "blackjack", "win")
            self.db.record_game(self.guild.id, loser.id, "blackjack", "loss")
        self.winner = winner
        self.finished = True

    async def on_timeout(self) -> None:
        if self.finished:
            return
        for p in self.players:
            self.done[p.id] = True
        self._settle()
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        if self.message:
            try:
                await self.message.edit(embed=self._render(final=True, timed_out=True), view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary, emoji="🃏")
    async def hit(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        pid = interaction.user.id
        self.hands[pid].append(self.deck.pop())
        if hand_value(self.hands[pid]) >= 21:
            self.done[pid] = True
        await self._after_action(interaction)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary, emoji="✋")
    async def stand(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.done[interaction.user.id] = True
        await self._after_action(interaction)

    def _render(self, final: bool = False, timed_out: bool = False) -> discord.Embed:
        if final:
            if self.winner is None:
                color, head = 0x95A5A6, "➖ Push — Einsätze zurück"
            else:
                color, head = 0x2ECC71, f"🏆 {self.winner.mention} gewinnt **{_fmt(self.bet * 2)}** {self.coin}!"
            title = "🃏 Blackjack-Duell — Ergebnis"
        else:
            color, head = 0x5865F2, f"▶️ {self._current_player().mention} ist am Zug"
            title = "🃏 Blackjack-Duell"

        embed = discord.Embed(title=title, description=head, color=color)
        for i, p in enumerate(self.players):
            pv = hand_value(self.hands[p.id])
            marker = "▶️ " if (not final and i == self.current) else ""
            note = ""
            if pv > 21:
                note = "  💥 BUST"
            elif final and is_blackjack(self.hands[p.id]):
                note = "  🌟 Blackjack"
            elif not final and self.done[p.id]:
                note = "  ✋ steht"
            embed.add_field(
                name=f"{marker}{p.display_name} — Einsatz {_fmt(self.bet)} {self.coin}",
                value=f"{_cards_str(self.hands[p.id])}  (**{pv}**){note}",
                inline=False,
            )
        if final:
            parts = [f"{p.display_name}: **{_fmt(self.balances.get(p.id, 0))}** {self.coin}" for p in self.players]
            footer = "Kontostände — " + " · ".join(parts)
            if timed_out:
                footer = "⏱️ Zeit abgelaufen. " + footer
            embed.set_footer(text=footer)
        else:
            embed.set_footer(text="Hit · Stand")
        return embed


class BlackjackCog(commands.Cog):
    """/blackjack."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]

    def _coin(self, guild: discord.Guild | None) -> str:
        if guild is not None:
            emoji = discord.utils.get(guild.emojis, name=COIN_EMOJI_NAME)
            if emoji is not None:
                return str(emoji)
        return COIN_FALLBACK

    @app_commands.command(name="blackjack", description="Spiele Blackjack gegen den Dealer.")
    @app_commands.guild_only()
    @app_commands.describe(einsatz=f"Einsatz in Coins (1–{MAX_BET})")
    async def blackjack(
        self, interaction: discord.Interaction, einsatz: app_commands.Range[int, 1, MAX_BET]
    ) -> None:
        guild = interaction.guild
        coin = self._coin(guild)
        balance = int(self.db.get_user(guild.id, interaction.user.id)["coins"])
        if einsatz > balance:
            await interaction.response.send_message(
                f"⚠️ Du hast nur **{_fmt(balance)}** {coin}, das reicht nicht für **{_fmt(einsatz)}**.",
                ephemeral=True,
            )
            return

        self.db.add_coins(guild.id, interaction.user.id, -einsatz)
        view = BlackjackView(self, interaction, einsatz)

        # Sofortiger natürlicher Blackjack → direkt abrechnen, keine Buttons.
        if is_blackjack(view.hands[0].cards):
            view._settle()
            await interaction.response.send_message(embed=view._render_final())
            view.message = await interaction.original_response()
            return

        view._update_buttons()
        await interaction.response.send_message(embed=view._render(), view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="blackjackvs", description="Fordere ein anderes Mitglied zum Blackjack-Duell heraus.")
    @app_commands.guild_only()
    @app_commands.describe(gegner="Wen forderst du heraus?", einsatz=f"Einsatz in Coins (1–{MAX_BET})")
    async def blackjackvs(
        self,
        interaction: discord.Interaction,
        gegner: discord.Member,
        einsatz: app_commands.Range[int, 1, MAX_BET],
    ) -> None:
        guild = interaction.guild
        coin = self._coin(guild)
        if gegner.bot or gegner.id == interaction.user.id:
            await interaction.response.send_message(
                "⚠️ Du kannst nur ein anderes Mitglied herausfordern.", ephemeral=True
            )
            return
        my_balance = int(self.db.get_user(guild.id, interaction.user.id)["coins"])
        if einsatz > my_balance:
            await interaction.response.send_message(
                f"⚠️ Du hast nur **{_fmt(my_balance)}** {coin}, das reicht nicht für **{_fmt(einsatz)}**.",
                ephemeral=True,
            )
            return
        opp_balance = int(self.db.get_user(guild.id, gegner.id)["coins"])
        if einsatz > opp_balance:
            await interaction.response.send_message(
                f"⚠️ {gegner.display_name} hat nur **{_fmt(opp_balance)}** {coin} und kann den Einsatz nicht aufbringen.",
                ephemeral=True,
            )
            return

        view = DuelChallengeView(self, interaction.user, gegner, einsatz)
        embed = discord.Embed(
            title="🃏 Blackjack-Duell",
            description=(
                f"{interaction.user.mention} fordert {gegner.mention} heraus!\n"
                f"Einsatz: **{_fmt(einsatz)}** {coin} pro Person · Gewinner kassiert **{_fmt(einsatz * 2)}** {coin}.\n\n"
                f"{gegner.mention}, nimmst du an?"
            ),
            color=0x5865F2,
        )
        await interaction.response.send_message(
            content=gegner.mention, embed=embed, view=view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BlackjackCog(bot))

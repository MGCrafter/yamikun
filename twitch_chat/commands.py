"""Text commands and moderation rules. No network calls inside transactions."""
from __future__ import annotations

import json
import math
import random
import re
import time
import unicodedata
from collections import OrderedDict, deque

from cogs.blackjack import hand_value, RANKS, SUITS
from cogs.economy import DAILY_CAP, DAILY_COOLDOWN, DAILY_PER_STREAK, DAILY_RESET, WEEK_BONUS
from cogs.roulette import BETS, _is_win, _color_name
from cogs.slots import PAYOUTS, DISPLAY, BASE_COPY
from cogs.social import friend_level
from twitch_chat.store import Store

SOCIAL = {"hug": "umarmt", "pat": "tätschelt", "kiss": "küsst", "slap": "gibt eine spielerische Ohrfeige an", "highfive": "gibt ein High-Five an"}
ALIASES = {"balance": "coins", "cf": "coinflip", "bj": "blackjack", "top": "leaderboard", "commands": "help"}
GAMES = {"coinflip", "slots", "roulette", "blackjack", "blackjackduel"}
LINK_RE = re.compile(r"(?:https?://|www\.|\b[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.(?:[a-z]{2,24})(?:[/\s:]|$))", re.I)
LOGIN_RE = re.compile(r"[a-zA-Z0-9_]{1,25}\Z")

COMMANDS = [
    ("help", "Alle verfügbaren Befehle"), ("coins", "Dein Guthaben"),
    ("daily", "Tägliche Coins abholen"), ("pay @name 50", "Coins überweisen"),
    ("leaderboard", "Die fünf reichsten Zuschauer"),
    ("hug / pat / kiss / slap / highfive @name", "Social-Aktionen"),
    ("friend add / accept / remove / level @name", "Freundschaften mit Zustimmung"),
    ("friend list / requests", "Freunde und Anfragen"),
    ("marry @name", "Heiratsantrag senden"), ("marry accept / decline @name", "Antrag beantworten"),
    ("marriages", "Deine Ehen"), ("divorce @name", "Ehe beenden"),
    ("coinflip 50 kopf", "Kopf oder zahl, 2× Auszahlung"),
    ("slots 50", "Drei gleiche Symbole gewinnen"),
    ("roulette 50 rot", "Farbe, gerade/ungerade, tief/hoch, Dutzend, Spalte oder 0–36"),
    ("blackjack 50", "Blackjack gegen den Dealer"),
    ("hit / stand / double / split", "Blackjack steuern (bis zu vier Hände)"),
    ("blackjackduel @name 50", "Blackjack-Duell starten"),
    ("blackjackduel accept / decline @name", "Duell beantworten; danach hit oder stand"),
]


class CommandError(ValueError):
    pass


def normalize_text(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", text) if unicodedata.category(c) != "Cf").casefold()


class Engine:
    def __init__(self, store: Store, bot_id: str, rng=None):
        self.store, self.db, self.bot_id = store, store.conn, bot_id
        self.rng = rng or random.SystemRandom()
        self.history: OrderedDict[tuple[str, str], deque] = OrderedDict()

    def linked(self, uid: str):
        return self.db.execute("SELECT discord_id FROM twitch_chat_links WHERE twitch_id=?", (uid,)).fetchone()

    def touch(self, cid: str, uid: str, login: str):
        self.db.execute("""INSERT INTO twitch_chat_wallets(channel_id,user_id,login) VALUES(?,?,?)
            ON CONFLICT(channel_id,user_id) DO UPDATE SET login=excluded.login""", (cid, uid, login))

    def balance(self, cid: str, uid: str) -> int:
        link = self.linked(uid)
        if link:
            row = self.db.execute("SELECT coins FROM levels WHERE guild_id=0 AND user_id=?", (link[0],)).fetchone()
        else:
            row = self.db.execute("SELECT coins FROM twitch_chat_wallets WHERE channel_id=? AND user_id=?", (cid, uid)).fetchone()
        return row[0] if row else 0

    def money(self, cid: str, uid: str, delta: int):
        link = self.linked(uid)
        if link:
            self.db.execute("INSERT OR IGNORE INTO levels(guild_id,user_id) VALUES(0,?)", (link[0],))
            cur = self.db.execute("UPDATE levels SET coins=coins+? WHERE guild_id=0 AND user_id=? AND coins+?>=0", (delta, link[0], delta))
        else:
            cur = self.db.execute("UPDATE twitch_chat_wallets SET coins=coins+? WHERE channel_id=? AND user_id=? AND coins+?>=0", (delta, cid, uid, delta))
        if not cur.rowcount:
            raise CommandError("Dafür reichen deine Coins nicht. Mit !daily bekommst du neue Coins.")

    def target(self, cid: str, uid: str, value: str) -> tuple[str, str]:
        login = value.lstrip("@").lower()
        if not LOGIN_RE.fullmatch(login):
            raise CommandError("Bitte einen gültigen @Twitch-Namen angeben.")
        rows = self.db.execute("SELECT user_id,login FROM twitch_chat_wallets WHERE channel_id=? AND login=?", (cid, login)).fetchall()
        if len(rows) != 1:
            raise CommandError("Diese Person muss zuerst einmal in diesem Chat schreiben.")
        target, name = rows[0]
        if target in {uid, self.bot_id}:
            raise CommandError("Bitte eine andere Person auswählen.")
        return target, name

    def moderation(self, cfg: dict, event: dict, now: float) -> str | None:
        if not cfg["automod_enabled"]:
            return None
        uid, cid = event["chatter_user_id"], event["broadcaster_user_id"]
        badges = {badge.get("set_id") for badge in event.get("badges", [])}
        if uid in {cid, self.bot_id} or badges & {"broadcaster", "moderator"}:
            return None
        text = normalize_text(event["message"]["text"])
        key = (cid, uid)
        history = self.history.setdefault(key, deque(maxlen=8))
        self.history.move_to_end(key)
        while history and now - history[0][0] > 8:
            history.popleft()
        history.append((now, text))
        if len(self.history) > 10000:
            self.history.popitem(last=False)
        if cfg["block_links"] and LINK_RE.search(text):
            return "Linkfilter"
        if any(normalize_text(word) in text for word in cfg["blocked_words"]):
            return "Gesperrter Begriff"
        letters = [c for c in event["message"]["text"] if c.isalpha()]
        if cfg["block_caps"] and len(letters) >= 12 and sum(c.isupper() for c in letters) / len(letters) >= .8:
            return "Zu viele Großbuchstaben"
        if cfg["block_spam"] and (len(history) >= 6 or sum(t == text for _, t in history) >= 3):
            return "Spam / Wiederholungen"
        return None

    def process(self, row: dict, now: float | None = None) -> dict:
        """Commit the result and economic effects together; retry returns the result."""
        now = time.time() if now is None else now
        with self.db:
            current = self.db.execute("SELECT processed,result FROM twitch_chat_events WHERE id=?", (row["id"],)).fetchone()
            if current[0]:
                return json.loads(current[1] or "{}")
            event = json.loads(row["payload"])
            cid, uid = event["broadcaster_user_id"], event["chatter_user_id"]
            channel = self.store.channel(cid)
            result = {}
            if channel and channel["enabled"] and uid != self.bot_id and now - row["created"] < 120:
                cfg = channel["settings"]
                self.touch(cid, uid, event["chatter_user_login"])
                reason = self.moderation(cfg, event, now)
                if reason:
                    action = "timeout" if cfg["timeout_seconds"] else "delete"
                    log = self.db.execute("INSERT INTO twitch_chat_modlog(channel_id,login,reason,action,created) VALUES(?,?,?,?,?)",
                                          (cid, event["chatter_user_login"], reason, action, now))
                    result = {"moderate": {"reason": reason, "duration": cfg["timeout_seconds"], "log_id": log.lastrowid}}
                else:
                    self.store.timer_activity(cid)
                    message = event["message"]["text"].strip()
                    if message.startswith(cfg["prefix"]):
                        parts = message[len(cfg["prefix"]):].split()
                        if parts:
                            command = ALIASES.get(parts[0].lower(), parts[0].lower())
                            # Resolve open hands even if the channel disabled the gambling module.
                            actions = {"hit", "stand", "double", "split"}
                            last = self.db.execute("SELECT command_at FROM twitch_chat_wallets WHERE channel_id=? AND user_id=?", (cid, uid)).fetchone()[0]
                            if now - last >= (1 if command in actions else cfg["command_cooldown"]):
                                self.db.execute("SAVEPOINT command")
                                try:
                                    reply = self.command(cid, uid, command, parts[1:], cfg, now)
                                except CommandError as exc:
                                    self.db.execute("ROLLBACK TO command")
                                    reply = str(exc).replace("!", cfg["prefix"])
                                finally:
                                    self.db.execute("RELEASE command")
                                if reply:
                                    self.db.execute("UPDATE twitch_chat_wallets SET command_at=? WHERE channel_id=? AND user_id=?", (now, cid, uid))
                                    result = {"reply": f"@{event['chatter_user_login']} {reply}"[:500]}
            self.db.execute("UPDATE twitch_chat_events SET processed=1,result=?,payload=? WHERE id=?",
                            (json.dumps(result), json.dumps(event), row["id"]))
            return result

    def bet(self, text: str, cfg: dict) -> int:
        if not re.fullmatch(r"[0-9]{1,6}", text) or not 1 <= int(text) <= cfg["max_bet"]:
            raise CommandError(f"Einsatz: eine ganze Zahl zwischen 1 und {cfg['max_bet']}.")
        return int(text)

    def command(self, cid: str, uid: str, cmd: str, args: list[str], cfg: dict, now: float) -> str | None:
        p = cfg["prefix"]
        if cmd == "help":
            groups = [f"{p}coins, {p}daily, {p}pay, {p}leaderboard"]
            if cfg["social_enabled"]:
                groups.append(f"{p}hug/pat/kiss/slap/highfive @name, {p}friend, {p}marry")
            if cfg["gambling_enabled"]:
                groups.append(f"{p}coinflip, {p}slots, {p}roulette, {p}blackjack, {p}blackjackduel")
            return " | ".join(groups) + " · Anleitung: yamikun.eu/twitch"
        if cmd == "coins":
            scope = "Discord & Twitch" if self.linked(uid) else "dieser Twitch-Channel"
            return f"{self.balance(cid, uid)} Coins ({scope})."
        if cmd == "daily":
            link = self.linked(uid)
            if link:
                row = self.db.execute("SELECT last_claim,streak FROM daily WHERE guild_id=0 AND user_id=?", (link[0],)).fetchone()
                last, streak = row if row else (0, 0)
            else:
                last = self.db.execute("SELECT daily_at FROM twitch_chat_wallets WHERE channel_id=? AND user_id=?", (cid, uid)).fetchone()[0]
                streak = 0
            if last and now - last < DAILY_COOLDOWN:
                return f"Daily wieder in {math.ceil((DAILY_COOLDOWN - now + last) / 60)} Minuten."
            if link:
                streak = streak + 1 if last and now - last <= DAILY_RESET else 1
                reward = min(DAILY_PER_STREAK * streak, DAILY_CAP) + (WEEK_BONUS if streak % 7 == 0 else 0)
                self.db.execute("INSERT OR REPLACE INTO daily VALUES(0,?,?,?)", (link[0], now, streak))
            else:
                reward = cfg["daily_coins"]
                self.db.execute("UPDATE twitch_chat_wallets SET daily_at=? WHERE channel_id=? AND user_id=?", (now, cid, uid))
            self.money(cid, uid, reward)
            return f"+{reward} Coins! Guthaben: {self.balance(cid, uid)}."
        if cmd == "leaderboard":
            rows = self.store.dashboard(cid)["leaderboard"][:5]
            return " | ".join(f"{i+1}. {r['login']}: {r['coins']}" for i, r in enumerate(rows)) or "Noch keine Coins."
        if cmd == "pay":
            if len(args) != 2:
                raise CommandError(f"{p}pay @name betrag")
            target, name = self.target(cid, uid, args[0])
            amount = self.bet(args[1], {"max_bet": 100000})
            if bool(self.linked(uid)) != bool(self.linked(target)):
                raise CommandError("Überweisungen brauchen denselben Coin-Typ: beide mit Discord verbunden oder beide ohne.")
            self.money(cid, uid, -amount)
            self.money(cid, target, amount)
            return f"{amount} Coins an @{name} überwiesen."
        if cmd in {*SOCIAL, "friend", "marry", "marriages", "divorce"}:
            if not cfg["social_enabled"]:
                return "Social-Commands sind hier deaktiviert."
            return self.social(cid, uid, cmd, args, now, p)
        if cmd in {"hit", "stand", "double", "split"}:
            return self.blackjack_action(cid, uid, cmd, now, p)
        if cmd not in GAMES:
            return None
        if not cfg["gambling_enabled"] and not (cmd == "blackjackduel" and args and args[0] == "decline"):
            return "Gambling ist hier deaktiviert."
        if cmd == "blackjackduel":
            return self.duel(cid, uid, args, cfg, now)
        if not args:
            raise CommandError(f"{p}{cmd} einsatz" + (" kopf|zahl" if cmd == "coinflip" else " rot|schwarz|0–36" if cmd == "roulette" else ""))
        bet = self.bet(args[0], cfg)
        if cmd == "blackjack":
            if len(args) != 1:
                raise CommandError(f"{p}blackjack einsatz")
            return self.blackjack_start(cid, uid, bet, now, p)
        self.money(cid, uid, -bet)
        if cmd == "coinflip":
            if len(args) != 2 or args[1].lower() not in {"kopf", "zahl"}:
                raise CommandError(f"{p}coinflip einsatz kopf|zahl")
            face = self.rng.choice(["kopf", "zahl"])
            payout = bet * 2 if args[1].lower() == face else 0
            label = face.capitalize()
        elif cmd == "slots":
            if len(args) != 1:
                raise CommandError(f"{p}slots einsatz")
            symbols = list(PAYOUTS)
            reels = [self.rng.choice(symbols)]
            reels += [reels[0] if self.rng.random() < BASE_COPY else self.rng.choice(symbols) for _ in range(2)]
            payout = bet * PAYOUTS[reels[0]] if len(set(reels)) == 1 else 0
            label = " · ".join(DISPLAY.get(r, "🪙") for r in reels)
        else:
            if len(args) not in {2, 3}:
                raise CommandError(f"{p}roulette einsatz rot|schwarz|gerade|ungerade|tief|hoch|dutzend1–3|spalte1–3|zahl 0–36")
            art, number = args[1].lower(), None
            if art.isascii() and art.isdigit() and len(args) == 2:
                number, art = int(art), "zahl"
            elif art == "zahl" and len(args) == 3 and re.fullmatch(r"[0-9]{1,2}", args[2]):
                number = int(args[2])
            elif len(args) != 2:
                raise CommandError("Ungültige Roulette-Wette.")
            if art not in BETS or (art == "zahl" and (number is None or not 0 <= number <= 36)):
                raise CommandError("Ungültige Roulette-Wette (Zahlen: 0–36).")
            result = self.rng.randrange(37)
            payout = bet * BETS[art][1] if _is_win(art, number, result) else 0
            label = f"{result} {_color_name(result)}"
        self.money(cid, uid, payout)
        return f"{label} · Einsatz {bet}, Auszahlung {payout} · Guthaben {self.balance(cid, uid)} Coins."

    def social(self, cid, uid, cmd, args, now, p):
        if cmd in {"marriages", "friend"} and (cmd == "marriages" or not args or args[0] in {"list", "requests"}):
            kind = "marry" if cmd == "marriages" else "friend"
            pending = args and args[0] == "requests"
            rows = self.db.execute("""SELECT r.*,w.login FROM twitch_chat_relations r
                JOIN twitch_chat_wallets w ON w.channel_id=r.channel_id AND w.user_id=CASE WHEN r.user_a=? THEN r.user_b ELSE r.user_a END
                WHERE r.channel_id=? AND r.kind=? AND (r.user_a=? OR r.user_b=?) AND r.accepted=?""",
                (uid, cid, kind, uid, uid, 0 if pending else 1)).fetchall()
            names = ["@" + r["login"] for r in rows if not pending or r["requester"] != uid]
            return ", ".join(names[:12]) or "Noch keine Einträge."
        action = "add"
        if cmd == "friend" or (cmd == "marry" and len(args) == 2):
            if len(args) != 2:
                raise CommandError(f"{p}{cmd} add|accept|remove|level @name")
            action, target_arg = args
        elif len(args) == 1:
            target_arg = args[0]
        else:
            raise CommandError(f"{p}{cmd} @name")
        target, name = self.target(cid, uid, target_arg)
        a, b = sorted([uid, target])
        if cmd in SOCIAL:
            self.db.execute("""UPDATE twitch_chat_relations SET xp=xp+1,xp_at=?
                WHERE channel_id=? AND kind='friend' AND user_a=? AND user_b=? AND accepted=1 AND xp_at<?""", (now, cid, a, b, now - 60))
            return f"{SOCIAL[cmd]} @{name}!"
        kind = "friend" if cmd == "friend" else "marry"
        key = (cid, kind, a, b)
        row = self.db.execute("SELECT * FROM twitch_chat_relations WHERE channel_id=? AND kind=? AND user_a=? AND user_b=?", key).fetchone()
        if cmd == "divorce" or action in {"remove", "decline"}:
            self.db.execute("DELETE FROM twitch_chat_relations WHERE channel_id=? AND kind=? AND user_a=? AND user_b=?", key)
            return f"Verbindung / Anfrage mit @{name} entfernt."
        if action == "level":
            return f"Freundschaft mit @{name}: Level {friend_level(row['xp'])}, {row['xp']} XP." if row and row["accepted"] else "Ihr seid noch nicht befreundet."
        if action == "accept":
            if not row or row["requester"] == uid or row["accepted"]:
                raise CommandError("Keine passende eingehende Anfrage.")
            self.db.execute("UPDATE twitch_chat_relations SET accepted=1 WHERE channel_id=? AND kind=? AND user_a=? AND user_b=?", key)
            return f"Du und @{name} seid jetzt {'befreundet' if kind == 'friend' else 'verheiratet'}!"
        if action != "add":
            raise CommandError("Unbekannte Social-Aktion.")
        if row:
            return "Diese Verbindung oder Anfrage besteht bereits."
        self.db.execute("INSERT INTO twitch_chat_relations(channel_id,kind,user_a,user_b,requester) VALUES(?,?,?,?,?)", (*key, uid))
        requester = self.db.execute("SELECT login FROM twitch_chat_wallets WHERE channel_id=? AND user_id=?", (cid, uid)).fetchone()[0]
        return f"Anfrage an @{name}! Annehmen mit {p}{kind} accept @{requester}."

    def deck(self):
        cards = [(r, s) for s in SUITS for r in RANKS]
        self.rng.shuffle(cards)
        return cards

    def busy(self, cid, uid):
        return self.db.execute("SELECT 1 FROM twitch_chat_games WHERE channel_id=? AND user_id=?", (cid, uid)).fetchone() or self.db.execute("SELECT 1 FROM twitch_chat_duels WHERE channel_id=? AND (challenger=? OR target=?)", (cid, uid, uid)).fetchone()

    def blackjack_start(self, cid, uid, bet, now, p):
        if self.busy(cid, uid):
            raise CommandError("Du hast bereits eine Runde oder Duellanfrage offen.")
        self.money(cid, uid, -bet)
        deck = self.deck()
        game = {"deck": deck, "hands": [{"cards": [deck.pop(), deck.pop()], "bet": bet, "stood": False}], "dealer": [deck.pop(), deck.pop()], "active": 0}
        if hand_value(game["dealer"]) == 21 or hand_value(game["hands"][0]["cards"]) == 21:
            return self.settle(cid, uid, game)
        self.save_game(cid, uid, game, now)
        return self.show_game(game, p, self.balance(cid, uid))

    def save_game(self, cid, uid, game, now):
        self.db.execute("INSERT OR REPLACE INTO twitch_chat_games VALUES(?,?,?,?)", (cid, uid, json.dumps(game), now + 120))

    def show_game(self, game, p, balance):
        hand = game["hands"][game["active"]]
        cards = " ".join("".join(c) for c in hand["cards"])
        label = f"Hand {game['active'] + 1}/{len(game['hands'])}" if len(game["hands"]) > 1 else "Du"
        actions = [f"{p}hit", f"{p}stand"]
        if len(hand["cards"]) == 2 and balance >= hand["bet"]:
            actions.append(f"{p}double")
            if len(game["hands"]) < 4 and hand["cards"][0][0] == hand["cards"][1][0]:
                actions.append(f"{p}split")
        return (f"Blackjack | {label}: {cards} ({hand_value(hand['cards'])} Punkte) | "
                f"Dealer: {''.join(game['dealer'][0])} + verdeckt | {' · '.join(actions)} | 120 s bis Stand")

    def blackjack_action(self, cid, uid, cmd, now, p):
        row = self.db.execute("SELECT state,expires FROM twitch_chat_games WHERE channel_id=? AND user_id=?", (cid, uid)).fetchone()
        if not row:
            raise CommandError(f"Keine offene Runde. Starte mit {p}blackjack einsatz.")
        game = json.loads(row[0])
        if "duel" in game:
            return self.duel_action(cid, uid, game["duel"], cmd, now, p)
        if row[1] <= now:
            return self.settle(cid, uid, game)
        hand = game["hands"][game["active"]]
        if cmd == "split":
            if len(game["hands"]) >= 4 or len(hand["cards"]) != 2 or hand["cards"][0][0] != hand["cards"][1][0]:
                raise CommandError("Split braucht zwei gleiche Kartenwerte; maximal vier Hände.")
            self.money(cid, uid, -hand["bet"])
            new = {"cards": [hand["cards"].pop(), game["deck"].pop()], "bet": hand["bet"], "stood": False}
            hand["cards"].append(game["deck"].pop())
            game["hands"].insert(game["active"] + 1, new)
        elif cmd == "double":
            if len(hand["cards"]) != 2:
                raise CommandError("Double ist nur mit den ersten zwei Karten möglich.")
            self.money(cid, uid, -hand["bet"])
            hand["bet"] *= 2
            hand["cards"].append(game["deck"].pop())
            hand["stood"] = True
        elif cmd == "hit":
            hand["cards"].append(game["deck"].pop())
        else:
            hand["stood"] = True
        while game["active"] < len(game["hands"]):
            current = game["hands"][game["active"]]
            if not current["stood"] and hand_value(current["cards"]) < 21:
                break
            game["active"] += 1
        if game["active"] >= len(game["hands"]):
            return self.settle(cid, uid, game)
        self.save_game(cid, uid, game, now)
        return self.show_game(game, p, self.balance(cid, uid))

    def settle(self, cid, uid, game):
        dealer = game["dealer"]
        while hand_value(dealer) < 17:
            dealer.append(game["deck"].pop())
        dv = hand_value(dealer)
        payout = 0
        results = []
        for hand in game["hands"]:
            value, bet = hand_value(hand["cards"]), hand["bet"]
            natural = len(game["hands"]) == 1 and len(hand["cards"]) == 2 and value == 21
            dealer_natural = len(dealer) == 2 and dv == 21
            if value > 21 or (dealer_natural and not natural):
                amount = 0
            elif natural and not dealer_natural:
                amount = bet + bet * 3 // 2
            elif value == dv:
                amount = bet
            elif dv > 21 or value > dv:
                amount = bet * 2
            else:
                amount = 0
            payout += amount
            outcome = "Überkauft" if value > 21 else "Blackjack!" if natural and amount > bet else "Gewonnen" if amount > bet else "Gleichstand" if amount == bet else "Verloren"
            label = f"Hand {len(results) + 1}: " if len(game["hands"]) > 1 else ""
            results.append(f"{label}{outcome} ({value})")
        self.money(cid, uid, payout)
        self.db.execute("DELETE FROM twitch_chat_games WHERE channel_id=? AND user_id=?", (cid, uid))
        return f"Blackjack | {' · '.join(results)} | Dealer: {dv} | Auszahlung {payout} | Guthaben {self.balance(cid, uid)} Coins."

    def duel(self, cid, uid, args, cfg, now):
        if len(args) == 2 and args[0] in {"accept", "decline"}:
            challenger, name = self.target(cid, uid, args[1])
            row = self.db.execute("SELECT * FROM twitch_chat_duels WHERE channel_id=? AND challenger=? AND target=? AND state IS NULL", (cid, challenger, uid)).fetchone()
            if not row:
                raise CommandError("Keine passende Duellanfrage.")
            if args[0] == "decline" or row["expires"] <= now:
                self.money(cid, challenger, row["bet"])
                self.db.execute("DELETE FROM twitch_chat_duels WHERE channel_id=? AND challenger=?", (cid, challenger))
                return "Duell beendet, Einsatz zurückgegeben."
            self.money(cid, uid, -row["bet"])
            deck = self.deck()
            state = {"deck": deck, "players": {u: {"cards": [deck.pop(), deck.pop()], "stood": False} for u in (challenger, uid)}}
            self.db.execute("UPDATE twitch_chat_duels SET state=?,expires=? WHERE channel_id=? AND challenger=?", (json.dumps(state), now + 120, cid, challenger))
            for u in (challenger, uid):
                self.save_game(cid, u, {"duel": challenger}, now)
            return f"Duell angenommen! @{name} und du: {cfg['prefix']}hit oder {cfg['prefix']}stand (120 s, kein Split/Double). " + self.duel_hands(cid, state)
        if len(args) != 2:
            raise CommandError(f"{cfg['prefix']}blackjackduel @name einsatz oder accept|decline @name")
        target, name = self.target(cid, uid, args[0])
        if bool(self.linked(uid)) != bool(self.linked(target)):
            raise CommandError("Für Duelle müssen beide denselben Coin-Typ nutzen.")
        if self.busy(cid, uid) or self.busy(cid, target):
            raise CommandError("Eine Person hat bereits eine offene Runde / Duellanfrage.")
        bet = self.bet(args[1], cfg)
        self.money(cid, uid, -bet)
        self.db.execute("INSERT INTO twitch_chat_duels(channel_id,challenger,target,bet,expires) VALUES(?,?,?,?,?)", (cid, uid, target, bet, now + 120))
        name_self = self.db.execute("SELECT login FROM twitch_chat_wallets WHERE channel_id=? AND user_id=?", (cid, uid)).fetchone()[0]
        return f"@{name}, Duell um {bet} Coins! {cfg['prefix']}blackjackduel accept @{name_self} (120 s)."

    def duel_hands(self, cid, state):
        parts = []
        for uid, hand in state["players"].items():
            name = self.db.execute("SELECT login FROM twitch_chat_wallets WHERE channel_id=? AND user_id=?", (cid, uid)).fetchone()[0]
            parts.append(f"@{name}: {' '.join(''.join(c) for c in hand['cards'])} = {hand_value(hand['cards'])}")
        return " | ".join(parts)

    def duel_action(self, cid, uid, challenger, cmd, now, p):
        row = self.db.execute("SELECT * FROM twitch_chat_duels WHERE channel_id=? AND challenger=?", (cid, challenger)).fetchone()
        state = json.loads(row["state"])
        hand = state["players"][uid]
        if cmd not in {"hit", "stand"}:
            raise CommandError("Im Duell sind hit und stand möglich.")
        if hand["stood"]:
            return "Du stehst bereits; die andere Person ist dran."
        if cmd == "hit" and row["expires"] > now:
            hand["cards"].append(state["deck"].pop())
        else:
            hand["stood"] = True
        for h in state["players"].values():
            if hand_value(h["cards"]) >= 21 or row["expires"] <= now:
                h["stood"] = True
        self.db.execute("UPDATE twitch_chat_duels SET state=? WHERE channel_id=? AND challenger=?", (json.dumps(state), cid, challenger))
        if all(h["stood"] for h in state["players"].values()):
            return self.settle_duel(dict(row), state)
        return self.duel_hands(cid, state) + f" · {p}hit / {p}stand"

    def settle_duel(self, row, state):
        cid, a, b, bet = row["channel_id"], row["challenger"], row["target"], row["bet"]
        scores = {u: hand_value(h["cards"]) if hand_value(h["cards"]) <= 21 else 0 for u, h in state["players"].items()}
        if scores[a] == scores[b]:
            self.money(cid, a, bet)
            self.money(cid, b, bet)
            result = "Gleichstand, beide Einsätze zurück."
        else:
            winner = max(scores, key=scores.get)
            self.money(cid, winner, bet * 2)
            name = self.db.execute("SELECT login FROM twitch_chat_wallets WHERE channel_id=? AND user_id=?", (cid, winner)).fetchone()[0]
            result = f"@{name} gewinnt {bet * 2} Coins Auszahlung!"
        self.db.execute("DELETE FROM twitch_chat_games WHERE channel_id=? AND user_id IN (?,?)", (cid, a, b))
        self.db.execute("DELETE FROM twitch_chat_duels WHERE channel_id=? AND challenger=?", (cid, a))
        return self.duel_hands(cid, state) + " · " + result

    def expire_games(self, now=None, channel_id=None):
        """Auto-stand on timeout; invitations refund escrow, including after restart."""
        now = time.time() if now is None else now
        with self.db:
            for row in self.db.execute("SELECT * FROM twitch_chat_duels").fetchall():
                if row["expires"] > now and row["channel_id"] != channel_id:
                    continue
                if row["state"]:
                    self.settle_duel(dict(row), json.loads(row["state"]))
                else:
                    self.money(row["channel_id"], row["challenger"], row["bet"])
                    self.db.execute("DELETE FROM twitch_chat_duels WHERE channel_id=? AND challenger=?", (row["channel_id"], row["challenger"]))
            for row in self.db.execute("SELECT * FROM twitch_chat_games").fetchall():
                if row["expires"] <= now or row["channel_id"] == channel_id:
                    self.settle(row["channel_id"], row["user_id"], json.loads(row["state"]))

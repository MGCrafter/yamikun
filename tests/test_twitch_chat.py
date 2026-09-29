from __future__ import annotations

import hashlib
import asyncio
import hmac
import json
import random
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest
import pytest_asyncio
import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from cryptography.fernet import Fernet

from db import Database
from twitch_chat.commands import Engine
from twitch_chat.service import SCOPES, Service, TwitchError
from twitch_chat.store import DEFAULTS, Store
from webpanel.twitch_chat import SESSION, STATE, TwitchChatPanel, settings


@pytest.fixture
def store(tmp_path):
    db = Database(str(tmp_path / "chat.db"))
    store = Store(db.conn)
    for uid in ("100", "200"):
        store.save_account(uid, "channel", "channel" + uid, "Channel", "encrypted")
        store.configure(uid, True, dict(DEFAULTS))
    yield store
    db.close()


def event(text="!daily", *, cid="100", uid="10", name="luna", message_id="msg-1", **extra):
    return {"broadcaster_user_id": cid, "chatter_user_id": uid, "chatter_user_login": name,
            "message_id": message_id, "message": {"text": text}, "badges": [], **extra}


def run(engine, text="!daily", *, now=1000, **kwargs):
    evt = event(text, **kwargs)
    engine.store.enqueue(evt, now)
    row = engine.db.execute("SELECT * FROM twitch_chat_events WHERE id=?", (evt["broadcaster_user_id"] + ":" + evt["message_id"],)).fetchone()
    return engine.process(dict(row), now)


def test_daily_deduplicates_across_restart_and_channels_are_isolated(store):
    engine = Engine(store, "999")
    first = run(engine)
    assert "+500" in first["reply"]
    assert run(Engine(store, "999")) == first
    assert engine.balance("100", "10") == 500
    assert engine.balance("200", "10") == 0
    assert "Daily wieder" in run(engine, now=1020, message_id="msg-2")["reply"]
    run(engine, cid="200")
    assert engine.balance("200", "10") == 500


def test_chat_automatically_claims_daily_once_and_at_cooldown_boundary(store):
    engine = Engine(store, "999")
    store.configure("100", True, {**DEFAULTS, "daily_coins": 750})
    assert run(engine, "Hallo!") == {}
    assert engine.balance("100", "10") == 750
    assert run(Engine(store, "999"), "Hallo!") == {}
    assert run(engine, "Noch da", now=1000 + 86400 - 1, message_id="early") == {}
    assert engine.balance("100", "10") == 750
    assert run(engine, "Neuer Tag", now=1000 + 86400, message_id="next-day") == {}
    assert engine.balance("100", "10") == 1500
    assert run(engine, "Hallo", cid="200", message_id="other-channel") == {}
    assert engine.balance("200", "10") == 500


def test_automatic_daily_shares_discord_cooldown_and_streak(store):
    engine = Engine(store, "999")
    with store.conn:
        store.conn.execute("INSERT INTO twitch_chat_links VALUES('10',123,'Luna')")
        store.conn.execute("INSERT INTO daily VALUES(0,123,1000,6)")
    run(engine, "Hallo", now=1001)
    assert engine.balance("100", "10") == 0
    run(engine, "Hallo", now=87400, message_id="next-day")
    from cogs.economy import DAILY_PER_STREAK, DAILY_CAP, WEEK_BONUS
    reward = min(7 * DAILY_PER_STREAK, DAILY_CAP) + WEEK_BONUS
    assert engine.balance("100", "10") == reward
    run(engine, "Hallo", cid="200", now=87401, message_id="other-channel")
    assert engine.balance("200", "10") == reward
    assert store.conn.execute("SELECT last_claim,streak FROM daily WHERE user_id=123").fetchone()[:] == (87400, 7)


@pytest.mark.parametrize("kind", ["bot", "disabled", "moderated", "expired"])
def test_automatic_daily_ignores_ineligible_messages(store, kind):
    engine = Engine(store, "999")
    uid = "999" if kind == "bot" else "10"
    store.configure("100", kind != "disabled", {**DEFAULTS, "automod_enabled": True, "blocked_words": ["blocked"]})
    evt = event("blocked" if kind == "moderated" else "Hallo", uid=uid)
    store.enqueue(evt, 1000)
    row = store.conn.execute("SELECT * FROM twitch_chat_events").fetchone()
    engine.process(dict(row), 1120 if kind == "expired" else 1000)
    assert engine.balance("100", uid) == 0


def test_automatic_daily_precedes_commands_and_survives_command_errors(store):
    engine = Engine(store, "999")
    assert "500 Coins" in run(engine, "!coins")["reply"]
    assert run(engine, "!slots invalid", uid="20", message_id="invalid")["reply"]
    assert engine.balance("100", "20") == 500
    # Claiming automatically must also work while commands are on cooldown.
    with store.conn:
        store.conn.execute("UPDATE twitch_chat_wallets SET command_at=87400 WHERE user_id='10'")
    assert run(engine, "!coins", now=87400, message_id="cooldown") == {}
    assert engine.balance("100", "10") == 1000


@pytest.mark.parametrize("text", ["!coinflip -5 kopf", "!coinflip 10001 kopf", "!coinflip 20 invalid", "!roulette 50 99", "!roulette 50 rot extra", "!slots 50 extra", "!coinflip 2.5 kopf", "!slots 999999999999999999", "!roulette 25 zahl -1"])
def test_bad_bets_rollback_without_spending(store, text):
    engine = Engine(store, "999")
    run(engine)
    result = run(engine, text, now=1010, message_id="invalid")
    assert result.get("reply")
    assert engine.balance("100", "10") == 500


def test_duplicate_coinflip_pays_only_once_and_cooldown_blocks_spam(store):
    engine = Engine(store, "999", random.Random(1))
    run(engine)
    result = run(engine, "!coinflip 50 kopf", now=1010, message_id="flip")
    balance = engine.balance("100", "10")
    assert balance in {450, 550}
    assert run(Engine(store, "999"), "!coinflip 50 kopf", now=1010, message_id="flip") == result
    assert engine.balance("100", "10") == balance
    assert run(engine, "!slots 50", now=1011, message_id="spam") == {}


def test_economy_link_uses_discord_daily_and_never_moves_channel_coins(store):
    engine = Engine(store, "999")
    run(engine)
    with store.conn:
        store.conn.execute("INSERT INTO twitch_chat_links VALUES('10',123,'Discord Luna')")
        store.conn.execute("INSERT INTO levels(guild_id,user_id,coins) VALUES(0,123,900)")
    assert engine.balance("100", "10") == 900
    assert "+10" in run(engine, now=1010, message_id="shared-daily")["reply"]
    assert engine.balance("100", "10") == 910
    assert "Daily wieder" in run(engine, cid="200", now=1020, message_id="shared-other")["reply"]
    assert store.conn.execute("SELECT last_claim,streak FROM daily WHERE guild_id=0 AND user_id=123").fetchone()[:] == (1010, 1)
    with store.conn:
        store.conn.execute("DELETE FROM twitch_chat_links WHERE twitch_id='10'")
    assert engine.balance("100", "10") == 500


def test_chat_link_uses_discord_balance_across_channels_and_restart(store):
    engine = Engine(store, "999")
    code = store.create_link_code(123, "Luna", "luna", 1000)
    with store.conn:
        store.conn.execute("INSERT INTO levels(guild_id,user_id,coins) VALUES(0,123,4321)")
        store.conn.execute("INSERT INTO daily VALUES(0,123,1000,3)")
    response = run(engine, f"!link {code}", now=1001)
    assert "4321 Coins (Discord & Twitch)" in response["reply"]
    assert not store.conn.execute("SELECT 1 FROM twitch_chat_link_codes").fetchone()
    assert engine.balance("200", "10") == 4321
    assert run(Engine(store, "999"), f"!link {code}", now=1002) == response
    assert "4321 Coins" in run(engine, "!coins", now=1010, message_id="coins")["reply"]
    assert "Mit Discord verbunden" in run(engine, "!link", now=1020, message_id="status")["reply"]
    assert store.conn.execute("SELECT coins FROM twitch_chat_wallets WHERE user_id='10'").fetchone()[0] == 500
    assert store.conn.execute("SELECT last_claim FROM daily WHERE user_id=123").fetchone()[0] == 1000


@pytest.mark.parametrize("case", ["wrong_user", "expired", "replaced", "already_linked", "game", "duel"])
def test_link_code_rejects_invalid_claims_without_changing_accounts(store, case):
    engine = Engine(store, "999")
    code = store.create_link_code(123, "Luna", "luna", 1000)
    with store.conn:
        if case == "already_linked":
            store.conn.execute("INSERT INTO twitch_chat_links VALUES('20',123,'Luna')")
        if case == "game":
            store.conn.execute("INSERT INTO twitch_chat_games VALUES('200','10','{}',2000)")
        if case == "duel":
            store.conn.execute("INSERT INTO twitch_chat_duels VALUES('200','20','10',50,2000,NULL)")
    if case == "replaced":
        store.create_link_code(123, "Luna", "luna", 1001)
    result = run(engine, f"!link {code}", name="other" if case == "wrong_user" else "luna",
                 now=1600 if case == "expired" else 1002)
    assert "reply" in result
    assert not engine.linked("10")
    assert engine.balance("100", "10") == 500


def test_link_instructions_and_prefix_work_without_website_account(store):
    engine = Engine(store, "999")
    store.configure("100", True, {**DEFAULTS, "prefix": "?"})
    assert "?link CODE" in run(engine, "?link")["reply"]
    code = store.create_link_code(123, "Luna", "LUNA", 1000)
    assert "Discord verbunden!" in run(engine, f"?link {code.lower()}", now=1010, message_id="link")["reply"]
    assert store.account("10") is None


@pytest.mark.asyncio
async def test_discord_link_command_returns_private_name_bound_code(store):
    from cogs.twitch_link import TwitchLinkCog
    cog = TwitchLinkCog(SimpleNamespace(db=SimpleNamespace(conn=store.conn)))
    interaction = SimpleNamespace(user=SimpleNamespace(id=123), response=SimpleNamespace(send_message=AsyncMock()))
    await cog.twitch_link.callback(cog, interaction, "xJessyX10")
    sent = interaction.response.send_message.call_args
    assert sent.kwargs["ephemeral"] is True
    assert "!link " in sent.args[0]
    row = store.conn.execute("SELECT * FROM twitch_chat_link_codes").fetchone()
    assert row["twitch_login"] == "xjessyx10"
    assert row["code_hash"] not in sent.args[0]


def test_pay_cannot_convert_channel_coins_to_discord(store):
    engine = Engine(store, "999")
    run(engine)
    run(engine, uid="20", name="neko", message_id="other")
    with store.conn:
        store.conn.execute("INSERT INTO twitch_chat_links VALUES('20',123,'Neko')")
    result = run(engine, "!pay @neko 50", now=1010, message_id="pay")
    assert "Coin-Typ" in result["reply"]
    assert engine.balance("100", "10") == 500
    assert engine.balance("100", "20") == 0


def test_friend_requests_require_target_consent_and_identity_is_id_based(store):
    engine = Engine(store, "999")
    run(engine, "hallo")
    run(engine, "hallo", uid="20", name="neko", message_id="other")
    run(engine, "!friend add @neko", now=1010, message_id="request")
    result = run(engine, "!friend accept @neko", now=1020, message_id="self")
    assert "Keine passende" in result["reply"]
    run(engine, "!friend accept @luna", uid="20", name="renamed", now=1030, message_id="accept")
    assert store.conn.execute("SELECT accepted FROM twitch_chat_relations").fetchone()[0] == 1
    assert "@renamed" in run(engine, "!friend list", now=1040, message_id="list")["reply"]


@pytest.mark.parametrize("cfg,text,reason", [
    ({"block_links": True}, "hier: https://example.com", "Linkfilter"),
    ({"block_caps": True}, "DAS IST VIEL ZU LAUT", "Großbuchstaben"),
    ({"blocked_words": ["spamword"]}, "sPaM\u200bWord", "Gesperrter Begriff"),
])
def test_automod_blocks_before_commands_and_exempts_mods(store, cfg, text, reason):
    engine = Engine(store, "999")
    store.configure("100", True, {**DEFAULTS, "automod_enabled": True, **cfg})
    result = run(engine, text)
    assert reason in result["moderate"]["reason"]
    assert "reply" not in result
    assert run(engine, text, message_id="mod", badges=[{"set_id": "moderator"}]) == {}
    assert run(engine, text, uid="100", message_id="owner") == {}
    assert run(engine, "!daily", uid="999", message_id="bot") == {}


def test_spam_window_expires(store):
    engine = Engine(store, "999")
    store.configure("100", True, {**DEFAULTS, "automod_enabled": True})
    assert run(engine, "spam") == {}
    assert run(engine, "spam", now=1001, message_id="2") == {}
    assert "moderate" in run(engine, "spam", now=1002, message_id="3")
    assert run(engine, "spam", now=1020, message_id="4") == {}


def fixed_game(engine, cards, dealer, deck, bet=50):
    with engine.db:
        engine.money("100", "10", -bet)
        engine.save_game("100", "10", {"hands": [{"cards": cards, "bet": bet, "stood": False}], "dealer": dealer, "deck": deck, "active": 0}, 1000)


def test_blackjack_restart_and_timeout_settle_once(store):
    engine = Engine(store, "999")
    run(engine)
    fixed_game(engine, [["10", "♠"], ["Q", "♠"]], [["10", "♥"], ["7", "♥"]], [])
    restarted = Engine(store, "999")
    restarted.expire_games(now=1201)
    assert restarted.balance("100", "10") == 550
    restarted.expire_games(now=1202)
    assert restarted.balance("100", "10") == 550


def test_blackjack_bust_double_split_and_naturals(store):
    engine = Engine(store, "999")
    run(engine)
    fixed_game(engine, [["10", "♠"], ["9", "♠"]], [["10", "♥"], ["7", "♥"]], [["5", "♥"]])
    result = run(engine, "!hit", now=1010, message_id="hit")
    assert "Auszahlung 0" in result["reply"]
    assert engine.balance("100", "10") == 450
    fixed_game(engine, [["5", "♠"], ["6", "♠"]], [["10", "♥"], ["7", "♥"]], [["10", "♦"]])
    assert "Auszahlung 200" in run(engine, "!double", now=1020, message_id="double")["reply"]
    assert engine.balance("100", "10") == 550
    fixed_game(engine, [["8", "♠"], ["8", "♥"]], [["10", "♥"], ["7", "♥"]], [["10", "♦"], ["10", "♣"]])
    run(engine, "!split", now=1030, message_id="split")
    run(engine, "!stand", now=1032, message_id="stand1")
    run(engine, "!stand", now=1034, message_id="stand2")
    assert engine.balance("100", "10") == 650
    fixed_game(engine, [["A", "♠"], ["K", "♠"]], [["10", "♥"], ["7", "♥"]], [])
    assert "Auszahlung 125" in run(engine, "!stand", now=1040, message_id="natural")["reply"]


@pytest.mark.parametrize("cards,balance,expected", [
    ([["6", "♦"], ["J", "♥"]], 50, ["double"]),
    ([["8", "♦"], ["8", "♥"]], 50, ["double", "split"]),
    ([["8", "♦"], ["8", "♥"]], 49, []),
    ([["2", "♦"], ["3", "♥"], ["4", "♠"]], 50, []),
])
def test_blackjack_prompt_shows_only_available_actions(store, cards, balance, expected):
    game = {"hands": [{"cards": cards, "bet": 50}], "active": 0, "dealer": [["2", "♠"], ["K", "♥"]]}
    prompt = Engine(store, "999").show_game(game, "?", balance)
    assert prompt.startswith("Blackjack | Du:")
    assert "Punkte) | Dealer: 2♠ + verdeckt" in prompt
    assert "K♥" not in prompt and "Hand 1" not in prompt
    assert "?hit · ?stand" in prompt
    for command in ("double", "split"):
        assert ("?" + command in prompt) == (command in expected)
    game["hands"] *= 4
    game["active"] = 2
    prompt = Engine(store, "999").show_game(game, "!", balance)
    assert "Hand 3/4:" in prompt and "!split" not in prompt


def test_duel_escrow_consent_expiry_and_settlement(store):
    engine = Engine(store, "999", random.Random(4))
    run(engine)
    run(engine, uid="20", name="neko", message_id="neko")
    run(engine, "!blackjackduel @neko 50", now=1010, message_id="invite")
    assert engine.balance("100", "10") == 450
    assert engine.balance("100", "20") == 500
    engine.expire_games(now=1200)
    assert engine.balance("100", "10") == 500
    run(engine, "!blackjackduel @neko 50", now=1210, message_id="invite2")
    run(engine, "!blackjackduel accept @luna", uid="20", name="neko", now=1220, message_id="accept")
    assert engine.balance("100", "20") == 450
    run(engine, "!stand", now=1230, message_id="stand1")
    run(engine, "!stand", uid="20", name="neko", now=1240, message_id="stand2")
    assert engine.balance("100", "10") + engine.balance("100", "20") == 1000
    assert store.conn.execute("SELECT COUNT(*) FROM twitch_chat_games").fetchone()[0] == 0
    assert store.conn.execute("SELECT COUNT(*) FROM twitch_chat_duels").fetchone()[0] == 0


@pytest.mark.parametrize("key,value", [("prefix", "/"), ("prefix", "! x"), ("max_bet", True), ("daily_coins", 10001), ("timeout_seconds", -1), ("blocked_words", [""]), ("blocked_words", ["\u200b"]), ("blocked_words", "text"), ("block_links", "false")])
def test_settings_reject_invalid_fields(key, value):
    with pytest.raises(ValueError):
        settings({**DEFAULTS, key: value})


@pytest.fixture
def configured(monkeypatch):
    for key, value in {"TWITCH_CHAT_ENABLED": "1", "TWITCH_CLIENT_ID": "client", "TWITCH_CLIENT_SECRET": "secret",
                       "TWITCH_BOT_USER_ID": "999", "TWITCH_EVENTSUB_SECRET": "s" * 64, "TWITCH_TOKEN_KEY": Fernet.generate_key().decode()}.items():
        monkeypatch.setenv(key, value)


@pytest_asyncio.fixture
async def panel(store, configured):
    parent = SimpleNamespace(db=SimpleNamespace(conn=store.conn), base_url="https://yamikun.eu", _session=lambda r: None)
    panel = TwitchChatPanel(parent)
    panel.secure = False  # aiohttp TestClient uses local HTTP; production is HTTPS.
    app = web.Application()
    panel.register(app)
    async with TestClient(TestServer(app)) as client:
        yield panel, client


def login_session(panel, client, uid="100"):
    with panel.store.conn:
        panel.store.conn.execute("INSERT OR REPLACE INTO twitch_chat_sessions VALUES(?,?,?,?)", (panel.store.digest("session"), uid, "csrf", time.time() + 10000))
    client.session.cookie_jar.update_cookies({SESSION: "session"})


def signed(panel, evt=None, kind="notification", *, stamp=None, raw=None):
    data = {"subscription": {"type": "channel.chat.message", "condition": {"broadcaster_user_id": "100", "user_id": "999"}}, "event": evt or event()}
    if kind == "webhook_callback_verification":
        data["challenge"] = "challenge-text"
    raw = raw or json.dumps(data).encode()
    stamp = stamp or datetime.now(timezone.utc).isoformat()
    headers = {"Twitch-Eventsub-Message-Id": "delivery-1", "Twitch-Eventsub-Message-Timestamp": stamp, "Twitch-Eventsub-Message-Type": kind}
    headers["Twitch-Eventsub-Message-Signature"] = "sha256=" + hmac.new(panel.service.secret.encode(), ("delivery-1" + stamp).encode() + raw, hashlib.sha256).hexdigest()
    return raw, headers


def auto_message(**changes):
    return {"id": "discord", "name": "Discord", "text": "Unser Discord: https://example.com",
            "enabled": True, "interval_minutes": 1, "min_messages": 0, "live_only": True, **changes}


def configure_timer(store, messages=None, *, now=1000, **changes):
    store.configure("100", True, {**DEFAULTS, "auto_messages": messages or [auto_message()], **changes}, now=now)
    store.status("100", "connected")
    store.save_account("999", "bot", "yami", "Yami", "encrypted")


@pytest.mark.parametrize("patch", [
    {"id": "bad:*"}, {"id": []}, {"enabled": 1}, {"live_only": "yes"},
    {"interval_minutes": 0}, {"interval_minutes": 1441}, {"interval_minutes": True},
    {"interval_minutes": 1.5}, {"min_messages": -1}, {"min_messages": 1001},
    {"name": " "}, {"name": "x" * 61}, {"text": " "}, {"text": "\u200b"},
    {"text": "x" * 501}, {"text": "line\nline"}, {"text": "line\x00line"}, {"extra": True},
])
def test_auto_messages_validate_fields(patch):
    with pytest.raises(ValueError):
        settings({**DEFAULTS, "auto_messages": [auto_message(**patch)]})


def test_auto_messages_validate_collection_and_keep_literal_text():
    for value in ("text", [None], [auto_message()] * 2, [auto_message(id=str(i)) for i in range(21)]):
        with pytest.raises(ValueError):
            settings({**DEFAULTS, "auto_messages": value})
    message = auto_message(text=" <b>Hi</b> {channel} " + "🌙" * 460)
    assert settings({**DEFAULTS, "auto_messages": [message]})["auto_messages"][0]["text"] == message["text"].strip()


@pytest.mark.asyncio
async def test_timer_api_owner_csrf_roundtrip_and_legacy_client_preservation(panel):
    panel, client = panel
    payload = {"enabled": False, "settings": {**DEFAULTS, "auto_messages": [auto_message()]}}
    assert (await client.post("/api/twitch/settings", json=payload)).status == 401
    login_session(panel, client)
    assert (await client.post("/api/twitch/settings", json=payload)).status == 403
    headers = {"X-CSRF-Token": "csrf"}
    response = await client.post("/api/twitch/settings", json=payload, headers=headers)
    assert response.status == 200
    assert (await response.json())["channel"]["settings"]["auto_messages"] == [auto_message()]
    assert panel.store.channel("200")["settings"]["auto_messages"] == []
    del payload["settings"]["auto_messages"]
    response = await client.post("/api/twitch/settings", json=payload, headers=headers)
    assert response.status == 200
    assert panel.store.channel("100")["settings"]["auto_messages"] == [auto_message()]
    payload["settings"]["auto_messages"] = [auto_message(text="x" * 501)]
    assert (await client.post("/api/twitch/settings", json=payload, headers=headers)).status == 400
    assert panel.store.channel("100")["settings"]["auto_messages"] == [auto_message()]


@pytest.mark.asyncio
async def test_timer_activity_deduplicates_excludes_bot_filtered_and_other_channel(store, configured):
    configure_timer(store, [auto_message(min_messages=2)], automod_enabled=True, block_links=True)
    service = Service(store.conn, "https://yamikun.eu")
    service.api = AsyncMock(return_value={"data": [{"user_id": "100"}]})
    run(service.engine, "hallo", now=1001)
    run(service.engine, "hallo", now=1002)  # same event, counted only once
    run(service.engine, "bot", uid="999", now=1003, message_id="bot")
    run(service.engine, "https://example.com", now=1004, message_id="blocked")
    run(service.engine, "other", cid="200", now=1005, message_id="other")
    assert store.conn.execute("SELECT message_count FROM twitch_chat_timers").fetchone()[0] == 1
    await service.schedule_auto_messages(1061)
    service.api.assert_not_awaited()  # activity gate avoids unnecessary live queries
    run(service.engine, "nochmal hallo", now=1062, message_id="second")
    restarted = Service(store.conn, "https://yamikun.eu")
    restarted.api = service.api
    await restarted.schedule_auto_messages(1062)
    rows = store.conn.execute("SELECT * FROM twitch_chat_events WHERE id LIKE 'auto:%'").fetchall()
    assert len(rows) == 1 and rows[0]["processed"] == 1
    assert json.loads(rows[0]["result"])["reply"] == auto_message()["text"]
    assert store.conn.execute("SELECT message_count,next_due FROM twitch_chat_timers").fetchone()[:] == (0, 1122)
    await Service(store.conn, "https://yamikun.eu").schedule_auto_messages(1063)
    assert store.conn.execute("SELECT COUNT(*) FROM twitch_chat_events WHERE id LIKE 'auto:%'").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_timers_live_offline_failure_disabled_and_spacing(store, configured):
    configure_timer(store, [auto_message(id="a"), auto_message(id="b", live_only=False)])
    service = Service(store.conn, "https://yamikun.eu")
    service.api = AsyncMock(return_value={"data": []})
    await service.schedule_auto_messages(1059)
    service.api.assert_not_awaited()
    await service.schedule_auto_messages(1060)
    row = store.conn.execute("SELECT result FROM twitch_chat_events").fetchone()
    assert json.loads(row[0])["auto_message"]["id"] == "b"
    await service.schedule_auto_messages(1075)
    assert store.conn.execute("SELECT COUNT(*) FROM twitch_chat_events").fetchone()[0] == 1
    service._live.clear()
    service.api.return_value = {"data": [{"user_id": "100"}]}
    await service.schedule_auto_messages(1120)
    assert store.conn.execute("SELECT COUNT(*) FROM twitch_chat_events").fetchone()[0] == 2
    service._live.clear()
    service.api.side_effect = TwitchError("twitch_503", 503)
    await service.schedule_auto_messages(1180)
    assert store.conn.execute("SELECT COUNT(*) FROM twitch_chat_events").fetchone()[0] == 3
    assert json.loads(store.conn.execute("SELECT result FROM twitch_chat_events ORDER BY created DESC LIMIT 1").fetchone()[0])["auto_message"]["id"] == "b"
    assert store.dashboard("100")["diagnostics"]["live_error"]
    store.configure("100", False, store.channel("100")["settings"], now=1180)
    await service.schedule_auto_messages(1300)
    assert store.conn.execute("SELECT COUNT(*) FROM twitch_chat_timers").fetchone()[0] == 0
    assert store.conn.execute("SELECT COUNT(*) FROM twitch_chat_events WHERE delivered=0").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_timer_edit_cancels_pending_and_unrelated_settings_keep_progress(store, configured):
    configure_timer(store)
    service = Service(store.conn, "https://yamikun.eu")
    service.api = AsyncMock(return_value={"data": [{"user_id": "100"}]})
    run(service.engine, "hi", now=1010)
    configure_timer(store, now=1020, prefix="?")
    assert store.conn.execute("SELECT next_due,message_count FROM twitch_chat_timers").fetchone()[:] == (1060, 1)
    await service.schedule_auto_messages(1060)
    configure_timer(store, [auto_message(text="Neuer Text")], now=1061)
    row = store.conn.execute("SELECT delivered FROM twitch_chat_events WHERE id LIKE 'auto:%'").fetchone()
    assert row[0] == 1
    assert store.conn.execute("SELECT next_due,message_count FROM twitch_chat_timers").fetchone()[:] == (1121, 0)
    store.configure("100", True, {**DEFAULTS, "auto_messages": []}, now=1062)
    assert store.conn.execute("SELECT COUNT(*) FROM twitch_chat_timers").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_timer_settings_changed_during_live_request_are_rechecked(store, configured):
    configure_timer(store)
    service = Service(store.conn, "https://yamikun.eu")
    async def api(*args, **kwargs):
        store.configure("100", False, store.channel("100")["settings"], now=1060)
        return {"data": [{"user_id": "100"}]}
    service.api = api
    await service.schedule_auto_messages(1060)
    assert store.conn.execute("SELECT COUNT(*) FROM twitch_chat_events").fetchone()[0] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_automatic_delivery_uses_bot_and_rechecks_settings_after_throttle(store, configured, monkeypatch, cancel):
    now = time.time()
    # A literal "moderate" in a user field must not route this to the AutoMod worker.
    message = auto_message(id="moderate", name="moderate", text="moderate", live_only=False)
    configure_timer(store, [message], now=now - 61)
    service = Service(store.conn, "https://yamikun.eu")
    await service.schedule_auto_messages(now)
    service.api = AsyncMock(return_value={"data": [{"is_sent": True}]})
    real_sleep = asyncio.sleep
    async def throttle(delay):
        if cancel and delay == 0:
            store.configure("100", True, {**DEFAULTS, "auto_messages": []})
        await real_sleep(0)
    monkeypatch.setattr("twitch_chat.service.asyncio.sleep", throttle)
    task = asyncio.create_task(service.deliver(False))
    try:
        for _ in range(20):
            await real_sleep(0)
            if store.conn.execute("SELECT delivered FROM twitch_chat_events").fetchone()[0]:
                break
        assert store.conn.execute("SELECT delivered FROM twitch_chat_events").fetchone()[0] == 1
        if cancel:
            service.api.assert_not_awaited()
        else:
            service.api.assert_awaited_once_with("POST", "chat/messages", json={
                "broadcaster_id": "100", "sender_id": "999", "message": message["text"], "for_source_only": True})
            assert not Store(store.conn).auto_message_can_send("100", now + 59)
            assert Store(store.conn).auto_message_can_send("100", now + 61)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", ["offline", "recent_send", "revoked", "stale"])
async def test_queued_auto_message_rechecks_delivery_conditions(store, configured, monkeypatch, condition):
    now = time.time()
    message = auto_message(live_only=condition == "offline")
    configure_timer(store, [message], now=now - 61)
    store.queue_auto_message("100", message, now - 121 if condition == "stale" else now)
    if condition == "recent_send":
        store.auto_message_sent("100", now - 10)
    if condition == "revoked":
        store.forget_account("999", "bot")
    service = Service(store.conn, "https://yamikun.eu")
    service.api = AsyncMock(return_value={"data": []})
    real_sleep = asyncio.sleep
    async def fast_sleep(delay):
        await real_sleep(0)
    monkeypatch.setattr("twitch_chat.service.asyncio.sleep", fast_sleep)
    task = asyncio.create_task(service.deliver(False))
    try:
        for _ in range(20):
            await real_sleep(0)
            if store.conn.execute("SELECT delivered FROM twitch_chat_events").fetchone()[0]:
                break
        assert store.conn.execute("SELECT delivered FROM twitch_chat_events").fetchone()[0] == 1
        assert all(call.args[1] != "chat/messages" for call in service.api.await_args_list)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_api_auth_csrf_owner_isolation_and_secret_redaction(panel):
    panel, client = panel
    assert (await client.post("/api/twitch/settings", json={})).status == 401
    login_session(panel, client)
    assert (await client.post("/api/twitch/settings", json={})).status == 403
    response = await client.get("/api/twitch/me")
    data = await response.json()
    assert data["channel"]["user_id"] == "100"
    assert "credentials" not in await response.text()
    response = await client.post("/api/twitch/settings", headers={"X-CSRF-Token": "csrf"}, json={"enabled": False, "settings": {**DEFAULTS, "prefix": "?"}, "channel_id": "200"})
    assert response.status == 400
    response = await client.post("/api/twitch/settings", headers={"X-CSRF-Token": "csrf"}, json={"enabled": False, "settings": {**DEFAULTS, "prefix": "?"}})
    assert response.status == 200
    assert panel.store.channel("100")["settings"]["prefix"] == "?"
    assert panel.store.channel("200")["settings"]["prefix"] == "!"


@pytest.mark.asyncio
@pytest.mark.parametrize("uid,expected", [(None, False), ("100", False), ("999", True)])
async def test_bot_setup_is_discoverable_only_for_the_configured_account(panel, uid, expected):
    panel, client = panel
    # The decision must use the verified Twitch ID, never a supplied login/query.
    if uid:
        panel.store.save_account(uid, "channel", "same_login", "Same name", "encrypted")
        login_session(panel, client, uid)
    response = await client.get("/api/twitch/me?user_id=999&bot=1")
    data = await response.json()
    assert data["can_setup_bot"] is expected
    assert data["bot_ready"] is False
    assert panel.store.account("999", "bot") is None


@pytest.mark.asyncio
async def test_signed_webhooks_reject_tampering_age_duplicates_and_shared_chat(panel):
    panel, client = panel
    body, headers = signed(panel, kind="webhook_callback_verification")
    response = await client.post("/twitch/eventsub", data=body, headers=headers)
    assert response.status == 200
    assert await response.text() == "challenge-text"
    assert (await client.post("/twitch/eventsub", data=body + b" ", headers=headers)).status == 403
    body, headers = signed(panel, stamp="2020-01-01T00:00:00Z")
    assert (await client.post("/twitch/eventsub", data=body, headers=headers)).status == 403
    body, headers = signed(panel)
    for _ in range(2):
        assert (await client.post("/twitch/eventsub", data=body, headers=headers)).status == 204
    assert panel.store.conn.execute("SELECT COUNT(*) FROM twitch_chat_events").fetchone()[0] == 1
    body, headers = signed(panel, event(message_id="shared", source_broadcaster_user_id="200"))
    assert (await client.post("/twitch/eventsub", data=body, headers=headers)).status == 204
    assert panel.store.conn.execute("SELECT COUNT(*) FROM twitch_chat_events").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_oauth_state_is_one_time_cookie_bound_and_sessions_rotate(panel):
    panel, client = panel
    panel.service.http = object()  # Network calls are mocked below.
    panel.service.authorize = AsyncMock(return_value="100")
    res = await client.get("/twitch/login", allow_redirects=False)
    state = parse_qs(urlsplit(res.headers["Location"]).query)["state"][0]
    assert res.cookies[STATE]["httponly"]
    assert state not in str(panel.store.conn.execute("SELECT * FROM twitch_chat_oauth").fetchone()[:])
    res = await client.get("/twitch/callback?code=code&state=wrong", allow_redirects=False)
    assert res.headers["Location"] == "/twitch?error=state"
    client.session.cookie_jar.update_cookies({STATE: state})
    res = await client.get("/twitch/callback?code=code&state=" + state, allow_redirects=False)
    assert res.headers["Location"] == "/twitch"
    assert res.cookies[SESSION]["httponly"]
    token = res.cookies[SESSION].value
    assert not panel.store.conn.execute("SELECT 1 FROM twitch_chat_sessions WHERE token_hash=?", (token,)).fetchone()
    client.session.cookie_jar.update_cookies({STATE: state})
    res = await client.get("/twitch/callback?code=code&state=" + state, allow_redirects=False)
    assert res.headers["Location"] == "/twitch?error=state"
    assert panel.service.authorize.await_count == 1


@pytest.mark.asyncio
async def test_optional_link_requires_both_sessions_is_unique_and_blocks_open_games(panel):
    panel, client = panel
    login_session(panel, client, "10")
    panel.store.save_account("10", "channel", "luna", "Luna", "enc")
    headers = {"X-CSRF-Token": "csrf"}
    assert (await client.post("/api/twitch/discord-link", json={"linked": True}, headers=headers)).status == 401
    panel.panel._session = lambda r: {"user_id": 123, "username": "Discord Luna"}
    assert (await client.post("/api/twitch/discord-link", json={"linked": True}, headers=headers)).status == 200
    assert (await client.post("/api/twitch/discord-link", json={"linked": True}, headers=headers)).status == 200
    with panel.store.conn:
        panel.store.conn.execute("INSERT INTO levels(guild_id,user_id,coins) VALUES(0,123,4321)")
    me = await (await client.get("/api/twitch/me")).json()
    assert me["discord_link"]["coins"] == 4321
    panel.panel._session = lambda r: {"user_id": 456, "username": "Other"}
    assert (await client.post("/api/twitch/discord-link", json={"linked": True}, headers=headers)).status == 409
    with panel.store.conn:
        panel.service.engine.touch("100", "10", "luna")
        panel.service.engine.money("100", "10", 500)
        panel.service.engine.save_game("100", "10", {"hands": [{"cards": [["10", "S"], ["Q", "S"]], "bet": 50, "stood": False}], "dealer": [["10", "H"], ["7", "H"]], "deck": [], "active": 0}, time.time())
    assert (await client.post("/api/twitch/discord-link", json={"linked": False}, headers=headers)).status == 409


@pytest.mark.asyncio
async def test_tokens_encrypt_refresh_validate_and_revoke(store, configured):
    service = Service(store.conn, "https://yamikun.eu")
    old = {"access_token": "old-secret", "refresh_token": "refresh-secret", "expires_at": 0}
    store.save_account("100", "channel", "channel100", "Channel", service.encrypt(old))
    assert "old-secret" not in store.account("100")["credentials"]
    service.request = AsyncMock(return_value={"access_token": "new-secret", "refresh_token": "new-refresh", "expires_in": 4000})
    service.validate = AsyncMock(return_value={"client_id": "client", "user_id": "100", "scopes": list(SCOPES["channel"])})
    assert await service.user_token("100") == "new-secret"
    assert await service.user_token("100") == "new-secret"
    assert service.request.await_count == 1
    assert service.validate.await_count == 1
    assert service.decrypt(store.account("100")["credentials"])["refresh_token"] == "new-refresh"
    service._validated.clear()
    service.validate.side_effect = TwitchError("twitch_401", 401)
    with pytest.raises(TwitchError):
        await service.user_token("100")
    assert store.account("100") is None
    assert not store.channel("100")["enabled"]


@pytest.mark.asyncio
async def test_bot_oauth_rejects_wrong_identity(store, configured):
    service = Service(store.conn, "https://yamikun.eu")
    service.request = AsyncMock(return_value={"access_token": "access", "refresh_token": "refresh", "expires_in": 4000})
    service.validate = AsyncMock(return_value={"client_id": "client", "user_id": "100", "scopes": list(SCOPES["bot"])})
    with pytest.raises(TwitchError, match="wrong_bot_account"):
        await service.authorize("code", "bot")
    assert not store.account("100", "bot")


@pytest.mark.asyncio
async def test_reconcile_paginates_and_never_deletes_other_integrations(store, configured):
    service = Service(store.conn, "https://yamikun.eu")
    store.save_account("999", "bot", "yami", "Yami", "encrypted")
    service.user_token = AsyncMock(return_value="token")
    callback = "https://yamikun.eu/twitch/eventsub"
    subscriptions = [
        {"id": "keep", "type": "channel.chat.message", "status": "enabled", "condition": {"broadcaster_user_id": "100", "user_id": "999"}, "transport": {"callback": callback}},
        {"id": "other", "type": "stream.online", "condition": {}, "transport": {"callback": "https://elsewhere.test"}},
        {"id": "remove", "type": "channel.chat.message", "status": "enabled", "condition": {"broadcaster_user_id": "300", "user_id": "999"}, "transport": {"callback": callback}},
    ]
    calls = []
    async def api(method, path, **kwargs):
        calls.append((method, kwargs))
        if method == "GET":
            return {"data": subscriptions[1:], "pagination": {}} if kwargs["params"].get("after") else {"data": subscriptions[:1], "pagination": {"cursor": "page2"}}
        return {}
    service.api = api
    await service.reconcile()
    assert [kw["params"]["id"] for method, kw in calls if method == "DELETE"] == ["remove"]
    assert [kw["json"]["condition"]["broadcaster_user_id"] for method, kw in calls if method == "POST"] == ["200"]
    assert store.channel("100")["status"] == "connected"


@pytest.mark.asyncio
@pytest.mark.parametrize("duration", [0, 60])
async def test_delivery_moderates_only_the_target_and_records_success(store, configured, duration):
    service = Service(store.conn, "https://yamikun.eu")
    store.configure("100", True, {**DEFAULTS, "automod_enabled": True, "block_links": True, "timeout_seconds": duration})
    run(service.engine, "https://example.com", now=time.time())
    store.delivery_status("100", "moderation", "Previous moderation error")
    store.delivery_status("100", "send", "Independent send error")
    called = asyncio.Event()
    calls = []
    async def api(method, path, **kwargs):
        calls.append((method, path, kwargs))
        called.set()
        return {}
    service.api = api
    task = asyncio.create_task(service.deliver(True))
    try:
        await asyncio.wait_for(called.wait(), 1)
        await asyncio.sleep(0)
        method, path, kwargs = calls[0]
        assert kwargs["account"] == ("100", "channel")
        assert kwargs["params"]["broadcaster_id"] == "100"
        if duration:
            assert (method, path) == ("POST", "moderation/bans")
            assert kwargs["json"]["data"]["duration"] == 60
            assert kwargs["json"]["data"]["user_id"] == "10"
        else:
            assert (method, path) == ("DELETE", "moderation/chat")
            assert kwargs["params"]["message_id"] == "msg-1"
        assert store.conn.execute("SELECT outcome FROM twitch_chat_modlog").fetchone()[0] == "ok"
        assert store.conn.execute("SELECT delivered,payload FROM twitch_chat_events").fetchone()[:] == (1, "{}")
        assert store.dashboard("100")["channel"]["error"] == "Independent send error"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_send_uses_bot_identity_and_source_channel_only(store, configured):
    service = Service(store.conn, "https://yamikun.eu")
    run(service.engine, now=time.time())
    store.delivery_status("100", "send", "Previous send error")
    called = asyncio.Event()
    calls = []
    async def api(method, path, **kwargs):
        calls.append((method, path, kwargs))
        called.set()
        return {"data": [{"is_sent": True}]}
    service.api = api
    task = asyncio.create_task(service.deliver(False))
    try:
        await asyncio.wait_for(called.wait(), 1)
        await asyncio.sleep(0)
        assert calls[0][0:2] == ("POST", "chat/messages")
        assert store.dashboard("100")["channel"]["error"] == ""
        body = calls[0][2]["json"]
        assert body["sender_id"] == "999"
        assert body["broadcaster_id"] == "100"
        assert body["for_source_only"] is True
        assert len(body["message"]) <= 500
        assert store.conn.execute("SELECT delivered,payload FROM twitch_chat_events").fetchone()[:] == (1, "{}")
        assert service.engine.balance("100", "10") == 500
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,message,reason", [
    (401, "The sender must have authorized the app with the user:write:chat and user:bot scopes.", "bot_authorization_missing"),
    (401, "The broadcaster must have authorized the app with the channel:bot scope.", "channel_authorization_missing"),
    (403, "Authorization rejected: private-response-content", ""),
    (400, None, ""),
])
async def test_http_errors_keep_status_and_safe_permission_reason(store, configured, status, message, reason):
    service = Service(store.conn, "https://yamikun.eu")
    async def upstream(request):
        if message is None:
            return web.Response(text="<html>private-response-content</html>", status=status)
        return web.json_response({"message": message, "access_token": "private-response-content"}, status=status)
    app = web.Application()
    app.router.add_post("/chat/messages", upstream)
    async with TestServer(app) as server, aiohttp.ClientSession() as session:
        service.http = session
        with pytest.raises(TwitchError) as failure:
            await service.request("POST", server.make_url("/chat/messages"))
    assert failure.value.status == status
    assert failure.value.reason == reason
    assert f"twitch_{status}" in failure.value.diagnostic
    assert "private-response-content" not in str(vars(failure.value))


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome,diagnostic,hint", [
    ({"data": [{"is_sent": False, "drop_reason": {"code": "automod_held", "message": "private-response-content"}}]}, "reason=automod_held", "Moderationswarteschlange"),
    ({"data": [{"is_sent": False, "drop_reason": {"code": "msg_verified_email"}}]}, "reason=msg_verified_email", "E-Mail-Adresse"),
    ({"data": [{"is_sent": False, "drop_reason": {"code": "msg_requires_verified_phone_number"}}]}, "reason=msg_requires_verified_phone_number", "Telefonnummer"),
    ({"data": [{"is_sent": False, "drop_reason": {"code": "\nprivate-response-content"}}]}, "chat_message_dropped", "Fehlercode"),
    ({"data": []}, "chat_response_invalid", "Fehlercode"),
    (TwitchError("twitch_401", 401, reason="bot_authorization_missing"), "status=401", "Bot-Freigabe"),
    (TwitchError("twitch_403", 403), "status=403", "Chat-Beschränkungen"),
    (asyncio.TimeoutError("private-response-content"), "TimeoutError", "Verbindungsfehler"),
])
async def test_failed_delivery_reports_reason_without_repeating_command(store, configured, caplog, outcome, diagnostic, hint):
    service = Service(store.conn, "https://yamikun.eu")
    run(service.engine, now=time.time())
    called = asyncio.Event()
    async def api(*args, **kwargs):
        called.set()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    service.api = AsyncMock(side_effect=api)
    task = asyncio.create_task(service.deliver(False))
    try:
        await asyncio.wait_for(called.wait(), 1)
        await asyncio.sleep(0)
        assert service.api.await_count == 1
        assert diagnostic in caplog.text
        assert "action=send" in caplog.text and "channel=100" in caplog.text
        assert "private-response-content" not in caplog.text
        dashboard = store.dashboard("100")["channel"]
        assert dashboard["status"] == "error" and hint in dashboard["error"]
        assert "private-response-content" not in dashboard["error"]
        assert store.conn.execute("SELECT delivered,attempts,payload FROM twitch_chat_events").fetchone()[:] == (1, 1, "{}")
        assert service.engine.balance("100", "10") == 500
        assert service.engine.balance("200", "10") == 0
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_reconcile_does_not_clear_delivery_errors_and_errors_survive_restart(store, configured):
    service = Service(store.conn, "https://yamikun.eu")
    store.save_account("999", "bot", "yami", "Yami", "encrypted")
    store.delivery_status("100", "send", "Chat reply rejected")
    store.delivery_status("100", "moderation", "Moderation rejected")
    service.user_token = AsyncMock(return_value="token")
    service.api = AsyncMock(return_value={"data": [
        {"id": cid, "type": "channel.chat.message", "status": "enabled",
         "condition": {"broadcaster_user_id": cid, "user_id": "999"},
         "transport": {"callback": "https://yamikun.eu/twitch/eventsub"}}
        for cid in ("100", "200")
    ]})
    await service.reconcile()
    restarted = Store(store.conn)
    assert restarted.channel("100")["status"] == "connected"
    assert restarted.dashboard("100")["channel"]["status"] == "error"
    assert "Chat reply rejected" in restarted.dashboard("100")["channel"]["error"]
    assert "Moderation rejected" in restarted.dashboard("100")["channel"]["error"]
    assert restarted.dashboard("200")["channel"]["error"] == ""
    restarted.delivery_status("100", "send")
    assert restarted.dashboard("100")["channel"]["error"] == "Moderation rejected"
    restarted.delivery_status("100", "moderation")
    assert restarted.dashboard("100")["channel"]["status"] == "connected"
    assert restarted.dashboard("100")["channel"]["error"] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500])
async def test_retry_sends_committed_reply_and_clears_delivery_error(store, configured, monkeypatch, status):
    service = Service(store.conn, "https://yamikun.eu")
    clock = [time.time()]
    monkeypatch.setattr("twitch_chat.service.time.time", lambda: clock[0])
    result = run(service.engine, now=time.time())
    real_sleep = asyncio.sleep
    sent_at = []
    async def fast_sleep(delay):
        clock[0] += delay
        await real_sleep(0)
    monkeypatch.setattr("twitch_chat.service.asyncio.sleep", fast_sleep)
    retried = asyncio.Event()
    attempts = 0
    async def api(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        sent_at.append(clock[0])
        assert kwargs["json"]["message"] == result["reply"]
        if attempts == 1:
            raise TwitchError(f"twitch_{status}", status, retry_after=37 if status == 429 else 0)
        assert "fehlgeschlagen" in store.dashboard("100")["channel"]["error"]
        retried.set()
        return {"data": [{"is_sent": True}]}
    service.api = api
    task = asyncio.create_task(service.deliver(False))
    try:
        await asyncio.wait_for(retried.wait(), 1)
        await real_sleep(0)
        assert attempts == 2
        assert sent_at[1] - sent_at[0] >= (37 if status == 429 else 5)
        assert store.dashboard("100")["channel"]["error"] == ""
        assert service.engine.balance("100", "10") == 500
        assert store.conn.execute("SELECT delivered,attempts FROM twitch_chat_events").fetchone()[:] == (1, 1)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("reset,expected", [("1042", 42), ("999", 0), ("invalid", 0), ("nan", 0), ("inf", 0), (None, 0)])
async def test_http_rate_limit_preserves_reset_delay(store, configured, monkeypatch, reset, expected):
    service = Service(store.conn, "https://yamikun.eu")
    monkeypatch.setattr("twitch_chat.service.time.time", lambda: 1000)

    async def upstream(request):
        return web.json_response({"message": "Too Many Requests"}, status=429,
                                 headers={"Ratelimit-Reset": reset} if reset is not None else {})

    app = web.Application()
    app.router.add_post("/chat/messages", upstream)
    async with TestServer(app) as server, aiohttp.ClientSession() as session:
        service.http = session
        with pytest.raises(TwitchError) as failure:
            await service.request("POST", server.make_url("/chat/messages"))
    assert failure.value.status == 429
    assert failure.value.retry_after == expected


def custom_command(**patch):
    return {"id": "discord", "name": "discord", "response": "Hallo {user}, willkommen bei {channel}! {target}: {args}",
            "enabled": True, "aliases": ["dc"], "user_level": "everyone", "cooldown": 10, "user_cooldown": 30, **patch}


@pytest.mark.parametrize("patch", [
    {"name": "daily"}, {"name": "balance"}, {"name": "!test"}, {"name": "ümlaut"},
    {"aliases": ["coins"]}, {"aliases": ["dc", "DC"]}, {"aliases": ["discord"]}, {"aliases": "dc"},
    {"response": ""}, {"response": "x" * 501}, {"response": "one\ntwo"}, {"response": "\u200b"},
    {"user_level": "admin"}, {"enabled": 1}, {"cooldown": True}, {"cooldown": -1},
    {"user_cooldown": 86401}, {"id": "bad:*"}, {"extra": "no"},
])
def test_custom_commands_strict_validation(patch):
    with pytest.raises(ValueError):
        settings({**DEFAULTS, "custom_commands": [custom_command(**patch)]})


def test_custom_commands_validate_collection_and_case():
    for value in (None, {}, [None], [custom_command()] * 2,
                  [custom_command(id=str(i), name=f"command{i}", aliases=[]) for i in range(51)],
                  [custom_command(), custom_command(id="two", name="DC", aliases=[])]):
        with pytest.raises(ValueError):
            settings({**DEFAULTS, "custom_commands": value})
    result = settings({**DEFAULTS, "custom_commands": [custom_command(name=" Discord ", aliases=["DC"])]})
    assert result["custom_commands"][0]["name"] == "discord"
    assert result["custom_commands"][0]["aliases"] == ["dc"]


def test_custom_cooldowns_aliases_restarts_and_builtin_independence(store):
    store.configure("100", True, {**DEFAULTS, "prefix": "?", "custom_commands": [custom_command()]})
    engine = Engine(store, "999")
    first = run(engine, "?DC @neko {user}", now=1000)
    assert first["reply"] == "Hallo @luna, willkommen bei channel100! @neko: @neko {user}"
    assert run(Engine(Store(store.conn), "999"), "?DC @neko {user}", now=1001) == first
    assert run(engine, "?discord", uid="20", now=1005, message_id="global") == {}
    assert run(engine, "?discord", now=1011, message_id="personal") == {}
    assert "reply" in run(engine, "?dc", uid="20", now=1011, message_id="other")
    assert "reply" in run(engine, "?daily", now=1012, message_id="builtin")
    assert "reply" in run(Engine(Store(store.conn), "999"), "?dc", now=1030, message_id="restart")
    assert run(engine, "?discord", cid="200", now=1050, message_id="other-channel") == {}
    assert "?discord" in run(engine, "?help", now=1050, message_id="help")["reply"]


@pytest.mark.parametrize("level,uid,badges,allowed", [
    ("everyone", "10", [], True), ("subscriber", "10", [], False),
    ("subscriber", "10", ["founder"], True), ("subscriber", "10", ["vip"], True),
    ("vip", "10", ["subscriber"], False), ("vip", "10", ["vip"], True),
    ("moderator", "10", ["vip"], False), ("moderator", "10", ["moderator"], True),
    ("broadcaster", "10", ["moderator"], False), ("broadcaster", "100", [], True),
])
def test_custom_command_permission_levels(store, level, uid, badges, allowed):
    store.configure("100", True, {**DEFAULTS, "custom_commands": [custom_command(user_level=level)]})
    result = run(Engine(store, "999"), "!discord", uid=uid, badges=[{"set_id": badge} for badge in badges])
    assert bool(result.get("reply")) == allowed


def test_custom_edits_cancel_queued_replies_and_automod_still_runs_first(store):
    command = custom_command(response="x" * 499 + "{args}")
    # Use valid template length but a long expansion.
    command["response"] = "{args}" * 50
    store.configure("100", True, {**DEFAULTS, "custom_commands": [command]})
    engine = Engine(store, "999")
    assert len(run(engine, "!discord " + "x" * 100)["reply"]) == 500
    store.configure("100", True, {**DEFAULTS, "custom_commands": [custom_command(enabled=False)]})
    assert store.conn.execute("SELECT delivered,outcome FROM twitch_chat_events").fetchone()[:] == (1, "cancelled")
    assert run(engine, "!discord", now=1050, message_id="disabled") == {}
    store.configure("100", True, {**DEFAULTS, "automod_enabled": True, "block_links": True, "custom_commands": [custom_command()]})
    assert "moderate" in run(engine, "!discord https://example.com", now=1060, message_id="moderated")
    assert store.conn.execute("SELECT COUNT(*) FROM twitch_chat_command_cooldowns").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_custom_commands_api_roundtrip_legacy_tabs_and_webhook_delivery(panel):
    panel, client = panel
    login_session(panel, client)
    panel.store.save_account("999", "bot", "yami", "Yami", "encrypted")
    cfg = {**DEFAULTS, "custom_commands": [custom_command()]}
    headers = {"X-CSRF-Token": "csrf"}
    assert (await client.post("/api/twitch/settings", json={"enabled": True, "settings": cfg})).status == 403
    response = await client.post("/api/twitch/settings", json={"enabled": True, "settings": cfg}, headers=headers)
    assert response.status == 200
    assert (await response.json())["channel"]["settings"]["custom_commands"] == cfg["custom_commands"]
    legacy = {k: v for k, v in DEFAULTS.items() if k not in {"custom_commands", "auto_messages"}}
    assert (await client.post("/api/twitch/settings", json={"enabled": True, "settings": legacy}, headers=headers)).status == 200
    assert panel.store.channel("100")["settings"]["custom_commands"] == cfg["custom_commands"]
    assert panel.store.channel("200")["settings"]["custom_commands"] == []
    raw, signature = signed(panel, event("!dc @neko"))
    for _ in range(2):
        assert (await client.post("/twitch/eventsub", data=raw, headers=signature)).status == 204
    panel.service.api = AsyncMock(return_value={"data": [{"is_sent": True}]})
    tasks = [asyncio.create_task(panel.service.process()), asyncio.create_task(panel.service.deliver(False))]
    try:
        for _ in range(50):
            await asyncio.sleep(.01)
            if panel.store.conn.execute("SELECT delivered FROM twitch_chat_events").fetchone()[0]:
                break
        panel.service.api.assert_awaited_once()
        assert "@neko" in panel.service.api.call_args.kwargs["json"]["message"]
        fresh = await (await client.get("/api/twitch/me")).json()
        assert fresh["diagnostics"]["last_received"]
        assert fresh["diagnostics"]["last_sent"]
        assert fresh["diagnostics"]["pending"] == 0
        assert "daily" in fresh["reserved_command_names"]
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def test_fair_queue_prioritizes_commands_and_keeps_channel_order_after_restart(store):
    engine = Engine(store, "999")
    for i in range(3):
        run(engine, "!coins", now=1000 + i * 5, message_id=f"a{i}")
    run(engine, "!coins", cid="200", now=1015, message_id="b")
    store.queue_auto_message("200", auto_message(live_only=False), 900)
    first = store.next_delivery(False, 1020)
    assert first["id"] == "100:a0"
    store.dispatch_attempt("100", False, 1020)
    store.finish(first["id"], "sent")
    restarted = Store(store.conn)
    assert restarted.next_delivery(False, 1021) is None  # global throttle survives restart
    second = restarted.next_delivery(False, 1022)
    assert second["id"] == "200:b"
    restarted.dispatch_attempt("200", False, 1022)
    restarted.finish(second["id"], "sent")
    assert restarted.next_delivery(False, 1024)["id"] == "100:a1"


def test_overload_skips_games_but_still_grants_automatic_daily(store):
    engine = Engine(store, "999")
    run(engine, "!daily", now=1000)
    for i in range(9):
        run(engine, "!coins", uid=str(20 + i), now=1001, message_id=str(i))
    assert not store.reply_capacity("100", 1002)
    assert run(engine, "!slots 50", now=1010, message_id="overload") == {}
    assert engine.balance("100", "10") == 500
    assert run(engine, "!daily", uid="40", now=1010, message_id="daily-overload") == {}
    assert engine.balance("100", "40") == 500
    assert store.conn.execute("SELECT daily_at FROM twitch_chat_wallets WHERE user_id='40'").fetchone()[0] == 1010
    assert store.conn.execute("SELECT outcome FROM twitch_chat_events WHERE id='100:overload'").fetchone()[0] == "overloaded"
    assert "reply" in run(engine, "!daily", cid="200", now=1010, message_id="room-in-other")
    store.finish("100:msg-1", "sent")
    assert "reply" in run(engine, "!daily", uid="40", now=1011, message_id="after-space")


def test_expiry_and_pause_finalize_moderation_logs_and_diagnostics(store, monkeypatch):
    now = time.time()
    store.configure("100", True, {**DEFAULTS, "automod_enabled": True, "block_links": True})
    engine = Engine(store, "999")
    run(engine, "https://example.com", now=now - 121)
    store.expire_deliveries(now)
    assert store.conn.execute("SELECT outcome FROM twitch_chat_modlog").fetchone()[0] == "expired"
    run(engine, "https://example.com", now=now, message_id="new")
    store.configure("100", False, store.channel("100")["settings"])
    assert [r[0] for r in store.conn.execute("SELECT outcome FROM twitch_chat_modlog ORDER BY id")] == ["expired", "cancelled"]
    diagnostic = Store(store.conn).dashboard("100")["diagnostics"]
    assert diagnostic["expired_24h"] == 1
    assert diagnostic["pending"] == 0


@pytest.mark.asyncio
async def test_retry_for_one_channel_does_not_block_another(store, configured, monkeypatch):
    service = Service(store.conn, "https://yamikun.eu")
    clock = [time.time()]
    monkeypatch.setattr("twitch_chat.service.time.time", lambda: clock[0])
    run(service.engine, now=clock[0])
    run(service.engine, cid="200", now=clock[0], message_id="second")
    real_sleep = asyncio.sleep
    async def tick(delay):
        clock[0] += delay
        await real_sleep(0)
    monkeypatch.setattr("twitch_chat.service.asyncio.sleep", tick)
    calls = []
    async def api(*args, **kwargs):
        cid = kwargs["json"]["broadcaster_id"]
        calls.append((cid, clock[0]))
        if len(calls) == 1:
            raise TwitchError("twitch_503", 503)
        return {"data": [{"is_sent": True}]}
    service.api = api
    task = asyncio.create_task(service.deliver(False))
    try:
        for _ in range(100):
            await real_sleep(0)
            if len(calls) >= 3:
                break
        assert [cid for cid, _ in calls] == ["100", "200", "100"]
        assert calls[1][1] - calls[0][1] < 5
        assert calls[2][1] - calls[0][1] >= 5
        assert service.engine.balance("100", "10") == 500
        assert store.conn.execute("SELECT COUNT(*) FROM twitch_chat_events WHERE outcome='sent'").fetchone()[0] == 2
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_event_table_migration_keeps_pending_messages(tmp_path):
    db = Database(str(tmp_path / "legacy.db"))
    with db.conn:
        db.conn.execute("""CREATE TABLE twitch_chat_events (id TEXT PRIMARY KEY,channel_id TEXT NOT NULL,
            payload TEXT NOT NULL,created REAL NOT NULL,processed INTEGER NOT NULL DEFAULT 0,
            result TEXT,delivered INTEGER NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0)""")
        db.conn.execute("INSERT INTO twitch_chat_events(id,channel_id,payload,created,processed,result) VALUES('old','100','{}',1000,1,?)", (json.dumps({"reply": "kept"}),))
    store = Store(db.conn)
    assert store.next_delivery(False, 1001)["id"] == "old"
    assert Store(db.conn).next_delivery(False, 1001)["result"] == '{"reply": "kept"}'
    db.close()


def test_global_reply_capacity_and_moderation_rate_limit_are_separate(store):
    engine = Engine(store, "999")
    for index in range(5):
        uid = str(300 + index)
        store.save_account(uid, "channel", "channel" + uid, "Channel", "encrypted")
        store.configure(uid, True, dict(DEFAULTS))
        for message in range(10):
            run(engine, "!coins", cid=uid, uid=str(message), message_id=str(message), now=1000)
    assert not store.reply_capacity("100", 1000)
    assert run(engine, "!daily", now=1001) == {}
    assert engine.balance("100", "10") == 500
    for uid in ("100", "200"):
        store.configure(uid, True, {**DEFAULTS, "automod_enabled": True, "block_links": True})
        assert "moderate" in run(engine, "https://example.com", cid=uid, now=1002, message_id="mod")
    with store.conn:
        store.defer_dispatch("100", "moderation", 1040)
    assert Store(store.conn).next_delivery(True, 1003)["channel_id"] == "200"


@pytest.mark.asyncio
async def test_custom_edit_while_selected_cancels_delivery(store, configured, monkeypatch):
    service = Service(store.conn, "https://yamikun.eu")
    store.configure("100", True, {**DEFAULTS, "custom_commands": [custom_command()]})
    run(service.engine, "!discord", now=time.time())
    service.api = AsyncMock(return_value={"data": [{"is_sent": True}]})
    real_sleep = asyncio.sleep
    async def edit_during_yield(delay):
        if delay == 0:
            store.configure("100", True, {**DEFAULTS, "custom_commands": [custom_command(response="Changed")]})
        await real_sleep(0)
    monkeypatch.setattr("twitch_chat.service.asyncio.sleep", edit_during_yield)
    task = asyncio.create_task(service.deliver(False))
    try:
        for _ in range(10):
            await real_sleep(0)
        service.api.assert_not_awaited()
        assert store.conn.execute("SELECT outcome,payload FROM twitch_chat_events").fetchone()[:] == ("cancelled", "{}")
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

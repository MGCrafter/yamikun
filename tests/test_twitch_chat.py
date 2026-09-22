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
    with pytest.raises(TwitchError):
        await service.schedule_auto_messages(1180)
    assert store.conn.execute("SELECT COUNT(*) FROM twitch_chat_events").fetchone()[0] == 2
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
        assert store.conn.execute("SELECT delivered,attempts FROM twitch_chat_events").fetchone()[:] == (1, 1)
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
    result = run(service.engine, now=time.time())
    real_sleep = asyncio.sleep
    async def fast_sleep(delay):
        await real_sleep(0)
    monkeypatch.setattr("twitch_chat.service.asyncio.sleep", fast_sleep)
    retried = asyncio.Event()
    attempts = 0
    async def api(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        assert kwargs["json"]["message"] == result["reply"]
        if attempts == 1:
            raise TwitchError(f"twitch_{status}", status)
        assert "fehlgeschlagen" in store.dashboard("100")["channel"]["error"]
        retried.set()
        return {"data": [{"is_sent": True}]}
    service.api = api
    task = asyncio.create_task(service.deliver(False))
    try:
        await asyncio.wait_for(retried.wait(), 1)
        await real_sleep(0)
        assert attempts == 2
        assert store.dashboard("100")["channel"]["error"] == ""
        assert service.engine.balance("100", "10") == 500
        assert store.conn.execute("SELECT delivered,attempts FROM twitch_chat_events").fetchone()[:] == (1, 1)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

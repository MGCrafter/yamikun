from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import discord
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from db import Database
from cogs.twitch import DEFAULT_TWITCH_MESSAGE, TWITCH_STREAMS_URL, TwitchCog, normalize_login, render_twitch


def test_twitch_login_accepts_channel_url_and_rejects_invalid_values():
    assert normalize_login("https://www.twitch.tv/Stream_er") == "stream_er"
    assert normalize_login("twitch.tv/Player42/") == "player42"
    assert normalize_login("http://m.twitch.tv/Player42") == "player42"
    assert normalize_login("https://www.twitch.tv/player42?lang=de") == "player42"
    assert normalize_login("https://twitch.tv/player42/videos") == "player42"
    assert normalize_login("https://example.test/streamer") is None
    assert normalize_login("not valid") is None
    assert normalize_login("ümlaut") is None


def test_twitch_message_replaces_only_known_tokens():
    stream = {"user_name": "Jessy", "title": "Raid night", "game_name": "Elden Ring"}
    text = render_twitch("{streamer}: {title} / {game} / {url} / {unknown}", stream, "jessy")
    assert text == "Jessy: Raid night / Elden Ring / https://twitch.tv/jessy / {unknown}"
    assert "{url}" in DEFAULT_TWITCH_MESSAGE


def test_twitch_configuration_is_persistent_and_resets_stream_deduplication(tmp_path):
    db = Database(str(tmp_path / "twitch.db"))
    db.set_twitch_config(42, True, "stream_er", 100, "{streamer} ist live", 200)
    config = db.get_twitch_config(42)
    assert config == {
        "enabled": True,
        "login": "stream_er",
        "channel_id": 100,
        "message": "{streamer} ist live",
        "mention_role_id": 200,
        "last_stream_id": None,
    }
    assert db.list_twitch_configs() == [
        {
            "guild_id": 42,
            "login": "stream_er",
            "channel_id": 100,
            "message": "{streamer} ist live",
            "mention_role_id": 200,
            "last_stream_id": None,
        }
    ]
    db.set_twitch_last_stream_id(42, "stream-1")
    assert db.get_twitch_config(42)["last_stream_id"] == "stream-1"
    db.set_twitch_config(42, True, "other", 101, None, None)
    assert db.get_twitch_config(42)["last_stream_id"] is None
    db.close()


@pytest.fixture
def live_bot(tmp_path, monkeypatch):
    monkeypatch.setenv("TWITCH_CLIENT_ID", "client")
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "secret")
    db = Database(str(tmp_path / "live.db"))
    cog = TwitchCog(SimpleNamespace(db=db))
    cog._get_token = AsyncMock(return_value="token")
    cog._announce = AsyncMock(return_value=True)
    yield cog
    db.close()


def test_saving_text_role_or_pause_preserves_announced_stream(live_bot):
    db = live_bot.db
    db.set_twitch_config(42, True, "streamer", 100, None, None)
    db.set_twitch_last_stream_id(42, "stream-1")
    for enabled in (True, False, True):
        db.set_twitch_config(42, enabled, "streamer", 100, "Neuer Text", 200)
        assert db.get_twitch_config(42)["last_stream_id"] == "stream-1"
    db.set_twitch_config(42, True, "streamer", 101, None, None)
    assert db.get_twitch_config(42)["last_stream_id"] is None


@pytest.mark.asyncio
async def test_offline_gap_and_restart_do_not_repeat_same_live_notification(live_bot):
    db = live_bot.db
    db.set_twitch_config(42, True, "streamer", 100, None, None)
    stream = {"id": "stream-1", "user_login": "streamer"}
    live_bot._helix_get = AsyncMock(side_effect=[[stream], []])
    await live_bot.poll_streams()
    await live_bot.poll_streams()
    restarted = TwitchCog(SimpleNamespace(db=db))
    restarted._get_token = live_bot._get_token
    restarted._announce = live_bot._announce
    restarted._helix_get = AsyncMock(side_effect=[[stream], [{**stream, "id": "stream-2"}]])
    await restarted.poll_streams()
    assert restarted._announce.await_count == 1
    await restarted.poll_streams()
    assert restarted._announce.await_count == 2
    assert db.get_twitch_config(42)["last_stream_id"] == "stream-2"


@pytest.mark.asyncio
async def test_live_poll_batches_unique_logins_with_full_page_size(live_bot):
    for gid in range(101):
        live_bot.db.set_twitch_config(gid, True, f"streamer{gid}", 100, None, None)
    live_bot.db.set_twitch_config(101, True, "streamer0", 200, None, None)

    async def streams(url, token, **kwargs):
        params = kwargs["params"]
        assert url == TWITCH_STREAMS_URL
        assert ("first", "100") in params
        return [{"id": "live-" + login, "user_login": login}
                for key, login in params if key == "user_login"]

    live_bot._helix_get = AsyncMock(side_effect=streams)
    await live_bot.poll_streams()
    assert live_bot._helix_get.await_count == 2
    batches = [[v for k, v in call.kwargs["params"] if k == "user_login"]
               for call in live_bot._helix_get.await_args_list]
    assert [len(batch) for batch in batches] == [100, 1]
    assert len(set(batches[0] + batches[1])) == 101
    assert live_bot._announce.await_count == 102


@pytest.mark.asyncio
async def test_failed_discord_delivery_retries_only_undelivered_guild(live_bot):
    for gid in (1, 2):
        live_bot.db.set_twitch_config(gid, True, "streamer", 100, None, None)
    live_bot._helix_get = AsyncMock(return_value=[{"id": "live", "user_login": "streamer"}])
    live_bot._announce.side_effect = [False, True, True]
    await live_bot.poll_streams()
    assert live_bot.db.get_twitch_config(1)["last_stream_id"] is None
    assert live_bot.db.get_twitch_config(2)["last_stream_id"] == "live"
    await live_bot.poll_streams()
    assert [c.args[0]["guild_id"] for c in live_bot._announce.await_args_list] == [1, 2, 1]


@pytest.mark.asyncio
async def test_live_poll_rechecks_pause_after_twitch_request(live_bot):
    live_bot.db.set_twitch_config(42, True, "streamer", 100, None, None)

    async def streams(*args, **kwargs):
        live_bot.db.set_twitch_config(42, False, "streamer", 100, None, None)
        return [{"id": "live", "user_login": "streamer"}]

    live_bot._helix_get = AsyncMock(side_effect=streams)
    await live_bot.poll_streams()
    live_bot._announce.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("still_unauthorized", [False, True])
async def test_live_poll_refreshes_rejected_token_once(live_bot, monkeypatch, still_unauthorized):
    cog = TwitchCog(SimpleNamespace(db=live_bot.db))
    cog._access_token = "stale"
    headers, tokens = [], []

    async def streams(request):
        headers.append(request.headers["Authorization"])
        assert request.query.getall("user_login") == ["streamer", "another"]
        if still_unauthorized or headers[-1] == "Bearer stale":
            return web.json_response({}, status=401)
        return web.json_response({"data": []})

    async def oauth(request):
        tokens.append(await request.post())
        return web.json_response({"access_token": "fresh", "expires_in": 3600})

    app = web.Application()
    app.router.add_get("/streams", streams)
    app.router.add_post("/token", oauth)
    async with TestServer(app) as server, aiohttp.ClientSession() as session:
        cog._session = session
        monkeypatch.setattr("cogs.twitch.TWITCH_OAUTH_URL", str(server.make_url("/token")))
        params = [("first", "100"), ("user_login", "streamer"), ("user_login", "another")]
        if still_unauthorized:
            with pytest.raises(aiohttp.ClientResponseError) as failure:
                await cog._helix_get(str(server.make_url("/streams")), "stale", params=params)
            assert failure.value.status == 401
        else:
            assert await cog._helix_get(str(server.make_url("/streams")), "stale", params=params) == []
            # Later batches still receive the original argument; use the refreshed cache.
            assert await cog._helix_get(str(server.make_url("/streams")), "stale", params=params) == []
    assert len(tokens) == 1
    assert headers == ["Bearer stale", "Bearer fresh"] + ([] if still_unauthorized else ["Bearer fresh"])


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"data": None}, {"data": [None]}, {"data": [{"id": "live"}]}])
async def test_live_poll_rejects_malformed_api_data(live_bot, payload):
    async def streams(request):
        return web.json_response(payload)

    app = web.Application()
    app.router.add_get("/streams", streams)
    async with TestServer(app) as server, aiohttp.ClientSession() as session:
        live_bot._session = session
        with pytest.raises(RuntimeError, match="response is invalid"):
            await live_bot._helix_get(str(server.make_url("/streams")), "token", params=[])


@pytest.mark.asyncio
async def test_live_embed_bounds_expanded_placeholders(live_bot):
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    guild = SimpleNamespace(id=42, me=object(), get_channel=lambda cid: channel)
    cog = TwitchCog(SimpleNamespace(db=live_bot.db, get_guild=lambda gid: guild))
    cfg = {"guild_id": 42, "channel_id": 100, "login": "streamer", "message": "{title}" * 200, "mention_role_id": None}
    stream = {"id": "live", "title": "x" * 140, "user_name": "x" * 300, "game_name": "y" * 1200}
    assert await cog._announce(cfg, stream)
    embed = channel.send.call_args.kwargs["embed"]
    assert len(embed.description) == 4096
    assert len(embed.title) <= 256
    assert len(embed.fields[0].value) <= 1024
    assert len(embed) <= 6000

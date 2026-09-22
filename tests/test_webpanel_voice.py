from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest

from cogs.webpanel import WebPanelCog


class FakeRequest:
    def __init__(self, payload: dict):
        self.payload = payload

    async def json(self) -> dict:
        return self.payload


class FakeVoiceCog:
    def __init__(self) -> None:
        self.calls = []

    async def ensure_voice_setup(self, guild, **kwargs):
        self.calls.append((guild, kwargs))
        return SimpleNamespace(id=10), SimpleNamespace(id=20)


@pytest.mark.asyncio
async def test_webpanel_can_enable_and_configure_join_to_create():
    voice = FakeVoiceCog()
    guild = SimpleNamespace(id=123, get_channel=lambda _cid: None)
    saved = []
    db = SimpleNamespace(
        get_voice_config=lambda _gid: {"enabled": False, "lobby_id": None, "category_id": None},
        set_voice_config=lambda *args, **kwargs: saved.append((args, kwargs)),
    )
    bot = SimpleNamespace(
        get_guild=lambda gid: guild if gid == 123 else None,
        get_cog=lambda name: voice if name == "VoiceMasterCog" else None,
    )
    cog = cast(Any, WebPanelCog.__new__(WebPanelCog))
    cog.bot = bot
    cog.db = db
    cog._require_guild_api = lambda _request: ({"user_id": 7, "username": "Jessy"}, 123)
    cog._check_csrf = lambda *_args, **_kwargs: None

    response = await cog.api_voice_save(FakeRequest({
        "enabled": True,
        "category_id": None,
        "lobby_name": "➕ Gaming Lounge erstellen",
    }))

    assert response.status == 200
    assert json.loads(response.text) == {"ok": True, "lobby_id": "20"}
    assert len(voice.calls) == 1
    called_guild, kwargs = voice.calls[0]
    assert called_guild is guild
    assert kwargs == {
        "actor_label": "WebPanel: Jessy",
        "category_id": None,
        "lobby_id": None,
        "lobby_name": "➕ Gaming Lounge erstellen",
    }
    assert saved == []  # Der Voice-Cog speichert erst nach erfolgreicher Discord-Erstellung.


@pytest.mark.asyncio
async def test_webpanel_can_disable_voice_without_deleting_existing_lobby():
    guild = SimpleNamespace(id=123, get_channel=lambda _cid: None)
    saved = []
    db = SimpleNamespace(
        get_voice_config=lambda _gid: {"enabled": True, "lobby_id": 20, "category_id": 10},
        set_voice_config=lambda *args, **kwargs: saved.append((args, kwargs)),
    )
    bot = SimpleNamespace(get_guild=lambda _gid: guild, get_cog=lambda _name: None)
    cog = cast(Any, WebPanelCog.__new__(WebPanelCog))
    cog.bot = bot
    cog.db = db
    cog._require_guild_api = lambda _request: ({"user_id": 7, "username": "Jessy"}, 123)
    cog._check_csrf = lambda *_args, **_kwargs: None

    response = await cog.api_voice_save(FakeRequest({"enabled": False, "delete_lobby": False}))

    assert response.status == 200
    assert saved == [((123,), {"enabled": False, "lobby_id": 20, "category_id": 10})]


@pytest.mark.asyncio
async def test_webpanel_can_use_an_existing_voice_channel(monkeypatch):
    class ExistingVoiceChannel:
        def __init__(self, channel_id: int) -> None:
            self.id = channel_id

    monkeypatch.setattr("cogs.webpanel.discord.VoiceChannel", ExistingVoiceChannel)
    voice = FakeVoiceCog()
    existing = ExistingVoiceChannel(77)
    guild = SimpleNamespace(id=123, get_channel=lambda cid: existing if cid == 77 else None)
    db = SimpleNamespace(
        get_voice_config=lambda _gid: {"enabled": False, "lobby_id": None, "category_id": None},
    )
    bot = SimpleNamespace(
        get_guild=lambda gid: guild if gid == 123 else None,
        get_cog=lambda name: voice if name == "VoiceMasterCog" else None,
    )
    cog = cast(Any, WebPanelCog.__new__(WebPanelCog))
    cog.bot = bot
    cog.db = db
    cog._require_guild_api = lambda _request: ({"user_id": 7, "username": "Jessy"}, 123)
    cog._check_csrf = lambda *_args, **_kwargs: None

    response = await cog.api_voice_save(FakeRequest({
        "enabled": True,
        "category_id": None,
        "lobby_id": "77",
        "lobby_name": None,
    }))

    assert response.status == 200
    assert voice.calls[0][1] == {
        "actor_label": "WebPanel: Jessy",
        "category_id": None,
        "lobby_id": 77,
        "lobby_name": None,
    }

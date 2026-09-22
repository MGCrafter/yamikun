from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from cogs.voicemaster import (
    VoiceMasterCog,
    clean_voice_name,
    default_voice_name,
    is_join_to_create_trigger,
)
from db import Database


def test_voice_config_and_temp_channels_persist(tmp_path):
    path = tmp_path / "bot.db"
    db = Database(str(path))
    try:
        assert db.get_voice_config(123) == {
            "enabled": False,
            "lobby_id": None,
            "category_id": None,
        }
        db.set_voice_config(123, enabled=True, lobby_id=1001, category_id=1000)
        db.add_temp_voice_channel(123, 2001, 42, created_at=10.0)
        db.add_temp_voice_channel(123, 2002, 43, created_at=20.0)
        db.add_temp_voice_channel(999, 9001, 99, created_at=30.0)
    finally:
        db.close()

    reopened = Database(str(path))
    try:
        assert reopened.get_voice_config(123) == {
            "enabled": True,
            "lobby_id": 1001,
            "category_id": 1000,
        }
        assert [row["channel_id"] for row in reopened.list_temp_voice_channels(123)] == [2001, 2002]
        first = reopened.get_temp_voice_channel(2001)
        assert first is not None
        assert first["owner_id"] == 42
        assert reopened.set_temp_voice_owner(2001, 77) is True
        transferred = reopened.get_temp_voice_channel(2001)
        assert transferred is not None
        assert transferred["owner_id"] == 77
        assert reopened.remove_temp_voice_channel(2001) is True
        assert reopened.remove_temp_voice_channel(2001) is False
        assert [row["channel_id"] for row in reopened.list_temp_voice_channels()] == [2002, 9001]
    finally:
        reopened.close()


def test_voice_names_are_clean_and_bounded():
    assert clean_voice_name("  Gaming\n\t Lounge  ") == "Gaming Lounge"
    assert clean_voice_name("\x00\x01") == "Eigener Voice"
    assert len(clean_voice_name("x" * 150)) == 100
    assert default_voice_name("Jessy") == "🔊 Jessys Lounge"


def test_voice_group_exposes_complete_free_control_set():
    names = {command.name for command in VoiceMasterCog.voice.commands}
    assert names == {
        "setup",
        "disable",
        "status",
        "panel",
        "name",
        "limit",
        "lock",
        "unlock",
        "hide",
        "reveal",
        "permit",
        "reject",
        "transfer",
        "claim",
    }


def test_only_configured_enabled_lobby_triggers_channel_creation():
    config = {"enabled": True, "lobby_id": 1234, "category_id": 555}
    assert is_join_to_create_trigger(config, 1234) is True
    assert is_join_to_create_trigger(config, 9999) is False
    assert is_join_to_create_trigger(config, None) is False
    assert is_join_to_create_trigger({**config, "enabled": False}, 1234) is False


@pytest.mark.asyncio
async def test_setup_can_reuse_selected_existing_lobby_without_creating_one(monkeypatch):
    class FakeCategory:
        def __init__(self) -> None:
            self.id = 10
            self.name = "Gaming"

    class FakeVoiceChannel:
        def __init__(self, category) -> None:
            self.id = 77
            self.name = "Meine Voice Lobby"
            self.category = category
            self.edits = []

        async def edit(self, **kwargs):
            self.edits.append(kwargs)

    monkeypatch.setattr("cogs.voicemaster.discord.CategoryChannel", FakeCategory)
    monkeypatch.setattr("cogs.voicemaster.discord.VoiceChannel", FakeVoiceChannel)
    category = FakeCategory()
    lobby = FakeVoiceChannel(category)
    created = []
    saved = []

    async def create_voice_channel(*args, **kwargs):
        created.append((args, kwargs))

    guild = SimpleNamespace(
        id=123,
        categories=[category],
        get_channel=lambda cid: {10: category, 77: lobby}.get(cid),
        create_voice_channel=create_voice_channel,
    )
    db = SimpleNamespace(
        get_voice_config=lambda _gid: {"enabled": False, "lobby_id": None, "category_id": None},
        set_voice_config=lambda *args, **kwargs: saved.append((args, kwargs)),
    )
    cog = cast(Any, VoiceMasterCog.__new__(VoiceMasterCog))
    cog.db = db

    selected_category, selected_lobby = await cog.ensure_voice_setup(
        guild,
        actor_label="Test",
        lobby_id=77,
        lobby_name=None,
    )

    assert selected_category is category
    assert selected_lobby is lobby
    assert created == []
    assert "name" not in lobby.edits[0]
    assert lobby.edits[0]["user_limit"] == 1
    assert saved == [((123,), {"enabled": True, "lobby_id": 77, "category_id": 10})]

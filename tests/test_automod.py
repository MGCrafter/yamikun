from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from cogs.moderation import (
    AUTO_MOD_DEFAULTS,
    AutomodState,
    automod_should_ignore_member,
    clamp_honeypot_delete_seconds,
    contains_mass_mention,
    normalize_automod_content,
)
from db import Database


def test_automod_settings_roundtrip_and_dedupes_exempt_roles(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    try:
        assert db.get_automod_config(123) == {
            "enabled": False,
            "delete_mass_mentions": True,
            "exempt_role_ids": [],
            "honeypot_channel_ids": [],
            "honeypot_ban": True,
            "honeypot_delete_seconds": 604800,
            **AUTO_MOD_DEFAULTS,
        }

        db.set_automod_config(
            123,
            enabled=True,
            delete_mass_mentions=False,
            exempt_role_ids=[9, 8, 9, 7],
            honeypot_channel_ids=[111, 222, 111],
            honeypot_ban=True,
            honeypot_delete_seconds=999999,
        )

        assert db.get_automod_config(123) == {
            "enabled": True,
            "delete_mass_mentions": False,
            "exempt_role_ids": [9, 8, 7],
            "honeypot_channel_ids": [111, 222],
            "honeypot_ban": True,
            "honeypot_delete_seconds": 604800,
            **AUTO_MOD_DEFAULTS,
        }
    finally:
        db.close()


def test_clamp_honeypot_delete_seconds_keeps_discord_range():
    assert clamp_honeypot_delete_seconds(-5) == 0
    assert clamp_honeypot_delete_seconds(3600) == 3600
    assert clamp_honeypot_delete_seconds(999999) == 604800


def test_normalize_automod_content_collapses_case_spacing_and_mentions():
    assert normalize_automod_content("  FREE   Nitro!!!  ") == "free nitro!!!"
    assert normalize_automod_content("Hallo <@123> <@!456> <#999> <@&888>") == "hallo @user @user #channel @role"


def test_contains_mass_mention_detects_everyone_and_here_case_insensitive():
    assert contains_mass_mention("ping @everyone") is True
    assert contains_mass_mention("ping @HERE") is True
    assert contains_mass_mention("@everyone!") is True
    assert contains_mass_mention("hello everyone") is False
    assert contains_mass_mention("email@everyone.example") is False


def test_automod_state_flags_repeated_identical_message_in_window():
    state = AutomodState(repeat_threshold=3, repeat_window_seconds=20, burst_threshold=5, burst_window_seconds=10)

    first = state.record_message(1, 2, "same text", now=100.0, is_new_member=False)
    second = state.record_message(1, 2, "same text", now=106.0, is_new_member=False)
    third = state.record_message(1, 2, " SAME   TEXT ", now=112.0, is_new_member=False)

    assert first.reasons == []
    assert second.reasons == []
    assert third.reasons == ["repeat_spam"]


def test_automod_state_flags_new_member_burst_only_for_new_members():
    state = AutomodState(repeat_threshold=99, repeat_window_seconds=20, burst_threshold=3, burst_window_seconds=10)

    normal_results = [
        state.record_message(1, 10, f"msg {idx}", now=200.0 + idx, is_new_member=False).reasons
        for idx in range(3)
    ]
    new_results = [
        state.record_message(1, 11, f"msg {idx}", now=300.0 + idx, is_new_member=True).reasons
        for idx in range(3)
    ]

    assert normal_results == [[], [], []]
    assert new_results == [[], [], ["new_member_burst"]]


def test_automod_should_ignore_admin_mods_and_configured_roles():
    admin = SimpleNamespace(
        guild_permissions=SimpleNamespace(administrator=True, manage_messages=False, manage_guild=False),
        roles=[],
    )
    moderator = SimpleNamespace(
        guild_permissions=SimpleNamespace(administrator=False, manage_messages=True, manage_guild=False),
        roles=[],
    )
    exempt_role_member = SimpleNamespace(
        guild_permissions=SimpleNamespace(administrator=False, manage_messages=False, manage_guild=False),
        roles=[SimpleNamespace(id=42)],
    )
    normal_member = SimpleNamespace(
        guild_permissions=SimpleNamespace(administrator=False, manage_messages=False, manage_guild=False),
        roles=[SimpleNamespace(id=5)],
    )

    assert automod_should_ignore_member(admin, [42]) is True
    assert automod_should_ignore_member(moderator, [42]) is True
    assert automod_should_ignore_member(exempt_role_member, [42]) is True
    assert automod_should_ignore_member(normal_member, [42]) is False


def test_automod_state_uses_account_and_join_age_for_new_member():
    state = AutomodState()
    now = datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc)

    assert state.is_new_member(
        joined_at=now - timedelta(minutes=5),
        created_at=now - timedelta(days=30),
        now=now,
    ) is True
    assert state.is_new_member(
        joined_at=now - timedelta(days=5),
        created_at=now - timedelta(hours=6),
        now=now,
    ) is True
    assert state.is_new_member(
        joined_at=now - timedelta(days=5),
        created_at=now - timedelta(days=30),
        now=now,
    ) is False

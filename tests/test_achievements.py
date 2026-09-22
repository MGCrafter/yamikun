from __future__ import annotations

from db import Database
from cogs.achievements import (
    ACHIEVEMENTS,
    achievement_payload,
    can_view_achievements,
    friend_achievement_payload,
    sync_user_achievements,
)


def _achievement(key: str):
    return next(item for item in ACHIEVEMENTS if item.key == key)


def test_secret_achievement_stays_hidden_until_unlocked():
    achievement = _achievement("lucky_century")

    locked = achievement_payload(achievement, {"games": 40}, unlocked_at=None)
    unlocked = achievement_payload(achievement, {"games": 100}, unlocked_at=1234.0)

    assert locked["title"] == "Geheimes Achievement"
    assert locked["description"] == "Details werden erst nach dem Freischalten enthüllt."
    assert locked["progress"] is None
    assert locked["hint"]
    assert unlocked["title"] == "Das Haus kennt dich"
    assert unlocked["hint"] is None
    assert unlocked["progress"] == {"current": 100, "target": 100, "percent": 100}


def test_public_achievement_shows_clamped_progress():
    achievement = _achievement("first_steps")

    payload = achievement_payload(achievement, {"level": 99}, unlocked_at=None)

    assert payload["description"] == "Erreiche Level 1."
    assert payload["progress"] == {"current": 1, "target": 1, "percent": 100}


def test_database_achievement_snapshot_and_unlock_roundtrip(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    try:
        db.get_user(1, 10)
        db.update_user(1, 10, xp=500, level=5, coins=2500)
        db.record_game(1, 10, "coinflip", "win")
        db.add_card(1, 10, "card-a", 7)
        db.add_server_card_owned(1, 10, "yami-a", 3)
        assert db.send_friend_request(1, 10, 20) == "requested"
        assert db.accept_friend(1, 20, 10)
        db.add_friend_xp(1, 10, 20, 250)

        snapshot = db.achievement_snapshot(1, 10)
        assert snapshot["level"] == 5
        assert snapshot["coins"] == 2500
        assert snapshot["games"] == 1
        assert snapshot["wins"] == 1
        assert snapshot["cards"] == 7
        assert snapshot["yami_cards"] == 3
        assert snapshot["friends"] == 1
        assert snapshot["friend_xp"] == 250

        assert db.unlock_achievement(10, "first_steps", unlocked_at=42.0)
        assert not db.unlock_achievement(10, "first_steps", unlocked_at=99.0)
        assert db.get_unlocked_achievements(10) == {"first_steps": 42.0}
    finally:
        db.close()


def test_first_sync_backfills_silently_then_live_sync_reports_new_unlock(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    try:
        db.get_user(1, 10)
        db.update_user(1, 10, xp=0, level=1, coins=0)

        first = sync_user_achievements(db, 1, 10, notify_limit=1)
        assert first == []
        assert "first_steps" in db.get_unlocked_achievements(10)
        assert db.achievements_initialized(10)

        db.update_user(1, 10, xp=0, level=5, coins=0)
        newly_unlocked = sync_user_achievements(db, 1, 10, notify_limit=1)

        assert [item.key for item in newly_unlocked] == ["rising_star"]
        assert "rising_star" in db.get_unlocked_achievements(10)
    finally:
        db.close()


def test_achievement_visibility_is_limited_to_self_or_accepted_friends(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    try:
        assert can_view_achievements(db, 1, 10, 10)
        assert not can_view_achievements(db, 1, 10, 20)

        assert db.send_friend_request(1, 10, 20) == "requested"
        assert not can_view_achievements(db, 1, 10, 20)
        assert db.accept_friend(1, 20, 10)
        assert can_view_achievements(db, 999, 10, 20)
    finally:
        db.close()


def test_catalog_is_expanded_and_contains_many_hintable_secrets():
    secrets = [item for item in ACHIEVEMENTS if item.secret]

    assert len(ACHIEVEMENTS) >= 30
    assert len(secrets) >= 10
    assert all(item.hint for item in secrets)


def test_friend_payload_never_exposes_secret_achievements_even_when_unlocked(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    try:
        db.get_user(1, 20)
        db.unlock_achievement(20, "lucky_century", unlocked_at=1234.0)

        items = friend_achievement_payload(db, 1, 20)

        assert items
        assert all(not item["secret"] for item in items)
        assert "lucky_century" not in {item["id"] for item in items}
        assert "Das Haus kennt dich" not in {item["title"] for item in items}
    finally:
        db.close()

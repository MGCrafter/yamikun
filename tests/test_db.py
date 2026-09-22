from __future__ import annotations

import time

from db import Database


def test_spend_coins_is_atomic_and_never_goes_negative(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    try:
        db.add_coins(123, 456, 100)

        assert db.spend_coins(123, 456, 75) is True
        assert db.get_user(123, 456)["coins"] == 25

        assert db.spend_coins(123, 456, 50) is False
        assert db.get_user(123, 456)["coins"] == 25
    finally:
        db.close()


def test_web_sessions_can_be_saved_loaded_and_deleted(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    try:
        session = {
            "user_id": 42,
            "username": "Jessy",
            "avatar": None,
            "guilds": {111: "Server A"},
            "member_guilds": {111: "Server A", 222: "Server B"},
            "csrf": "csrf-token",
            "exp": time.time() + 3600,
        }

        db.save_web_session("session-token", session)
        loaded = db.get_web_session("session-token")

        assert loaded is not None
        assert loaded["user_id"] == 42
        assert loaded["username"] == "Jessy"
        assert loaded["guilds"] == {111: "Server A"}
        assert loaded["member_guilds"] == {111: "Server A", 222: "Server B"}
        assert loaded["csrf"] == "csrf-token"

        db.delete_web_session("session-token")
        assert db.get_web_session("session-token") is None
    finally:
        db.close()


def test_expired_web_sessions_are_not_returned_and_are_cleaned_up(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    try:
        db.save_web_session(
            "expired-token",
            {
                "user_id": 42,
                "username": "Jessy",
                "avatar": None,
                "guilds": {},
                "member_guilds": {},
                "csrf": "csrf-token",
                "exp": time.time() - 1,
            },
        )

        assert db.get_web_session("expired-token") is None
        assert db.cleanup_web_sessions() >= 0
    finally:
        db.close()


def test_reward_game_aliases_resolve_to_canonical_reward_game(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    try:
        db.add_reward_game(111, "Valorant", 30, 12)
        db.add_reward_game_alias(111, "Valorant", "Valorant Tracker")

        assert db.match_reward_game(111, "Valorant") == "valorant"
        assert db.match_reward_game(111, "Valorant Tracker") == "valorant"
        assert db.list_reward_game_aliases(111) == [("valorant tracker", "valorant")]
    finally:
        db.close()


def test_reward_game_aliases_are_removed_with_canonical_game(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    try:
        db.add_reward_game(111, "Valorant", 30, 12)
        db.add_reward_game_alias(111, "Valorant", "Valorant Tracker")

        assert db.remove_reward_game(111, "Valorant") is True
        assert db.match_reward_game(111, "Valorant Tracker") is None
        assert db.list_reward_game_aliases(111) == []
    finally:
        db.close()


def test_favorite_game_cards_are_global_across_guilds(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    try:
        db.set_fav_game_card(111, 42, "valorant", "neon-card")

        assert db.get_fav_game_cards(222, 42) == {"valorant": "neon-card"}

        db.set_fav_game_card(222, 42, "valorant", None)
        assert db.get_fav_game_cards(111, 42) == {}
    finally:
        db.close()


def test_existing_guild_favorites_are_migrated_to_global_scope(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    try:
        db.conn.execute(
            "INSERT INTO fav_game_cards (guild_id, user_id, game, card_id) VALUES (?, ?, ?, ?)",
            (111, 42, "valorant", "neon-card"),
        )
        db.conn.commit()

        db._migrate_global()

        rows = db.conn.execute(
            "SELECT guild_id, user_id, game, card_id FROM fav_game_cards"
        ).fetchall()
        assert [tuple(row) for row in rows] == [(0, 42, "valorant", "neon-card")]
    finally:
        db.close()


def test_friendship_commands_share_one_global_state_across_guilds(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    try:
        assert db.send_friend_request(111, 10, 20) == "requested"
        assert db.list_incoming_requests(222, 20) == [10]

        assert db.accept_friend(222, 20, 10) is True
        assert db.list_friends(111, 10) == [(20, 0)]
        assert db.list_friends(333, 20) == [(10, 0)]

        assert db.remove_friend(333, 10, 20) is True
        assert db.list_friends(111, 10) == []
    finally:
        db.close()


def test_friendship_xp_is_accumulated_globally_across_guilds(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    try:
        assert db.add_friend_xp(111, 10, 20, 10) == 10
        assert db.add_friend_xp(222, 10, 20, 15) == 25
        assert db.friendship_xp(333, 10, 20) == 25
    finally:
        db.close()


def test_existing_guild_friendships_are_merged_into_global_scope(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    try:
        db.conn.executemany(
            "INSERT INTO friendships (guild_id, user_a, user_b, status, requester, xp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (0, 10, 20, "pending", 10, 5),
                (111, 10, 20, "accepted", None, 40),
                (222, 10, 20, "pending", 20, 60),
            ],
        )
        db.conn.commit()

        db._migrate_global()

        rows = db.conn.execute(
            "SELECT guild_id, user_a, user_b, status, requester, xp FROM friendships"
        ).fetchall()
        assert [tuple(row) for row in rows] == [(0, 10, 20, "accepted", None, 105)]
    finally:
        db.close()

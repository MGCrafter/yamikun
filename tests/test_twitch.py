from db import Database
from cogs.twitch import DEFAULT_TWITCH_MESSAGE, normalize_login, render_twitch


def test_twitch_login_accepts_channel_url_and_rejects_invalid_values():
    assert normalize_login("https://www.twitch.tv/Stream_er") == "stream_er"
    assert normalize_login("twitch.tv/Player42/") == "player42"
    assert normalize_login("http://m.twitch.tv/Player42") == "player42"
    assert normalize_login("https://www.twitch.tv/player42?lang=de") == "player42"
    assert normalize_login("https://twitch.tv/player42/videos") == "player42"
    assert normalize_login("https://example.test/streamer") is None
    assert normalize_login("not valid") is None


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

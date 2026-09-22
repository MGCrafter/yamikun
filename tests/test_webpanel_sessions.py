from __future__ import annotations

from db import Database
from cogs.webpanel import SESSION_COOKIE, WebPanelCog


class FakeBot:
    def __init__(self, db):
        self.db = db
        self.guilds = []


class FakeRequest:
    def __init__(self, token: str):
        self.cookies = {SESSION_COOKIE: token}


def test_new_session_is_persisted_and_survives_new_cog_instance(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    try:
        first = WebPanelCog(FakeBot(db))
        token = first._new_session(
            42,
            "Jessy",
            {111: "Admin Server"},
            {111: "Admin Server", 222: "Member Server"},
            avatar="https://cdn.discordapp.com/embed/avatars/0.png",
        )

        second = WebPanelCog(FakeBot(db))
        loaded = second._session(FakeRequest(token))

        assert loaded is not None
        assert loaded["user_id"] == 42
        assert loaded["username"] == "Jessy"
        assert loaded["guilds"] == {111: "Admin Server"}
        assert loaded["member_guilds"] == {111: "Admin Server", 222: "Member Server"}
    finally:
        db.close()

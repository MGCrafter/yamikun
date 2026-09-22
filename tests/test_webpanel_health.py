from __future__ import annotations

import json

import pytest

from db import Database
from cogs.webpanel import WebPanelCog


class FakeBot:
    def __init__(self, db, guild_count: int = 0):
        self.db = db
        self.guilds = [object() for _ in range(guild_count)]


@pytest.mark.asyncio
async def test_api_health_is_public_and_reports_guild_count(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    try:
        cog = WebPanelCog(FakeBot(db, guild_count=2))

        response = await cog.api_health(object())
        payload = json.loads(response.text)

        assert response.status == 200
        assert payload == {"status": "ok", "guild_count": 2}
    finally:
        db.close()

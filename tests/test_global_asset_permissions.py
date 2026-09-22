import json

import pytest
from aiohttp import web

from cogs.webpanel import SESSION_COOKIE, WebPanelCog
from db import Database


class FakeBot:
    def __init__(self, db):
        self.db = db
        self.guilds = []


class Request:
    def __init__(self, token, csrf, data):
        self.cookies = {SESSION_COOKIE: token}
        self.headers = {'X-CSRF-Token': csrf}
        self.match_info = {'gid': '111'}
        self.data = data

    async def json(self):
        return self.data


@pytest.mark.asyncio
@pytest.mark.parametrize('owners,allowed', [('', False), ('99', False), ('42', True)])
@pytest.mark.parametrize('action', ['coins', 'game', 'yami'])
async def test_only_explicit_owner_can_mutate_global_assets(tmp_path, monkeypatch, owners, allowed, action):
    monkeypatch.setenv('WEB_OWNER_IDS', owners)
    db = Database(str(tmp_path / 'bot.db'))
    try:
        cog = WebPanelCog(FakeBot(db))
        # Admin of server 111 targets assets earned by a user on server 222.
        token = cog._new_session(42, 'Admin', {111: 'A'})
        csrf = cog._sessions[token]['csrf']
        db.add_coins(222, 77, 100)
        db.add_card(222, 77, 'hero', 2)
        db.add_server_card_owned(222, 77, 'hero', 2)
        data = {'user_id': '77', 'amount': '-50', 'kind': action, 'card_id': 'hero'}
        request = Request(token, csrf, data)
        handler = cog.api_economy_coins if action == 'coins' else cog.api_inventory_remove
        me = json.loads((await cog.api_me(request)).text)
        assert me['can_manage_global_assets'] is allowed
        if allowed:
            await handler(request)
        else:
            with pytest.raises(web.HTTPForbidden) as exc:
                await handler(request)
            assert json.loads(exc.value.text)['error'] == 'global_owner_only'
        assert db.get_user(222, 77)['coins'] == (50 if allowed and action == 'coins' else 100)
        assert db.get_collection(222, 77).get('hero', 0) == (0 if allowed and action == 'game' else 2)
        assert db.get_server_collection(222, 77).get('hero', 0) == (0 if allowed and action == 'yami' else 2)
    finally:
        db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('owners,allowed', [('', False), ('99', False), ('42', True)])
async def test_level_coins_also_requires_explicit_owner(tmp_path, monkeypatch, owners, allowed):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from cogs.leveling import LevelingCog

    monkeypatch.setenv('WEB_OWNER_IDS', owners)
    db = Database(str(tmp_path / 'bot.db'))
    try:
        cog = object.__new__(LevelingCog)
        cog.db = db
        interaction = SimpleNamespace(
            guild_id=111, guild=None, user=SimpleNamespace(id=42),
            response=SimpleNamespace(send_message=AsyncMock()),
        )
        target = SimpleNamespace(id=77, mention='<@77>')
        db.add_coins(222, 77, 100)
        await LevelingCog.level_coins.callback(cog, interaction, target, -50)
        assert db.get_user(222, 77)['coins'] == (50 if allowed else 100)
        interaction.response.send_message.assert_awaited_once()
    finally:
        db.close()

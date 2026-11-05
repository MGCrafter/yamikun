from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from aiohttp import web
import pytest

from cogs.webpanel import STATE_COOKIE, WebPanelCog


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "cookies"),
    [
        ({"code": "test-code"}, {}),
        ({"code": "test-code", "state": ""}, {STATE_COOKIE: ""}),
        ({"code": "test-code", "state": "test-state"}, {}),
        ({"code": "test-code", "state": "test-state"}, {STATE_COOKIE: ""}),
        ({"code": "test-code", "state": "test-state"}, {STATE_COOKIE: "other-state"}),
        ({"state": "test-state"}, {STATE_COOKIE: "test-state"}),
    ],
)
async def test_callback_rejects_missing_or_invalid_state_before_http(query, cookies):
    cog = object.__new__(WebPanelCog)
    cog.client_id = "test-client"
    cog.client_secret = "test-secret"
    cog.redirect_uri = "https://example.invalid/callback"
    cog._http = MagicMock()
    cog._http.post.side_effect = AssertionError("OAuth exchange must not be called")
    request = SimpleNamespace(query=query, cookies=cookies)

    with pytest.raises(web.HTTPFound) as redirect:
        await cog.h_callback(request)

    assert redirect.value.location == "/?error=state"
    cog._http.post.assert_not_called()


@pytest.mark.asyncio
async def test_callback_matching_state_reaches_existing_token_exchange():
    cog = object.__new__(WebPanelCog)
    cog.client_id = "test-client"
    cog.client_secret = "test-secret"
    cog.redirect_uri = "https://example.invalid/callback"
    cog._http = MagicMock()
    response = MagicMock()
    response.__aenter__ = AsyncMock(return_value=SimpleNamespace(status=400))
    response.__aexit__ = AsyncMock(return_value=False)
    cog._http.post.return_value = response
    request = SimpleNamespace(
        query={"code": "test-code", "state": "test-state"},
        cookies={STATE_COOKIE: "test-state"},
    )

    with pytest.raises(web.HTTPFound) as redirect:
        await cog.h_callback(request)

    assert redirect.value.location == "/?error=token"
    cog._http.post.assert_called_once()

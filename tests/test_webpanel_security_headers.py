from __future__ import annotations

import pytest
from aiohttp import web

from cogs.webpanel import _cache_compress_mw


class FakeRequest:
    def __init__(self, path: str):
        self.path = path


@pytest.mark.asyncio
async def test_webpanel_middleware_adds_baseline_security_headers():
    async def handler(_request):
        return web.Response(text="<html></html>", content_type="text/html")

    response = await _cache_compress_mw(FakeRequest("/app"), handler)

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "same-origin"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]

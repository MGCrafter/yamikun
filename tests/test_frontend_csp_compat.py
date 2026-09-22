from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from aiohttp import web
from aiohttp.web_request import Request

from cogs.webpanel import _cache_compress_mw


class FakeRequest:
    def __init__(self, path: str):
        self.path = path


@pytest.mark.asyncio
async def test_csp_allows_declared_external_font_sources():
    async def handler(_request):
        return web.Response(text="<html></html>", content_type="text/html")

    response = await _cache_compress_mw(cast(Request, FakeRequest("/app")), handler)
    csp = response.headers["Content-Security-Policy"]

    assert "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com" in csp
    assert "font-src 'self' data: https://fonts.gstatic.com" in csp


def test_frontend_index_has_no_inline_scripts_or_event_handlers_blocked_by_csp():
    html = Path("frontend/index.html").read_text(encoding="utf-8")

    assert "<script>" not in html
    assert " onload=" not in html


def test_all_message_previews_use_shared_discord_markdown_renderer():
    component = Path("frontend/src/components/DiscordMarkdown.tsx").read_text(encoding="utf-8")
    assert "**" in component
    assert "__" in component
    assert "~~" in component
    assert "||" in component
    assert "dangerouslySetInnerHTML" not in component

    for page in ("Announce", "Welcome", "Boost", "Levelup"):
        source = Path(f"frontend/src/pages/{page}.tsx").read_text(encoding="utf-8")
        assert 'from "../components/DiscordMarkdown"' in source
        assert "<DiscordMarkdown" in source

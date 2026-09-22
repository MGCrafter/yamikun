from __future__ import annotations

from aiohttp import web

from webpanel.routes import register_routes


async def _handler(_request):
    return web.Response(text="ok")


class FakeCog:
    def __getattr__(self, name: str):
        if name.startswith(("h_", "api_")):
            return _handler
        raise AttributeError(name)


def test_register_routes_keeps_core_webpanel_paths_available(tmp_path):
    app = web.Application()
    static_dir = tmp_path / "static"
    assets_dir = tmp_path / "assets"
    static_dir.mkdir()
    assets_dir.mkdir()

    register_routes(app, FakeCog(), static_dir=static_dir, assets_dir=assets_dir)

    paths = {resource.canonical for resource in app.router.resources()}

    assert "/login" in paths
    assert "/callback" in paths
    assert "/api/health" in paths
    assert "/api/me" in paths
    assert "/api/g/{gid}/tickets" in paths
    assert "/api/g/{gid}/automod" in paths
    assert "/api/g/{gid}/twitch" in paths
    assert "/api/g/{gid}/voice" in paths
    assert "/api/u/{gid}/dashboard" in paths
    assert "/api/u/{gid}/achievements" in paths
    assert "/api/u/{gid}/cards/dismantle" in paths
    assert "/api/u/{gid}/boosters/exchange" in paths
    assert "/api/u/{gid}/feedback" in paths
    assert "/static" in paths
    assert "/" in paths
    assert "/{tail}" in paths

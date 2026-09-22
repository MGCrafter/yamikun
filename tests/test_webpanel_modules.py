from __future__ import annotations

from aiohttp import web

from webpanel.constants import SESSION_COOKIE, UPLOAD_ERRORS
from webpanel.helpers import card_payload, discord_avatar, is_http_url, local_static_url
from webpanel.middleware import cache_compress_middleware, rate_bucket


def test_webpanel_constants_are_available_from_dedicated_module():
    assert SESSION_COOKIE == "ot_session"
    assert UPLOAD_ERRORS["type"].startswith("Dateityp nicht unterstützt")


def test_webpanel_helpers_are_available_from_dedicated_module():
    assert discord_avatar(42, None).endswith(".png")
    assert is_http_url("https://example.com/image.png") is True
    assert is_http_url("javascript:alert(1)") is False

    payload = card_payload("c1", "Yami", "common", "https://example.com/yami.png", game="Game", count=2)
    assert payload["id"] == "c1"
    assert payload["rarity_label"]
    assert payload["game"] == "Game"
    assert payload["count"] == 2

    assert local_static_url("https://old.example/static/cards/0/card.png?v=1") == "/static/cards/0/card.png?v=1"
    assert local_static_url("/static/yami/card.webp") == "/static/yami/card.webp"
    assert local_static_url("https://cdn.discordapp.com/attachments/card.png") == "https://cdn.discordapp.com/attachments/card.png"


def test_webpanel_middleware_is_available_from_dedicated_module():
    assert rate_bucket("/api/me") == "api"
    assert rate_bucket("/login") == "auth"
    assert rate_bucket("/app") is None
    assert callable(cache_compress_middleware)
    assert getattr(cache_compress_middleware, "__middleware_version__", None) == 1

from __future__ import annotations

from cogs.webpanel import WebPanelCog


def test_is_http_url_accepts_only_http_and_https():
    assert WebPanelCog._is_http_url("https://example.com/image.png") is True
    assert WebPanelCog._is_http_url("http://example.com/image.png") is True

    assert WebPanelCog._is_http_url("javascript:alert(1)") is False
    assert WebPanelCog._is_http_url("data:image/png;base64,abc") is False
    assert WebPanelCog._is_http_url("file:///tmp/x.png") is False
    assert WebPanelCog._is_http_url("https://") is False


def test_field_trims_values_and_converts_missing_to_empty_string():
    assert WebPanelCog._field({"name": "  Yami  "}, "name") == "Yami"
    assert WebPanelCog._field({}, "name") == ""

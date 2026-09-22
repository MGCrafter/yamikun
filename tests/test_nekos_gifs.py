from __future__ import annotations

import pytest

from cogs.nekos import NEKOS_USER_AGENT, fetch_gif_file


class FakeResponse:
    def __init__(self, *, json_data=None, body=b"", content_type="application/json"):
        self._json_data = json_data
        self._body = body
        self.content_type = content_type

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def raise_for_status(self):
        return None

    async def json(self):
        return self._json_data

    async def read(self):
        return self._body


class FakeSession:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url.endswith("/hug"):
            return FakeResponse(
                json_data={"results": [{"url": "https://nekos.best/media/hug.gif"}]}
            )
        return FakeResponse(body=b"GIF89a-test", content_type="image/gif")


@pytest.mark.asyncio
async def test_gif_is_downloaded_with_valid_user_agent_and_attached():
    session = FakeSession()

    file = await fetch_gif_file(session, "hug", filename="hug.gif")

    assert file is not None
    assert file.filename == "hug.gif"
    assert len(session.calls) == 2
    assert all(call[1]["headers"]["User-Agent"] == NEKOS_USER_AGENT for call in session.calls)
    assert NEKOS_USER_AGENT.startswith("YamiKun (")

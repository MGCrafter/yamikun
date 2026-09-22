from __future__ import annotations

import io
from types import SimpleNamespace
from typing import Any, cast

import discord
import pytest

from cogs.marry import ABANDONED_GIF_CATEGORIES, ProposalView


class FakeCog:
    def __init__(self) -> None:
        self.category = None

    async def _fetch_gif(self, category: str) -> discord.File:
        self.category = category
        return discord.File(io.BytesIO(b"GIF89a"), filename="abandoned.gif")


class FakeMessage:
    def __init__(self) -> None:
        self.edit_kwargs = None

    async def edit(self, **kwargs) -> None:
        self.edit_kwargs = kwargs


@pytest.mark.asyncio
async def test_expired_proposal_uses_alter_message_and_random_gif_category():
    cog = FakeCog()
    proposer = SimpleNamespace(id=1, mention="<@1>")
    target = SimpleNamespace(id=2, mention="<@2>")
    view = ProposalView(
        cast(Any, cog), cast(Any, proposer), cast(Any, target)
    )
    message = FakeMessage()
    view.message = cast(Any, message)

    await view.on_timeout()

    assert view.done is True
    assert cog.category in ABANDONED_GIF_CATEGORIES
    assert len(ABANDONED_GIF_CATEGORIES) >= 5
    assert message.edit_kwargs is not None
    embed = message.edit_kwargs["embed"]
    assert embed.title == "🥀 Am Altar allein gelassen …"
    assert "am Altar allein gelassen" in embed.description
    assert embed.image.url == "attachment://abandoned.gif"
    assert len(message.edit_kwargs["attachments"]) == 1
    assert all(button.disabled for button in view.children)

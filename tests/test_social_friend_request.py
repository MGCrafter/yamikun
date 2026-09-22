from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import discord
import pytest

from cogs.social import FriendRequestView, friend_request_embed


def _user(user_id: int, name: str):
    return SimpleNamespace(
        id=user_id,
        display_name=name,
        mention=f"<@{user_id}>",
        display_avatar=SimpleNamespace(url=f"https://cdn.example/{user_id}.png"),
    )


def test_friend_request_embed_has_branded_copy_and_both_users():
    requester = _user(10, "Alice")
    target = _user(20, "Jessy")

    embed = friend_request_embed(cast(Any, requester), cast(Any, target))

    assert embed.title == "Eine neue Verbindung wartet"
    assert requester.mention in (embed.description or "")
    assert "öffentlichen Achievements" in (embed.description or "")
    assert embed.author.name == "Alice"
    assert (embed.thumbnail.url or "").endswith("/20.png")


@pytest.mark.asyncio
async def test_friend_request_view_contains_accept_button():
    view = FriendRequestView(SimpleNamespace(), 1, 10, 20)

    assert len(view.children) == 1
    button = view.children[0]
    assert isinstance(button, discord.ui.Button)
    assert button.label == "Freundschaft annehmen"
    assert button.style is discord.ButtonStyle.success
    assert view.timeout == 86_400


@pytest.mark.asyncio
async def test_accept_button_closes_friend_request_and_updates_message():
    calls: list[tuple[int, int, int]] = []

    class FakeDb:
        def accept_friend(self, guild_id: int, target_id: int, requester_id: int) -> bool:
            calls.append((guild_id, target_id, requester_id))
            return True

    class FakeResponse:
        def __init__(self) -> None:
            self.edited: dict | None = None

        async def edit_message(self, **kwargs) -> None:
            self.edited = kwargs

    response = FakeResponse()
    interaction = SimpleNamespace(
        user=SimpleNamespace(id=20, mention="<@20>"),
        response=response,
    )
    view = FriendRequestView(FakeDb(), 1, 10, 20)
    button = cast(discord.ui.Button, view.children[0])

    await button.callback(cast(Any, interaction))

    assert calls == [(1, 20, 10)]
    assert button.disabled
    assert button.label == "Freundschaft angenommen"
    assert response.edited is not None
    assert response.edited["view"] is view
    assert response.edited["embed"].title == "Freundschaft geschlossen"

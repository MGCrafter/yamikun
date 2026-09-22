from __future__ import annotations

from types import SimpleNamespace

import pytest

from cogs.webpanel import WebPanelCog


class SentUser:
    def __init__(self) -> None:
        self.embeds = []

    async def send(self, *, embed):
        self.embeds.append(embed)


class FakeBot:
    def __init__(self, user: SentUser) -> None:
        self.user = user

    def get_guild(self, gid: int):
        return SimpleNamespace(name=f"Guild {gid}")

    def get_user(self, uid: int):
        return self.user if uid == 999 else None


@pytest.mark.asyncio
async def test_notify_owners_feedback_sends_bugreport_embed_to_owner():
    owner = SentUser()
    cog = object.__new__(WebPanelCog)
    setattr(cog, "bot", FakeBot(owner))
    cog.owner_ids = {999}

    delivered = await cog._notify_owners_feedback(
        123,
        {"username": "Jessy", "user_id": 42},
        "bug",
        "Karten werden doppelt angezeigt",
        "Beim Blättern wächst der Profiltext immer weiter.",
    )

    assert delivered == 1
    assert len(owner.embeds) == 1
    embed = owner.embeds[0]
    assert embed.title == "🐞 Neuer Bugreport"
    assert embed.description == "Eine neue Meldung ist über das Webpanel eingegangen."
    assert embed.fields[0].name == "Server"
    assert embed.fields[0].value == "Guild 123"
    assert embed.fields[3].name == "Titel"
    assert embed.fields[3].value == "Karten werden doppelt angezeigt"
    assert embed.fields[-1].name == "Nachricht"
    assert "Profiltext" in embed.fields[-1].value

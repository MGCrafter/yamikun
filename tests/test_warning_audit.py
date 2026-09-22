from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from cogs.moderation import ModerationCog


class FakeAudit:
    def __init__(self) -> None:
        self.calls = []

    async def log(self, *args, **kwargs) -> None:
        self.calls.append((args, kwargs))


@pytest.mark.asyncio
async def test_manual_warning_uses_live_audit_cog_not_database_only():
    audit = FakeAudit()
    bot = SimpleNamespace(get_cog=lambda name: audit if name == "AuditCog" else None)
    db = SimpleNamespace(add_audit_log=lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("DB fallback must not run when AuditCog is loaded")
    ))
    cog = cast(Any, ModerationCog.__new__(ModerationCog))
    cog.bot = bot
    cog.db = db
    guild = SimpleNamespace(id=123)
    actor = SimpleNamespace(id=7)
    target = SimpleNamespace(id=42)

    await cog._log_moderation_action(
        cast(Any, guild),
        "warning_add",
        "Warnung erstellt",
        actor=cast(Any, actor),
        target=cast(Any, target),
        detail="Grund: Spam",
    )

    assert len(audit.calls) == 1
    args, kwargs = audit.calls[0]
    assert args[1:4] == ("members", "warning_add", "Warnung erstellt")
    assert kwargs["actor"] is actor
    assert kwargs["target"] is target
    assert kwargs["detail"] == "Grund: Spam"

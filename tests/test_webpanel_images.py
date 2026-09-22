from __future__ import annotations

import asyncio
from io import BytesIO

import pytest
from PIL import Image

from cogs.webpanel import WebPanelCog
from webpanel.images import MAX_CARD_DIMENSION, optimize_existing_card_image, save_card_upload


def _animated_gif_bytes() -> bytes:
    first = Image.new("RGBA", (8, 8), (255, 0, 0, 255))
    second = Image.new("RGBA", (8, 8), (0, 0, 255, 255))
    out = BytesIO()
    first.save(out, format="GIF", save_all=True, append_images=[second], duration=[80, 120], loop=0)
    return out.getvalue()


def test_gif_card_upload_is_converted_to_animated_webp(tmp_path):
    dest = save_card_upload(_animated_gif_bytes(), ".gif", tmp_path, "sparkle-card")

    assert dest.name == "sparkle-card.webp"
    assert not (tmp_path / "sparkle-card.gif").exists()
    with Image.open(dest) as image:
        assert image.format == "WEBP"
        assert getattr(image, "is_animated", False)
        assert getattr(image, "n_frames", 1) == 2


def test_static_card_upload_is_resized_and_converted_to_webp(tmp_path):
    image = Image.new("RGB", (MAX_CARD_DIMENSION * 2, MAX_CARD_DIMENSION), (0, 255, 0))
    out = BytesIO()
    image.save(out, format="PNG")

    dest = save_card_upload(out.getvalue(), ".png", tmp_path, "green-card")

    assert dest.name == "green-card.webp"
    assert dest.read_bytes()[:4] == b"RIFF"
    with Image.open(dest) as optimized:
        assert optimized.format == "WEBP"
        assert max(optimized.size) == MAX_CARD_DIMENSION


def test_existing_png_card_is_migrated_to_webp(tmp_path):
    old = tmp_path / "legacy-card.png"
    image = Image.new("RGBA", (64, 64), (20, 40, 60, 180))
    image.save(old, format="PNG")

    dest = optimize_existing_card_image(old)

    assert dest == tmp_path / "legacy-card.webp"
    assert dest.exists()
    assert not old.exists()
    with Image.open(dest) as optimized:
        assert optimized.format == "WEBP"


@pytest.mark.asyncio
async def test_webpanel_migrates_existing_local_card_and_updates_database_url(tmp_path, monkeypatch):
    static_dir = tmp_path / "static"
    yami_dir = static_dir / "yami"
    yami_dir.mkdir(parents=True)
    old = yami_dir / "srv_legacy.png"
    Image.new("RGB", (80, 80), (90, 20, 120)).save(old, format="PNG")

    updates = []

    class FakeDb:
        def list_custom_cards(self, _guild_id):
            return []

        def list_server_cards(self, _guild_id):
            return [("srv_legacy", "Legacy", "rare", "https://old.example/static/yami/srv_legacy.png")]

        def add_server_card(self, *args):
            updates.append(args)

    monkeypatch.setattr("cogs.webpanel.STATIC_DIR", static_dir)
    cog = object.__new__(WebPanelCog)
    cog.db = FakeDb()
    cog.base_url = "https://new.example"

    assert await cog._optimize_existing_card_images() == 1
    assert not old.exists()
    assert (yami_dir / "srv_legacy.webp").exists()
    assert updates[0][4].startswith("https://new.example/static/yami/srv_legacy.webp?v=")


@pytest.mark.asyncio
async def test_webpanel_start_does_not_wait_for_slow_card_migration(tmp_path, monkeypatch):
    migration_started = asyncio.Event()
    release_migration = asyncio.Event()

    class FakeRunner:
        def __init__(self, _app):
            pass

        async def setup(self):
            pass

        async def cleanup(self):
            pass

    class FakeSite:
        def __init__(self, *_args):
            pass

        async def start(self):
            pass

    async def slow_migration():
        migration_started.set()
        await release_migration.wait()

    monkeypatch.setattr("cogs.webpanel.STATIC_DIR", tmp_path / "static")
    monkeypatch.setattr("cogs.webpanel.register_routes", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("cogs.webpanel.web.AppRunner", FakeRunner)
    monkeypatch.setattr("cogs.webpanel.web.TCPSite", FakeSite)

    cog = object.__new__(WebPanelCog)
    cog.enabled = True
    from db import Database
    cog.db = Database(":memory:")
    cog.base_url = "https://example.test"
    cog.client_id = "client"
    cog.client_secret = "secret"
    cog.host = "127.0.0.1"
    cog.port = 8080
    cog._runner = None
    cog._http = None
    cog._card_migration_task = None
    cog._run_card_image_migration = slow_migration

    await asyncio.wait_for(cog.cog_load(), timeout=0.5)
    await asyncio.wait_for(migration_started.wait(), timeout=0.5)
    task = cog._card_migration_task
    assert task is not None
    assert not task.done()

    release_migration.set()
    await asyncio.wait_for(task, timeout=0.5)
    await cog.cog_unload()
    cog.db.close()

from __future__ import annotations

from pathlib import Path

from db import Database


ROOT = Path(__file__).resolve().parents[1]


def test_dismantle_keeps_last_copy_and_persists_global_shards(tmp_path):
    path = tmp_path / "bot.db"
    db = Database(str(path))
    try:
        db.add_card(111, 42, "card-a", 3)

        ok, shards, remaining = db.dismantle_card_duplicate(111, 42, "card-a", 80)
        assert (ok, shards, remaining) == (True, 80, 2)

        # Karten und Splitter sind serverübergreifend global.
        ok, shards, remaining = db.dismantle_card_duplicate(999, 42, "card-a", 80)
        assert (ok, shards, remaining) == (True, 160, 1)

        ok, shards, remaining = db.dismantle_card_duplicate(111, 42, "card-a", 80)
        assert (ok, shards, remaining) == (False, 160, 1)
    finally:
        db.close()

    reopened = Database(str(path))
    try:
        assert reopened.get_card_shards(555, 42) == 160
        assert reopened.get_collection(555, 42)["card-a"] == 1
    finally:
        reopened.close()


def test_shards_exchange_is_atomic_and_uses_existing_game_pack_inventory(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    try:
        pack_type = "game:elden ring"
        ok, shards, packs = db.exchange_card_shards_for_pack(1, 7, pack_type, 400)
        assert (ok, shards, packs) == (False, 0, 0)

        db.add_card(1, 7, "duplicate", 2)
        assert db.dismantle_card_duplicate(1, 7, "duplicate", 500)[0]

        ok, shards, packs = db.exchange_card_shards_for_pack(1, 7, pack_type, 400)
        assert (ok, shards, packs) == (True, 100, 1)
        assert db.list_packs(999, 7)[pack_type] == 1

        # Fehlgeschlagener zweiter Tausch verändert weder Guthaben noch Packbestand.
        ok, shards, packs = db.exchange_card_shards_for_pack(1, 7, pack_type, 400)
        assert (ok, shards, packs) == (False, 100, 1)
    finally:
        db.close()


def test_profile_uses_animated_game_card_album_and_real_api_actions():
    dashboard = (ROOT / "frontend/src/pages/UserDashboard.tsx").read_text(encoding="utf-8")
    album = (ROOT / "frontend/src/components/ui/CardAlbum.tsx").read_text(encoding="utf-8")
    webpanel = (ROOT / "cogs/webpanel.py").read_text(encoding="utf-8")

    assert "<CardAlbum" in dashboard
    assert "/cards/dismantle" in dashboard
    assert "/boosters/exchange" in dashboard
    assert "album-flip" in album
    assert "Noch nicht entdeckt" in album
    assert "api_user_card_dismantle" in webpanel
    assert "api_user_booster_exchange" in webpanel

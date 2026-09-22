from __future__ import annotations

from db import Database


def test_warnings_are_persistent_scoped_and_manageable(tmp_path):
    path = tmp_path / "bot.db"
    db = Database(str(path))
    try:
        first = db.add_warning(111, 42, 7, "  Spam im Chat  ", created_at=1000.0)
        second = db.add_warning(111, 42, 8, "Beleidigung", created_at=2000.0)
        other_guild = db.add_warning(222, 42, 9, "Anderer Server", created_at=3000.0)

        assert first["reason"] == "Spam im Chat"
        assert [row["id"] for row in db.list_warnings(111, 42)] == [second["id"], first["id"]]
        assert db.remove_warning(222, first["id"]) is None
        removed = db.remove_warning(111, first["id"])
        assert removed is not None
        assert removed["reason"] == "Spam im Chat"
        assert [row["id"] for row in db.list_warnings(111, 42)] == [second["id"]]
        assert [row["id"] for row in db.list_warnings(222, 42)] == [other_guild["id"]]
    finally:
        db.close()

    reopened = Database(str(path))
    try:
        assert len(reopened.list_warnings(111, 42)) == 1
        assert reopened.clear_warnings(111, 42) == 1
        assert reopened.clear_warnings(111, 42) == 0
        assert len(reopened.list_warnings(222, 42)) == 1
    finally:
        reopened.close()


def test_warning_reason_must_contain_text_and_is_bounded(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    try:
        try:
            db.add_warning(1, 2, 3, "   ")
        except ValueError:
            pass
        else:
            raise AssertionError("Leere Gründe müssen abgelehnt werden")

        row = db.add_warning(1, 2, 3, "x" * 1200)
        assert len(row["reason"]) == 1000
    finally:
        db.close()

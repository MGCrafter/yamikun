from __future__ import annotations

import sqlite3
import subprocess
import tarfile
from pathlib import Path


def test_backup_script_creates_timestamped_sqlite_backup(tmp_path):
    db_path = tmp_path / "bot.db"
    with sqlite3.connect(db_path) as con:
        con.execute("CREATE TABLE notes (body TEXT NOT NULL)")
        con.execute("INSERT INTO notes VALUES ('backup-ok')")

    out_dir = tmp_path / "backups"
    result = subprocess.run(
        ["bash", "scripts/backup_db.sh", str(db_path), str(out_dir)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    backup_path = Path(result.stdout.strip().splitlines()[-1])
    assert backup_path.is_file()
    assert backup_path.match(str(out_dir / "????-??-??" / "??-??-??" / "bot-db_????-??-??_??-??-??.tar.gz"))

    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    with tarfile.open(backup_path, "r:gz") as archive:
        names = archive.getnames()
        assert "bot.db" in names
        assert "MANIFEST.txt" in names
        archive.extractall(extract_dir, filter="data")

    with sqlite3.connect(extract_dir / "bot.db") as con:
        row = con.execute("SELECT body FROM notes").fetchone()
    assert row == ("backup-ok",)

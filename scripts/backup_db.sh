#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DB_PATH="${1:-$ROOT/bot.db}"
BACKUP_ROOT="${2:-$ROOT/backups}"

if [[ ! -f "$DB_PATH" ]]; then
  printf 'Fehler: Datenbank nicht gefunden: %s\n' "$DB_PATH" >&2
  exit 1
fi

STAMP="$(date +%Y-%m-%d_%H-%M-%S)"
DATE_DIR="${STAMP%%_*}"
TIME_DIR="${STAMP##*_}"
OUT_DIR="$BACKUP_ROOT/$DATE_DIR/$TIME_DIR"
WORK_DIR="$(mktemp -d)"
OUT="$OUT_DIR/bot-db_${STAMP}.tar.gz"

cleanup() {
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

mkdir -p "$OUT_DIR"

DB_PATH="$DB_PATH" WORK_DIR="$WORK_DIR" python3 - <<'PY'
import os
import sqlite3
from pathlib import Path

source = Path(os.environ["DB_PATH"])
target = Path(os.environ["WORK_DIR"]) / "bot.db"

with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
    src.backup(dst)
PY

cat > "$WORK_DIR/MANIFEST.txt" <<EOF
Yumikun SQLite Backup
Created: $STAMP
Source: $DB_PATH
Content: bot.db created via sqlite3 backup API
Restore: stop the bot, replace bot.db with this backup, then start the bot again
EOF

tar -C "$WORK_DIR" -czf "$OUT" bot.db MANIFEST.txt
printf 'Backup erstellt:\n%s\n' "$OUT"

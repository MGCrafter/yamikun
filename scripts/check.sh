#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT/.venv/bin/python"
fi

export PYTHONDONTWRITEBYTECODE=1

"$PYTHON_BIN" -m compileall -q bot.py db.py cogs webpanel twitch_chat tests
"$PYTHON_BIN" -m pytest -q
(cd frontend && npx tsc --noEmit --incremental false)
(cd frontend && npm run build)

#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TARBALL_DIR="$ROOT/.local/deployments"
STAMP="$(date +%Y-%m-%d_%H-%M-%S)"
DATE_DIR="${STAMP%%_*}"
TIME_DIR="${STAMP##*_}"
OUT_DIR="$TARBALL_DIR/$DATE_DIR/$TIME_DIR"
mkdir -p "$OUT_DIR"

BASE_NAME="$(basename "${1:-yumikun-caprover.tar.gz}")"
if [[ "$BASE_NAME" == *.tar.gz ]]; then
  BASE_NAME="${BASE_NAME%.tar.gz}"
fi
NAME="${BASE_NAME}_${STAMP}.tar.gz"
OUT="$OUT_DIR/$NAME"
TMP_OUT="$(mktemp --tmpdir yumikun-caprover.XXXXXX.tar.gz)"
trap 'rm -f "$TMP_OUT"' EXIT

tar \
  --exclude='.git' \
  --exclude='.hermes' \
  --exclude='.codex' \
  --exclude='.local' \
  --exclude='.github' \
  --exclude='.env' \
  --exclude='.env.*' \
  --exclude='bot.db' \
  --exclude='bot.db-wal' \
  --exclude='bot.db-shm' \
  --exclude='bot.db.bak*' \
  --exclude='*.db' \
  --exclude='*.db-*' \
  --exclude='*.db.*' \
  --exclude='*.sqlite*' \
  --exclude='*.pem' \
  --exclude='*.key' \
  --exclude='config.json' \
  --exclude='static' \
  --exclude='data' \
  --exclude='backups' \
  --exclude='TMP for Caprover Tarballs' \
  --exclude='.venv' \
  --exclude='venv' \
  --exclude='.pytest_cache' \
  --exclude='__pycache__' \
  --exclude='*.py[cod]' \
  --exclude='frontend/node_modules' \
  --exclude='frontend/dist' \
  --exclude='frontend/*.tsbuildinfo' \
  --exclude='frontend/vite.config.js' \
  --exclude='frontend/vite.config.d.ts' \
  --exclude='*.zip' \
  --exclude='*.tar.gz' \
  --exclude='*.tar' \
  --exclude='*.tgz' \
  --exclude='*.bak' \
  --exclude='*.log' \
  --exclude='Screenshot*' \
  --exclude='design-preview' \
  --exclude='docs' \
  --exclude='tests' \
  --exclude='dev_panel.py' \
  -czf "$TMP_OUT" .

mv "$TMP_OUT" "$OUT"
printf 'Tarball erstellt: %s\n' "$OUT"

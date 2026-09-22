"""Konstanten und Pfade für das aiohttp-WebPanel."""

from __future__ import annotations

import os
from pathlib import Path

# MIME-Typ je Bilddateiendung (für Base64-Avatar-Uploads an die Discord-API).
IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

API_BASE = "https://discord.com/api"
SCOPE = "identify"
SESSION_COOKIE = "ot_session"
STATE_COOKIE = "ot_oauth_state"
SESSION_TTL = 60 * 60 * 8  # 8 Stunden
MAX_UPLOAD = 70 * 1024 * 1024  # 70 MB
# Mindestabstand zwischen zwei Spiel-Anfragen desselben Users (Sekunden).
# Verhindert, dass jemand die WebOwner mit DMs/API-Calls flutet (token-sparsam).
GAME_REQUEST_COOLDOWN = 5 * 60
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

# Discord-Längenlimits für eingegebene Texte (serverseitig erzwungen).
MSG_MAX = 2000
EMBED_TITLE_MAX = 256
EMBED_DESC_MAX = 4096
NICK_MAX = 32
COIN_AMOUNT_MAX = 1_000_000_000

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Hochgeladene Karten-Bilder. Über DATA_DIR auf einen persistenten Ordner
# umlenkbar (z.B. /data in Containern). Lokal: aktuelles Verzeichnis.
STATIC_DIR = Path(os.environ.get("DATA_DIR", ".")) / "static"
# Mitgelieferte Design-Assets (Logo etc.) — liegen im Repo, immer verfügbar.
ASSETS_DIR = PROJECT_ROOT / "webassets"
# Gebautes React-Frontend (Vite). Existiert erst nach `npm run build`.
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"

# Fehlercodes für Uploads -> Klartext (Frontend kann eigene Texte nutzen).
UPLOAD_ERRORS = {
    "size": "Datei zu groß — maximal 70 MB erlaubt.",
    "type": "Dateityp nicht unterstützt — erlaubt sind PNG, JPG, GIF und WebP.",
    "fields": "Bitte Spiel, Name und Seltenheit ausfüllen.",
    "noimg": "Bitte ein Bild auswählen.",
    "name": "Ungültiger Name — mindestens ein Buchstabe oder eine Ziffer nötig.",
}

# Platzhalter, solange das Frontend noch nicht gebaut wurde (frontend/dist fehlt).
PLACEHOLDER_HTML = """<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Yumikun</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0c0d11;
color:#e9ebf1;font-family:system-ui,sans-serif}.box{max-width:460px;text-align:center;padding:40px}
code{background:#181b23;padding:2px 7px;border-radius:6px;color:#c8ff4d}
a{color:#c8ff4d}</style></head><body><div class="box">
<h1>API läuft ✅</h1><p>Das Backend ist bereit, aber das React-Frontend wurde noch nicht
gebaut.</p><p>Phase 2: <code>cd frontend && npm install && npm run build</code></p>
<p style="color:#9aa1ad;font-size:.9rem">Test der API (eingeloggt):
<a href="/api/me">/api/me</a></p></div></body></html>"""

# Öffentliche Transcript-Seite. {{ }} = literale Klammern (str.format). Platzhalter:
# num, cat, server, opener, closer, when, count, body
TRANSCRIPT_PAGE = """<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ticket #{num} — Transcript</title>
<style>
:root{{--bg:#0b0b12;--surf:#15161f;--surf2:#1b1d28;--bd:#262838;--txt:#e8e8f0;--mut:#9a9ab0;--acc:#7C3AED}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--txt);font-family:system-ui,-apple-system,Segoe UI,sans-serif;line-height:1.5}}
.wrap{{max-width:840px;margin:0 auto;padding:24px 16px 80px}}
header{{background:linear-gradient(135deg,rgba(124,58,237,.25),transparent);border:1px solid var(--bd);border-radius:16px;padding:22px 24px;margin-bottom:22px}}
header h1{{margin:0 0 6px;font-size:1.5rem}}
.tag{{display:inline-block;background:var(--acc);color:#fff;border-radius:999px;padding:2px 10px;font-size:.78rem;font-weight:700;vertical-align:middle;margin-left:8px}}
.kv{{display:flex;flex-wrap:wrap;gap:6px 22px;margin-top:12px;color:var(--mut);font-size:.88rem}}
.kv b{{color:var(--txt);font-weight:600}}
.msg{{display:flex;gap:14px;padding:10px 12px;border-radius:12px}}
.msg:hover{{background:var(--surf)}}
.av{{width:42px;height:42px;border-radius:50%;flex:none;object-fit:cover;background:var(--surf2)}}
.mc{{min-width:0;flex:1}}
.meta{{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}}
.name{{font-weight:700}}
.bot{{background:var(--acc);color:#fff;border-radius:4px;font-size:.62rem;font-weight:700;padding:1px 5px;letter-spacing:.04em}}
.ts{{color:var(--mut);font-size:.76rem}}
.content{{margin-top:2px;word-wrap:break-word;overflow-wrap:anywhere}}
.content code{{background:var(--surf2);padding:1px 6px;border-radius:5px;font-size:.88em}}
.content pre{{background:var(--surf2);padding:10px 12px;border-radius:8px;overflow:auto}}
.content a{{color:#a78bfa}}
.atts{{margin-top:6px;display:flex;flex-wrap:wrap;gap:8px}}
.att-img{{max-width:320px;max-height:260px;border-radius:10px;border:1px solid var(--bd)}}
.att-file{{display:inline-block;background:var(--surf2);border:1px solid var(--bd);border-radius:8px;padding:8px 12px;color:#a78bfa;text-decoration:none}}
.empty{{color:var(--mut);text-align:center;padding:40px}}
footer{{margin-top:30px;text-align:center;color:var(--mut);font-size:.8rem}}
</style></head><body><div class="wrap">
<header>
  <h1>🎫 Ticket #{num}<span class="tag">{cat}</span></h1>
  <div class="kv">
    <span>Server: <b>{server}</b></span>
    <span>Ersteller: <b>{opener}</b></span>
    <span>Geschlossen von: <b>{closer}</b></span>
    <span>Geschlossen: <b>{when}</b></span>
    <span>Nachrichten: <b>{count}</b></span>
  </div>
</header>
{body}
<footer>Yumikun · Ticket-Transcript</footer>
</div></body></html>"""

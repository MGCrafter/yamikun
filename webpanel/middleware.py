"""aiohttp-Middlewares und kleine Response-Caches für das WebPanel."""

from __future__ import annotations

import time

from aiohttp import web

# --- Rate-Limiting (einfaches Fixed-Window pro IP) --------------------------
# Schützt OAuth- und API-Endpunkte vor Flooding. Bewusst grob: ergänzt (ersetzt
# nicht) den feineren GAME_REQUEST_COOLDOWN.
RATE_LIMITS = {
    "auth": (30, 300),
    "api": (300, 60),
}
_rate_state: dict[tuple[str, str], tuple[float, int]] = {}


def rate_bucket(path: str) -> str | None:
    if path.startswith(("/login", "/callback", "/twitch/login", "/twitch/callback")):
        return "auth"
    if path.startswith("/api/"):
        return "api"
    return None


def client_ip(request: web.Request) -> str:
    # Hinter dem CapRover-Reverse-Proxy ist die echte IP in X-Forwarded-For.
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote or "?"


@web.middleware
async def rate_limit_middleware(request: web.Request, handler):
    bucket = rate_bucket(request.path)
    if bucket is None:
        return await handler(request)
    max_req, window = RATE_LIMITS[bucket]
    now = time.time()
    key = (client_ip(request), bucket)
    start, count = _rate_state.get(key, (now, 0))
    if now - start >= window:
        start, count = now, 0
    count += 1
    _rate_state[key] = (start, count)
    # Gelegentlich abgelaufene Einträge wegräumen (begrenzt das Wachstum des Dicts).
    if len(_rate_state) > 2000:
        for k, (s, _c) in list(_rate_state.items()):
            if now - s >= 300:
                _rate_state.pop(k, None)
    if count > max_req:
        retry = max(int(window - (now - start)), 1)
        raise web.HTTPTooManyRequests(
            headers={"Retry-After": str(retry)}, text="Rate limit exceeded"
        )
    return await handler(request)


# --- Kleiner TTL-Cache für teure, reine Lese-Endpunkte ----------------------
# Schlüssel z. B. "overview:<gid>". Daten sind pro Guild gleich (nicht pro User),
# daher unbedenklich teilbar. Kurze TTL → Staleness auf wenige Sekunden begrenzt.
RESP_CACHE_TTL = 15
_resp_cache: dict[str, tuple[float, dict]] = {}


def cache_get(key: str) -> dict | None:
    hit = _resp_cache.get(key)
    if hit and time.time() - hit[0] < RESP_CACHE_TTL:
        return hit[1]
    return None


def cache_set(key: str, value: dict) -> None:
    _resp_cache[key] = (time.time(), value)


# Content-Typen, die sich für gzip lohnen (Text/Code/JSON). Bilder/Webp/Fonts
# sind bereits komprimiert und werden NICHT erneut gepackt.
COMPRESSIBLE_PREFIXES = ("text/", "application/javascript", "application/json", "application/xml")
COMPRESSIBLE_EXACT = {"application/x-javascript", "image/svg+xml"}
# FileResponse kennt seinen Content-Type erst beim prepare() – in der Middleware
# ist er noch leer. Für statische Dateien daher zusätzlich per Endung entscheiden.
COMPRESSIBLE_EXT = (".js", ".mjs", ".css", ".html", ".json", ".svg", ".map", ".xml", ".txt")


@web.middleware
async def cache_compress_middleware(request: web.Request, handler):
    """Setzt passende Cache-Control-/Security-Header und aktiviert gzip für Text/Code."""
    resp = await handler(request)
    path = request.path
    if "Cache-Control" not in resp.headers:
        if path.startswith("/appassets/"):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif path.startswith(("/assets/", "/static/")):
            resp.headers["Cache-Control"] = "public, max-age=86400"
        elif path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        elif resp.content_type == "text/html":
            resp.headers["Cache-Control"] = "no-cache"
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "img-src 'self' data: https:; "
        "font-src 'self' data: https://fonts.gstatic.com; "
        "connect-src 'self'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'",
    )
    ctype = (resp.content_type or "").lower()
    compressible = ctype.startswith(COMPRESSIBLE_PREFIXES) or ctype in COMPRESSIBLE_EXACT
    if not compressible:
        compressible = path.endswith(COMPRESSIBLE_EXT)
    if compressible:
        resp.enable_compression()
    return resp

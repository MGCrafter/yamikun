"""Reine Helper-Funktionen für WebPanel-Payloads und Validierung."""

from __future__ import annotations

import urllib.parse

from cogs.gamecards import RARITIES, RARITY_ORDER


def color_for_rarity(rarity: str) -> str:
    """Seltenheits-Farbe als #RRGGBB."""
    return f"#{RARITIES.get(rarity, RARITIES['common'])['color']:06X}"


def rarity_label(rarity: str) -> str:
    return RARITIES.get(rarity, RARITIES["common"])["label"]


def discord_avatar(user_id: int, avatar_hash: str | None) -> str:
    """Profilbild-URL aus OAuth-Daten (mit animiertem GIF-Support, sonst Default)."""
    if avatar_hash:
        ext = "gif" if avatar_hash.startswith("a_") else "png"
        return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{ext}?size=128"
    return f"https://cdn.discordapp.com/embed/avatars/{(user_id >> 22) % 6}.png"


def rarities_meta() -> list[dict]:
    """Seltenheiten in Anzeige-Reihenfolge mit Label + Farbe — für das Frontend."""
    keys = list(RARITY_ORDER) + [r for r in RARITIES if r not in RARITY_ORDER]
    return [{"key": r, "label": RARITIES[r]["label"], "color": color_for_rarity(r)} for r in keys]


def card_payload(
    cid: str,
    name: str,
    rarity: str,
    url: str | None,
    game: str | None = None,
    count: int | None = None,
) -> dict:
    payload = {
        "id": cid,
        "name": name,
        "rarity": rarity,
        "rarity_label": rarity_label(rarity),
        "color": color_for_rarity(rarity),
        "url": url,
    }
    if game is not None:
        payload["game"] = game
    if count is not None:
        payload["count"] = count
    return payload


def local_static_url(url: str | None) -> str | None:
    """Gibt lokal gehostete WebPanel-Dateien als origin-relative URL zurück.

    Ältere Karteneinträge speichern die komplette Domain in der Datenbank. Wenn
    die öffentliche Domain später wechselt, laden Browser sonst die alte URL und
    laufen in Redirect-/DNS-Probleme. Für alles unter /static/ reicht im WebPanel
    eine relative URL; externe Quellen wie Discord-CDN bleiben unverändert.
    """
    if not url:
        return url
    raw = url.strip()
    try:
        parsed = urllib.parse.urlparse(raw)
    except ValueError:
        return raw
    if parsed.path.startswith("/static/"):
        return urllib.parse.urlunparse(("", "", parsed.path, "", parsed.query, parsed.fragment))
    return raw


def is_http_url(url: str) -> bool:
    """True nur für echte http(s)-URLs (blockt javascript:/data:/file:)."""
    try:
        parsed = urllib.parse.urlparse(url.strip())
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)

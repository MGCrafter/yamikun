"""Routenregistrierung für das aiohttp-WebPanel."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aiohttp import web


def register_routes(
    app: web.Application,
    cog: Any,
    *,
    static_dir: Path,
    assets_dir: Path,
) -> None:
    """Registriert alle WebPanel-Routen in stabiler Reihenfolge.

    Der Discord-Cog bleibt Eigentümer der Handler-Methoden. Dieses Modul hält nur
    die URL-Struktur zentral, damit `cogs/webpanel.py` kleiner und übersichtlicher
    bleibt.
    """
    # --- OAuth (server-seitig, liefert Redirects/Cookies) ---
    app.add_routes([
        web.get("/login", cog.h_login),
        web.get("/callback", cog.h_callback),
        web.get("/logout", cog.h_logout),
        web.get("/t/{token}", cog.h_transcript),  # öffentliche Transcript-Ansicht
    ])

    # --- JSON-API ---
    app.add_routes([
        web.get("/api/health", cog.api_health),
        web.get("/api/me", cog.api_me),
        web.get("/api/g/{gid}/overview", cog.api_overview),
        web.get("/api/g/{gid}/cards", cog.api_cards),
        web.post("/api/g/{gid}/cards/add", cog.api_cards_add),
        web.post("/api/g/{gid}/cards/delete", cog.api_cards_delete),
        web.post("/api/g/{gid}/cards/rename", cog.api_cards_rename),
        web.post("/api/g/{gid}/cards/replace", cog.api_cards_replace),
        web.get("/api/g/{gid}/games", cog.api_games),
        web.post("/api/g/{gid}/games/add", cog.api_games_add),
        web.post("/api/g/{gid}/games/remove", cog.api_games_remove),
        web.post("/api/g/{gid}/games/alias", cog.api_games_alias),
        web.post("/api/g/{gid}/games/alias/remove", cog.api_games_alias_remove),
        web.post("/api/g/{gid}/games/request", cog.api_games_request),
        web.post("/api/g/{gid}/channel", cog.api_set_channel),
        web.get("/api/g/{gid}/yami", cog.api_yami),
        web.post("/api/g/{gid}/yami/add", cog.api_yami_add),
        web.post("/api/g/{gid}/yami/delete", cog.api_yami_delete),
        web.post("/api/g/{gid}/yami/replace", cog.api_yami_replace),
        web.get("/api/g/{gid}/economy", cog.api_economy),
        web.post("/api/g/{gid}/economy/coins", cog.api_economy_coins),
        web.get("/api/g/{gid}/inventory", cog.api_inventory),
        web.get("/api/g/{gid}/inventory/user/{uid}", cog.api_inventory_user),
        web.post("/api/g/{gid}/inventory/remove", cog.api_inventory_remove),
        web.get("/api/g/{gid}/reactionroles", cog.api_reactionroles),
        web.post("/api/g/{gid}/reactionroles/add", cog.api_reactionroles_add),
        web.post("/api/g/{gid}/reactionroles/delete", cog.api_reactionroles_delete),
        web.get("/api/g/{gid}/welcome", cog.api_welcome),
        web.post("/api/g/{gid}/welcome", cog.api_welcome_save),
        web.get("/api/g/{gid}/autoroles", cog.api_autoroles),
        web.post("/api/g/{gid}/autoroles", cog.api_autoroles_save),
        web.post("/api/g/{gid}/welcome/upload", cog.api_welcome_upload),
        web.post("/api/g/{gid}/welcome/image", cog.api_welcome_image),
        web.get("/api/g/{gid}/boost", cog.api_boost),
        web.post("/api/g/{gid}/boost", cog.api_boost_save),
        web.post("/api/g/{gid}/boost/upload", cog.api_boost_upload),
        web.post("/api/g/{gid}/boost/image", cog.api_boost_image),
        web.get("/api/g/{gid}/twitch", cog.api_twitch),
        web.post("/api/g/{gid}/twitch", cog.api_twitch_save),
        web.get("/api/g/{gid}/automod", cog.api_automod),
        web.post("/api/g/{gid}/automod", cog.api_automod_save),
        web.get("/api/g/{gid}/voice", cog.api_voice),
        web.post("/api/g/{gid}/voice", cog.api_voice_save),
        web.get("/api/g/{gid}/audit", cog.api_audit),
        web.post("/api/g/{gid}/audit/settings", cog.api_audit_settings),
        web.post("/api/g/{gid}/audit/channel", cog.api_audit_channel),
        web.post("/api/g/{gid}/audit/clear", cog.api_audit_clear),
        web.get("/api/g/{gid}/tickets", cog.api_tickets),
        web.post("/api/g/{gid}/tickets/config", cog.api_tickets_config),
        web.post("/api/g/{gid}/tickets/panel", cog.api_tickets_panel),
        web.post("/api/g/{gid}/tickets/disable", cog.api_tickets_disable),
        web.post("/api/g/{gid}/tickets/category/add", cog.api_tickets_cat_add),
        web.post("/api/g/{gid}/tickets/category/remove", cog.api_tickets_cat_remove),
        web.get("/api/g/{gid}/levelup", cog.api_levelup),
        web.post("/api/g/{gid}/levelup", cog.api_levelup_save),
        web.get("/api/g/{gid}/botprofile", cog.api_botprofile),
        web.post("/api/g/{gid}/botprofile/nick", cog.api_botprofile_nick),
        web.post("/api/g/{gid}/botprofile/avatar", cog.api_botprofile_avatar),
        web.post("/api/g/{gid}/botprofile/avatar/remove", cog.api_botprofile_avatar_remove),
        web.get("/api/g/{gid}/announce", cog.api_announce),
        web.post("/api/g/{gid}/announce/send", cog.api_announce_send),
        web.post("/api/g/{gid}/announce/edit", cog.api_announce_edit),
        web.post("/api/g/{gid}/announce/delete", cog.api_announce_delete),
        # --- User-Dashboard (eigene Daten, kein Admin nötig) ---
        web.get("/api/u/{gid}/dashboard", cog.api_user_dashboard),
        web.get("/api/u/{gid}/achievements", cog.api_user_achievements),
        web.post("/api/u/{gid}/fuse", cog.api_user_fuse),
        web.post("/api/u/{gid}/cards/dismantle", cog.api_user_card_dismantle),
        web.post("/api/u/{gid}/boosters/exchange", cog.api_user_booster_exchange),
        web.post("/api/u/{gid}/feedback", cog.api_user_feedback),
    ])

    # --- Statische Dateien (Karten-Bilder + Bot-Logo) ---
    app.router.add_static("/static/", path=str(static_dir))
    if assets_dir.is_dir():
        app.router.add_static("/assets/", path=str(assets_dir))

    # --- SPA-Fallback (muss ZULETZT registriert werden) ---
    app.router.add_get("/", cog.h_spa)
    app.router.add_get("/{tail:.*}", cog.h_spa)

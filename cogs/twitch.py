"""Twitch-Live-Benachrichtigungen über die Twitch-Helix-API.

Die Konfiguration liegt pro Discord-Server im WebPanel. Der Cog pollt nur
aktivierte Einträge und meldet einen Stream genau einmal je Twitch-Stream-ID.
Twitch-Credentials bleiben ausschließlich in Umgebungsvariablen:
TWITCH_CLIENT_ID und TWITCH_CLIENT_SECRET.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import aiohttp
import discord
from discord.ext import commands, tasks

logger = logging.getLogger("oaken-tower-bot")

TWITCH_OAUTH_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_STREAMS_URL = "https://api.twitch.tv/helix/streams"
DEFAULT_TWITCH_MESSAGE = "{streamer} ist jetzt live auf Twitch!\n{title}\n{url}"
TWITCH_PLACEHOLDERS = ("{streamer}", "{title}", "{game}", "{url}")


def normalize_login(value: str) -> str | None:
    """Akzeptiert Twitch-Login oder Kanal-URL und liefert den Twitch-Login.

    Die Helix-API kennt nur den Login-Namen, deshalb wird aus einer URL immer
    der Kanalname extrahiert. Erlaubt sind http/https, die Subdomains www/m/go
    sowie Zusätze wie ``?lang=de`` oder ``/videos``.
    """
    raw = value.strip().lower()
    for scheme in ("https://", "http://", "//"):
        if raw.startswith(scheme):
            raw = raw[len(scheme):]
            break
    host, _, path = raw.partition("/")
    for subdomain in ("www.", "m.", "go."):
        if host.startswith(subdomain):
            host = host[len(subdomain):]
            break
    if host == "twitch.tv":
        raw = path
    elif "." in host:
        # Ein fremder Host ist kein Twitch-Kanal.
        return None
    # Nur der erste Pfadabschnitt ist der Kanalname (z. B. /videos, /about).
    raw = raw.split("?")[0].split("#")[0].strip("/").split("/")[0]
    if not raw or len(raw) > 25 or not raw.isascii() or not all(ch.isalnum() or ch == "_" for ch in raw):
        return None
    return raw


def render_twitch(template: str | None, stream: dict[str, Any], login: str) -> str:
    """Ersetzt bewusst nur bekannte Tokens, damit Text mit Klammern sicher bleibt."""
    text = template or DEFAULT_TWITCH_MESSAGE
    values = {
        "{streamer}": str(stream.get("user_name") or login),
        "{title}": str(stream.get("title") or "Live auf Twitch"),
        "{game}": str(stream.get("game_name") or "Twitch"),
        "{url}": f"https://twitch.tv/{login}",
    }
    for key, value in values.items():
        text = text.replace(key, value)
    return text


class TwitchCog(commands.Cog):
    """Fragt Twitch im Minutentakt ab und postet Live-Embeds in Discord."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]
        self._session: aiohttp.ClientSession | None = None
        self._access_token: str | None = None
        self._token_expires_at = 0.0

    async def cog_load(self) -> None:
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        self.poll_streams.start()

    async def cog_unload(self) -> None:
        self.poll_streams.cancel()
        if self._session and not self._session.closed:
            await self._session.close()

    @tasks.loop(minutes=1)
    async def poll_streams(self) -> None:
        configs = self.db.list_twitch_configs()
        if not configs:
            return
        if not os.environ.get("TWITCH_CLIENT_ID") or not os.environ.get("TWITCH_CLIENT_SECRET"):
            logger.warning("Twitch: Konfiguration vorhanden, aber TWITCH_CLIENT_ID/SECRET fehlen.")
            return
        try:
            token = await self._get_token()
        except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError):
            logger.exception("Twitch: OAuth-Token konnte nicht geladen werden.")
            return
        # Fetch each Twitch login only once, even when several guilds follow it.
        logins = list(dict.fromkeys(cfg["login"] for cfg in configs))
        for start in range(0, len(logins), 100):
            batch = logins[start:start + 100]
            try:
                streams = await self._helix_get(TWITCH_STREAMS_URL, token, params=[
                    ("first", "100"), *[("user_login", login) for login in batch],
                ])
            except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError):
                logger.exception("Twitch: Live-Abfrage fehlgeschlagen.")
                continue
            by_login = {stream["user_login"].lower(): stream for stream in streams}
            for cfg in configs:
                if cfg["login"] not in batch:
                    continue
                # Settings may have changed while the Twitch request was pending.
                current = self.db.get_twitch_config(cfg["guild_id"])
                if not current["enabled"] or current["login"] != cfg["login"]:
                    continue
                try:
                    await self._check_config({**current, "guild_id": cfg["guild_id"]}, by_login.get(cfg["login"]))
                except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError):
                    logger.exception("Twitch: Prüfung für Guild %s fehlgeschlagen.", cfg["guild_id"])

    @poll_streams.before_loop
    async def _before_poll(self) -> None:
        await self.bot.wait_until_ready()

    async def _get_token(self) -> str:
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token
        if self._session is None:
            raise RuntimeError("Twitch HTTP session is not ready")
        payload = {
            "client_id": os.environ["TWITCH_CLIENT_ID"],
            "client_secret": os.environ["TWITCH_CLIENT_SECRET"],
            "grant_type": "client_credentials",
        }
        async with self._session.post(TWITCH_OAUTH_URL, data=payload) as response:
            response.raise_for_status()
            data = await response.json()
        token = str(data.get("access_token") or "")
        if not token:
            raise RuntimeError("Twitch OAuth response has no access token")
        self._access_token = token
        self._token_expires_at = time.time() + int(data.get("expires_in") or 0)
        return token

    async def _helix_get(self, url: str, token: str, *, params: list[tuple[str, str]]) -> list[dict[str, Any]]:
        if self._session is None:
            raise RuntimeError("Twitch HTTP session is not ready")
        for attempt in range(2):
            headers = {
                "Client-Id": os.environ["TWITCH_CLIENT_ID"],
                "Authorization": f"Bearer {self._access_token or token}",
            }
            async with self._session.get(url, headers=headers, params=params) as response:
                if response.status == 401 and not attempt:
                    self._access_token = None
                    self._token_expires_at = 0
                else:
                    response.raise_for_status()
                    result = await response.json()
                    rows = result.get("data") if isinstance(result, dict) else None
                    if not isinstance(rows, list) or any(
                        not isinstance(row, dict) or not isinstance(row.get("user_login"), str) for row in rows
                    ):
                        raise RuntimeError("Twitch streams response is invalid")
                    return rows
            token = await self._get_token()
        raise RuntimeError("Twitch authentication failed")

    async def _check_config(self, cfg: dict[str, Any], stream: dict[str, Any] | None) -> None:
        if not stream:
            # Keep the last delivered ID across offline gaps and restarts.
            # A genuinely new stream has a new ID; an empty response isn't a reset.
            return
        stream_id = str(stream.get("id") or "")
        if not stream_id or stream_id == cfg["last_stream_id"]:
            return
        delivered = await self._announce(cfg, stream)
        # Nur eine erfolgreiche Discord-Zustellung merkt sich die Stream-ID.
        # Bei temporären Rechte-/Netzwerkfehlern versucht der nächste Poll erneut.
        if delivered:
            self.db.set_twitch_last_stream_id(cfg["guild_id"], stream_id)

    async def _announce(self, cfg: dict[str, Any], stream: dict[str, Any]) -> bool:
        guild = self.bot.get_guild(cfg["guild_id"])
        if guild is None:
            logger.warning("Twitch: Guild %s nicht im Cache.", cfg["guild_id"])
            return False
        channel = guild.get_channel(cfg["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            logger.warning("Twitch: Ziel-Channel %s nicht verfügbar (Guild %s).", cfg["channel_id"], guild.id)
            return False
        me = guild.me
        if me is None or not channel.permissions_for(me).send_messages:
            logger.warning("Twitch: Keine Schreibrechte in Channel %s (Guild %s).", channel.id, guild.id)
            return False
        login = cfg["login"]
        url = f"https://twitch.tv/{login}"
        game = str(stream.get("game_name") or "Twitch")
        embed = discord.Embed(
            title=f"🔴 {stream.get('user_name') or login} ist live!"[:256],
            url=url,
            description=render_twitch(cfg["message"], stream, login)[:4096],
            color=0x9146FF,
        )
        embed.add_field(name="Kategorie", value=game[:1024], inline=True)
        thumbnail = str(stream.get("thumbnail_url") or "").replace("{width}", "1280").replace("{height}", "720")
        if thumbnail:
            embed.set_image(url=thumbnail)
        embed.set_footer(text="Twitch Live")

        role = guild.get_role(cfg["mention_role_id"]) if cfg["mention_role_id"] else None
        content = role.mention if role else None
        mentions = discord.AllowedMentions(roles=[role]) if role else discord.AllowedMentions.none()
        try:
            await channel.send(content=content, embed=embed, allowed_mentions=mentions)
            return True
        except discord.Forbidden:
            logger.warning("Twitch: Forbidden beim Senden nach Channel %s.", channel.id)
        except discord.HTTPException:
            logger.exception("Twitch: Discord-Nachricht konnte nicht gesendet werden.")
        return False


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TwitchCog(bot))

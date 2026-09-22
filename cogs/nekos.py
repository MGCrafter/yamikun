"""Robuster Abruf von nekos.best-GIFs als Discord-Anhang.

nekos.best verlangt einen identifizierenden User-Agent. Die GIF-URL wird außerdem
heruntergeladen, statt sie Discord als externe Embed-URL zu überlassen: Discords
Bild-Proxy verwendet einen eigenen User-Agent, den nekos.best derzeit blockiert.
"""

from __future__ import annotations

import io
import os
from typing import Optional

import aiohttp
import discord

NEKOS_API_URL = "https://nekos.best/api/v2/{}"
DEFAULT_NEKOS_USER_AGENT = "YamiKun (https://yamikun.eu)"
NEKOS_USER_AGENT = (
    os.environ.get("NEKOS_USER_AGENT", "").strip() or DEFAULT_NEKOS_USER_AGENT
)
MAX_GIF_BYTES = 8 * 1024 * 1024


async def fetch_gif_file(
    session: aiohttp.ClientSession,
    category: str,
    *,
    filename: str = "reaction.gif",
) -> Optional[discord.File]:
    """Lädt ein GIF mit gültigem User-Agent und liefert es als Discord-Datei."""
    headers = {"User-Agent": NEKOS_USER_AGENT}
    timeout = aiohttp.ClientTimeout(total=15)

    async with session.get(
        NEKOS_API_URL.format(category), headers=headers, timeout=timeout
    ) as response:
        response.raise_for_status()
        payload = await response.json()

    url = payload["results"][0]["url"]
    async with session.get(url, headers=headers, timeout=timeout) as response:
        response.raise_for_status()
        body = await response.read()
        content_type = getattr(response, "content_type", "")

    if not body or len(body) > MAX_GIF_BYTES or not content_type.startswith("image/"):
        return None
    return discord.File(io.BytesIO(body), filename=filename)

"""Resolve the bot login with app credentials; prints only its public Twitch ID."""
import argparse
import asyncio
import os
import re

import aiohttp
from dotenv import load_dotenv


async def main(login):
    load_dotenv()
    client_id, secret = os.getenv("TWITCH_CLIENT_ID"), os.getenv("TWITCH_CLIENT_SECRET")
    if not client_id or not secret:
        raise SystemExit("TWITCH_CLIENT_ID und TWITCH_CLIENT_SECRET fehlen.")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as http:
        async with http.post("https://id.twitch.tv/oauth2/token", data={"client_id": client_id, "client_secret": secret, "grant_type": "client_credentials"}) as response:
            if response.status != 200:
                raise SystemExit(f"Twitch-Anmeldung fehlgeschlagen (HTTP {response.status}).")
            token = (await response.json())["access_token"]
        async with http.get("https://api.twitch.tv/helix/users", params={"login": login}, headers={"Client-Id": client_id, "Authorization": "Bearer " + token}) as response:
            if response.status != 200:
                raise SystemExit(f"Twitch-Abfrage fehlgeschlagen (HTTP {response.status}).")
            users = (await response.json()).get("data", [])
            if not users:
                raise SystemExit("Twitch-Konto nicht gefunden.")
            print("TWITCH_BOT_USER_ID=" + users[0]["id"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("login", help="Login-Name des Twitch-Botkontos")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9_]{1,25}", args.login):
        parser.error("Bitte nur den Twitch-Login-Namen angeben, keine URL.")
    try:
        asyncio.run(main(args.login))
    except (aiohttp.ClientError, asyncio.TimeoutError):
        raise SystemExit("Twitch ist nicht erreichbar. Bitte später erneut versuchen.") from None

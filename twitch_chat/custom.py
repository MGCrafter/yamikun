"""Plain-text custom commands: validation, permissions and literal substitution."""
from __future__ import annotations

import re
import unicodedata

BUILTIN_NAMES = frozenset({
    "help", "commands", "coins", "balance", "daily", "pay", "leaderboard", "top",
    "hug", "pat", "kiss", "slap", "highfive", "friend", "marry", "marriages", "divorce",
    "coinflip", "cf", "slots", "roulette", "blackjack", "bj", "blackjackduel",
    "hit", "stand", "double", "split", "link",
})
LEVELS = ("everyone", "subscriber", "vip", "moderator", "broadcaster")
NAME = re.compile(r"[a-z0-9][a-z0-9_]{0,24}\Z")
PLACEHOLDER = re.compile(r"\{(user|channel|target|args)\}")


def validate_commands(commands):
    if not isinstance(commands, list) or len(commands) > 50:
        raise ValueError("custom_commands")
    names, ids, cleaned = set(BUILTIN_NAMES), set(), []
    for item in commands:
        if not isinstance(item, dict) or set(item) != {
            "id", "name", "response", "enabled", "aliases", "user_level", "cooldown", "user_cooldown",
        }:
            raise ValueError("custom_commands")
        cid = item["id"]
        if not isinstance(cid, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", cid) or cid in ids:
            raise ValueError("custom_commands")
        ids.add(cid)
        if type(item["enabled"]) is not bool or item["user_level"] not in LEVELS:
            raise ValueError("custom_commands")
        for key, high in (("cooldown", 3600), ("user_cooldown", 86400)):
            if type(item[key]) is not int or not 0 <= item[key] <= high:
                raise ValueError("custom_commands")
        response = item["response"]
        if (not isinstance(response, str) or not 1 <= len(response.strip()) <= 500
                or not "".join(c for c in response if unicodedata.category(c) != "Cf").strip()
                or any(ord(c) < 32 or ord(c) == 127 for c in response)):
            raise ValueError("custom_commands")
        if not isinstance(item["aliases"], list) or len(item["aliases"]) > 5:
            raise ValueError("custom_commands")
        triggers = []
        for raw in [item["name"], *item["aliases"]]:
            name = raw.strip().lower() if isinstance(raw, str) else ""
            if not NAME.fullmatch(name) or name in names:
                raise ValueError("custom_commands")
            names.add(name)
            triggers.append(name)
        cleaned.append({**item, "name": triggers[0], "aliases": triggers[1:], "response": response.strip()})
    return cleaned


def permitted(command, event):
    badges = {b.get("set_id") for b in event.get("badges", [])}
    if event["chatter_user_id"] == event["broadcaster_user_id"]:
        level = 4
    elif "moderator" in badges:
        level = 3
    elif "vip" in badges:
        level = 2
    elif badges & {"subscriber", "founder"}:
        level = 1
    else:
        level = 0
    return level >= LEVELS.index(command["user_level"])


def render_response(template, *, user, channel, args):
    target = args[0].lstrip("@").lower() if args else user
    if not NAME.fullmatch(target):
        target = user
    values = {"user": "@" + user, "channel": channel, "target": "@" + target, "args": " ".join(args)}
    # One pass: user input cannot recursively expand placeholders or execute code.
    return PLACEHOLDER.sub(lambda match: values[match[1]], template)[:500]

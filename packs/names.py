"""Telegram set names: letters, digits and single underscores, ending in the bot suffix."""

import hashlib
import re

MAX_NAME = 64

_BASE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def suffix_for(bot_username: str) -> str:
    return f"_by_{bot_username}"


def room_for(bot_username: str) -> int:
    return MAX_NAME - len(suffix_for(bot_username))


def check_base(base: str, bot_username: str) -> tuple[str, dict] | None:
    """Return the key of why this prefix is unusable, or None when it is fine."""
    room = room_for(bot_username)
    if not base:
        return "prefix.empty", {}
    if len(base) > room:
        return "prefix.too_long", {"room": room}
    if not _BASE.match(base):
        return "prefix.charset", {}
    if "__" in base or base.endswith("_"):
        return "prefix.underscores", {}
    return None


def build_name(base: str, bot_username: str) -> str:
    return base + suffix_for(bot_username)




def tag_for(name: str) -> str:
    """A short stable handle for callback data, where the full set name does not fit."""
    return hashlib.sha1(name.encode()).hexdigest()[:10]

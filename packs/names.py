"""Telegram set names: letters, digits and single underscores, ending in the bot suffix."""

import hashlib
import re

MAX_NAME = 64

_BASE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def suffix_for(bot_username: str) -> str:
    return f"_by_{bot_username}"


def room_for(bot_username: str) -> int:
    return MAX_NAME - len(suffix_for(bot_username))


def check_base(base: str, bot_username: str) -> str | None:
    """Return why this prefix is unusable, or None when it is fine."""
    room = room_for(bot_username)
    if not base:
        return "Send a prefix for the link."
    if len(base) > room:
        return f"Too long, keep it to {room} characters."
    if not _BASE.match(base):
        return "Letters, digits and underscores only, starting with a letter."
    if "__" in base or base.endswith("_"):
        return "No doubled or trailing underscores."
    return None


def build_name(base: str, bot_username: str) -> str:
    return base + suffix_for(bot_username)




def tag_for(name: str) -> str:
    """A short stable handle for callback data, where the full set name does not fit."""
    return hashlib.sha1(name.encode()).hexdigest()[:10]

"""Telegram set names: letters, digits and single underscores, ending in the bot suffix."""

import re
import secrets
import unicodedata

MAX_NAME = 64
RANDOM_LEN = 5
FALLBACK_SLUG = "pack"

_ALLOWED = re.compile(r"[^a-z0-9]+")
_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"


def _slug(title: str) -> str:
    folded = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = _ALLOWED.sub("_", folded.lower()).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    if not slug or not slug[0].isalpha():
        slug = f"{FALLBACK_SLUG}_{slug}".strip("_")
    return slug


def _token() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(RANDOM_LEN))


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


def pack_name(title: str, bot_username: str) -> str:
    """Build a globally unique set name for this bot from a human title."""
    suffix = f"_by_{bot_username}"
    token = _token()
    room = MAX_NAME - len(suffix) - len(token) - 1
    if room < 1:
        raise ValueError(f"bot username {bot_username!r} leaves no room for a name")

    slug = _slug(title)[:room].strip("_")
    if not slug or not slug[0].isalpha():
        slug = FALLBACK_SLUG[:room]
    return f"{slug}_{token}{suffix}"

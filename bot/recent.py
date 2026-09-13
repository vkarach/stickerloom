"""Converted files the user may still want to hand to @Stickers, keyed by a short token."""

import secrets
from collections import OrderedDict
from dataclasses import dataclass

MAX_REMEMBERED = 500


@dataclass(frozen=True)
class Delivered:
    user_id: int
    file_id: str
    name: str
    emoji: str | None


class RecentFiles:
    def __init__(self, limit: int = MAX_REMEMBERED):
        self._items: OrderedDict[str, Delivered] = OrderedDict()
        self._limit = limit

    def reserve(self) -> str:
        return secrets.token_urlsafe(8)

    def store(self, token: str, item: Delivered) -> None:
        self._items[token] = item
        self._items.move_to_end(token)
        while len(self._items) > self._limit:
            self._items.popitem(last=False)

    def get(self, token: str, user_id: int) -> Delivered | None:
        item = self._items.get(token)
        return item if item and item.user_id == user_id else None

    def latest_for(self, user_id: int, limit: int = 10) -> list[Delivered]:
        found = [item for item in reversed(self._items.values()) if item.user_id == user_id]
        return found[:limit]


recent = RecentFiles()

import logging
from datetime import datetime, timezone

from models import Pack

log = logging.getLogger(__name__)

DEFAULT_EMOJI = "\u2b50"


class PackRepo:
    _ENSURE_USER = "INSERT INTO users (user_id) VALUES (?) ON CONFLICT DO NOTHING"

    _REMEMBER = (
        "INSERT INTO packs (user_id, name, title, created_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT DO NOTHING"
    )
    _LIST = (
        "SELECT user_id, name, title, created_at FROM packs "
        "WHERE user_id = ? ORDER BY created_at, rowid"
    )
    _FIND = "SELECT user_id, name, title, created_at FROM packs WHERE user_id = ? AND name = ?"

    _SET_ACTIVE = "UPDATE users SET active_pack = ? WHERE user_id = ?"
    _GET_ACTIVE = "SELECT active_pack FROM users WHERE user_id = ?"

    _SET_PENDING = "UPDATE users SET pending_title = ? WHERE user_id = ?"
    _GET_PENDING = "SELECT pending_title FROM users WHERE user_id = ?"
    _CLEAR_PENDING = "UPDATE users SET pending_title = NULL WHERE user_id = ?"

    _SET_EMOJI = "UPDATE users SET emoji = ? WHERE user_id = ?"
    _GET_EMOJI = "SELECT emoji FROM users WHERE user_id = ?"

    def __init__(self, conn):
        self._conn = conn

    async def _ensure(self, user_id: int) -> None:
        await self._conn.execute(self._ENSURE_USER, (user_id,))

    async def remember(self, user_id: int, name: str, title: str) -> Pack:
        created = datetime.now(timezone.utc).isoformat()
        await self._ensure(user_id)
        await self._conn.execute(self._REMEMBER, (user_id, name, title, created))
        await self._conn.commit()
        log.info("user %s owns pack %s", user_id, name)
        return Pack(user_id=user_id, name=name, title=title, created_at=created)

    async def list_for(self, user_id: int) -> list[Pack]:
        async with self._conn.execute(self._LIST, (user_id,)) as cursor:
            rows = await cursor.fetchall()
        return [Pack(r["user_id"], r["name"], r["title"], r["created_at"]) for r in rows]

    async def find(self, user_id: int, name: str) -> Pack | None:
        async with self._conn.execute(self._FIND, (user_id, name)) as cursor:
            row = await cursor.fetchone()
        return Pack(row["user_id"], row["name"], row["title"], row["created_at"]) if row else None

    async def set_active(self, user_id: int, name: str) -> None:
        await self._ensure(user_id)
        await self._conn.execute(self._SET_ACTIVE, (name, user_id))
        await self._conn.commit()

    async def active_for(self, user_id: int) -> str | None:
        async with self._conn.execute(self._GET_ACTIVE, (user_id,)) as cursor:
            row = await cursor.fetchone()
        return row["active_pack"] if row else None

    async def clear_active(self, user_id: int) -> None:
        await self._ensure(user_id)
        await self._conn.execute(self._SET_ACTIVE, (None, user_id))
        await self._conn.commit()

    async def set_pending(self, user_id: int, title: str) -> None:
        await self._ensure(user_id)
        await self._conn.execute(self._SET_PENDING, (title, user_id))
        await self._conn.commit()

    async def take_pending(self, user_id: int) -> str | None:
        async with self._conn.execute(self._GET_PENDING, (user_id,)) as cursor:
            row = await cursor.fetchone()
        title = row["pending_title"] if row else None
        if title is not None:
            await self._conn.execute(self._CLEAR_PENDING, (user_id,))
            await self._conn.commit()
        return title

    async def set_emoji(self, user_id: int, emoji: str) -> None:
        await self._ensure(user_id)
        await self._conn.execute(self._SET_EMOJI, (emoji, user_id))
        await self._conn.commit()

    async def emoji_for(self, user_id: int) -> str:
        async with self._conn.execute(self._GET_EMOJI, (user_id,)) as cursor:
            row = await cursor.fetchone()
        return (row["emoji"] if row else None) or DEFAULT_EMOJI

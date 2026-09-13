import logging
from datetime import datetime, timezone

from models import Pack, QueuedSticker
from packs.names import tag_for

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
    _FORGET = "DELETE FROM packs WHERE user_id = ? AND name = ?"

    _SET_ACTIVE = "UPDATE users SET active_pack = ? WHERE user_id = ?"
    _GET_ACTIVE = "SELECT active_pack FROM users WHERE user_id = ?"

    _SET_PENDING = "UPDATE users SET pending_title = ? WHERE user_id = ?"
    _GET_PENDING = "SELECT pending_title FROM users WHERE user_id = ?"

    _SET_ASKING = "UPDATE users SET asking = ? WHERE user_id = ?"
    _GET_ASKING = "SELECT asking FROM users WHERE user_id = ?"

    _SET_BUILDING = "UPDATE users SET building = ? WHERE user_id = ?"
    _GET_BUILDING = "SELECT building FROM users WHERE user_id = ?"

    _SET_DELETING = "UPDATE users SET deleting = ? WHERE user_id = ?"
    _GET_DELETING = "SELECT deleting FROM users WHERE user_id = ?"

    _SET_EDITING_PACK = "UPDATE users SET editing_pack = ? WHERE user_id = ?"
    _GET_EDITING_PACK = "SELECT editing_pack FROM users WHERE user_id = ?"

    _SET_IMPORTING = "UPDATE users SET importing = ? WHERE user_id = ?"
    _GET_IMPORTING = "SELECT importing FROM users WHERE user_id = ?"

    _SET_EDITING = "UPDATE users SET editing = ? WHERE user_id = ?"
    _GET_EDITING = "SELECT editing FROM users WHERE user_id = ?"

    _SET_LANG = "UPDATE users SET lang = ? WHERE user_id = ?"
    _GET_LANG = "SELECT lang FROM users WHERE user_id = ?"

    _SET_EMOJI = "UPDATE users SET emoji = ? WHERE user_id = ?"
    _GET_EMOJI = "SELECT emoji FROM users WHERE user_id = ?"

    _PUSH_STICKER = (
        "INSERT INTO queued_stickers (user_id, file_id, name, suggested, source_msg, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)"
    )
    _SET_PROMPT = "UPDATE queued_stickers SET prompt_msg = ? WHERE id = ?"
    _CLAIM_PROMPT = (
        "UPDATE queued_stickers SET prompt_msg = 0 WHERE id = ? AND prompt_msg IS NULL"
    )
    _RELEASE_PROMPT = "UPDATE queued_stickers SET prompt_msg = NULL WHERE id = ?"
    _ATTACH = "UPDATE queued_stickers SET file_id = ?, sha = ? WHERE id = ?"

    _REMEMBER_SHA = "INSERT INTO pack_stickers (name, sha) VALUES (?, ?) ON CONFLICT DO NOTHING"
    _HAS_SHA = "SELECT 1 FROM pack_stickers WHERE name = ? AND sha = ?"
    _QUEUED_SHAS = (
        "SELECT sha FROM queued_stickers WHERE user_id = ? AND sha IS NOT NULL AND id <> ?"
    )
    _FORGET_SHAS = "DELETE FROM pack_stickers WHERE name = ?"
    _HEAD_STICKER = (
        "SELECT id, user_id, file_id, name, suggested, emoji, source_msg, prompt_msg, sha "
        "FROM queued_stickers "
        "WHERE user_id = ? AND emoji IS NULL ORDER BY id LIMIT 1"
    )
    _READY_STICKERS = (
        "SELECT id, user_id, file_id, name, suggested, emoji, source_msg, prompt_msg, sha "
        "FROM queued_stickers "
        "WHERE user_id = ? AND emoji IS NOT NULL AND dup = 0 ORDER BY id"
    )
    _NAME_STICKER = "UPDATE queued_stickers SET emoji = ? WHERE id = ?"
    _MARK_DUP = "UPDATE queued_stickers SET emoji = ?, dup = 1 WHERE id = ?"
    _CLEAR_DUP = "UPDATE queued_stickers SET dup = 0 WHERE id = ?"
    _FIRST_DUP = (
        "SELECT id, user_id, file_id, name, suggested, emoji, source_msg, prompt_msg, sha "
        "FROM queued_stickers WHERE user_id = ? AND dup = 1 ORDER BY id LIMIT 1"
    )
    _POP_STICKER = "DELETE FROM queued_stickers WHERE id = ?"
    _COUNT_STICKERS = (
        "SELECT COUNT(*) AS n FROM queued_stickers WHERE user_id = ? AND emoji IS NULL"
    )
    _COUNT_ALL = "SELECT COUNT(*) AS n FROM queued_stickers WHERE user_id = ?"
    _CLEAR_STICKERS = "DELETE FROM queued_stickers WHERE user_id = ?"

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
        stored = await self.find(user_id, name)
        return stored or Pack(user_id, name, title, created)

    async def list_for(self, user_id: int) -> list[Pack]:
        async with self._conn.execute(self._LIST, (user_id,)) as cursor:
            rows = await cursor.fetchall()
        return [_pack(row) for row in rows]

    async def find(self, user_id: int, name: str) -> Pack | None:
        async with self._conn.execute(self._FIND, (user_id, name)) as cursor:
            row = await cursor.fetchone()
        return _pack(row) if row else None

    async def forget(self, user_id: int, name: str) -> None:
        await self._conn.execute(self._FORGET, (user_id, name))
        await self._conn.execute(self._FORGET_SHAS, (name,))
        await self._conn.commit()
        log.info("user %s no longer owns pack %s", user_id, name)

    async def find_by_tag(self, user_id: int, tag: str) -> Pack | None:
        """Callbacks carry a tag, not a name: a set name does not fit in 64 bytes."""
        return next((p for p in await self.list_for(user_id) if tag_for(p.name) == tag), None)

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

    async def peek_pending(self, user_id: int) -> str | None:
        async with self._conn.execute(self._GET_PENDING, (user_id,)) as cursor:
            row = await cursor.fetchone()
        return row["pending_title"] if row else None

    async def set_asking(self, user_id: int, kind: str | None) -> None:
        """Remember what the next plain message answers: a pack name, or a link prefix."""
        await self._ensure(user_id)
        await self._conn.execute(self._SET_ASKING, (kind, user_id))
        await self._conn.commit()

    async def asking_for(self, user_id: int) -> str | None:
        async with self._conn.execute(self._GET_ASKING, (user_id,)) as cursor:
            row = await cursor.fetchone()
        return row["asking"] if row else None

    async def set_building(self, user_id: int, building: bool) -> None:
        await self._ensure(user_id)
        await self._conn.execute(self._SET_BUILDING, (int(building), user_id))
        await self._conn.commit()

    async def is_building(self, user_id: int) -> bool:
        async with self._conn.execute(self._GET_BUILDING, (user_id,)) as cursor:
            row = await cursor.fetchone()
        return bool(row["building"]) if row else False

    async def set_deleting(self, user_id: int, name: str | None) -> None:
        await self._ensure(user_id)
        await self._conn.execute(self._SET_DELETING, (name, user_id))
        await self._conn.commit()

    async def deleting_for(self, user_id: int) -> str | None:
        async with self._conn.execute(self._GET_DELETING, (user_id,)) as cursor:
            row = await cursor.fetchone()
        return row["deleting"] if row else None

    async def set_editing_pack(self, user_id: int, name: str | None) -> None:
        """The pack whose stickers the user is picking from, by button or by sending one."""
        await self._ensure(user_id)
        await self._conn.execute(self._SET_EDITING_PACK, (name, user_id))
        await self._conn.commit()

    async def editing_pack_for(self, user_id: int) -> str | None:
        async with self._conn.execute(self._GET_EDITING_PACK, (user_id,)) as cursor:
            row = await cursor.fetchone()
        return row["editing_pack"] if row else None

    async def set_importing(self, user_id: int, source: str | None) -> None:
        await self._ensure(user_id)
        await self._conn.execute(self._SET_IMPORTING, (source, user_id))
        await self._conn.commit()

    async def importing_for(self, user_id: int) -> str | None:
        async with self._conn.execute(self._GET_IMPORTING, (user_id,)) as cursor:
            row = await cursor.fetchone()
        return row["importing"] if row else None

    async def set_editing(self, user_id: int, file_id: str | None) -> None:
        await self._ensure(user_id)
        await self._conn.execute(self._SET_EDITING, (file_id, user_id))
        await self._conn.commit()

    async def editing_for(self, user_id: int) -> str | None:
        async with self._conn.execute(self._GET_EDITING, (user_id,)) as cursor:
            row = await cursor.fetchone()
        return row["editing"] if row else None

    async def set_lang(self, user_id: int, lang: str) -> None:
        await self._ensure(user_id)
        await self._conn.execute(self._SET_LANG, (lang, user_id))
        await self._conn.commit()

    async def lang_for(self, user_id: int) -> str | None:
        async with self._conn.execute(self._GET_LANG, (user_id,)) as cursor:
            row = await cursor.fetchone()
        return row["lang"] if row else None

    async def set_emoji(self, user_id: int, emoji: str) -> None:
        await self._ensure(user_id)
        await self._conn.execute(self._SET_EMOJI, (emoji, user_id))
        await self._conn.commit()

    async def push_sticker(self, user_id: int, file_id: str | None, name: str,
                           suggested: str | None, source_msg: int | None = None) -> int:
        """Reserve the sticker's place in the queue; file_id lands once it is converted."""
        created = datetime.now(timezone.utc).isoformat()
        await self._ensure(user_id)
        cursor = await self._conn.execute(
            self._PUSH_STICKER, (user_id, file_id, name, suggested, source_msg, created))
        await self._conn.commit()
        return cursor.lastrowid

    async def attach(self, sticker_id: int, file_id: str, sha: str | None = None) -> None:
        await self._conn.execute(self._ATTACH, (file_id, sha, sticker_id))
        await self._conn.commit()

    async def remember_sha(self, name: str, sha: str | None) -> None:
        if sha:
            await self._conn.execute(self._REMEMBER_SHA, (name, sha))
            await self._conn.commit()

    async def has_sha(self, name: str, sha: str) -> bool:
        async with self._conn.execute(self._HAS_SHA, (name, sha)) as cursor:
            return await cursor.fetchone() is not None

    async def queued_shas(self, user_id: int, besides: int) -> set:
        async with self._conn.execute(self._QUEUED_SHAS, (user_id, besides)) as cursor:
            return {row["sha"] for row in await cursor.fetchall()}

    async def claim_prompt(self, sticker_id: int) -> bool:
        """Two finished conversions can reach the same head at once; only one may ask."""
        cursor = await self._conn.execute(self._CLAIM_PROMPT, (sticker_id,))
        await self._conn.commit()
        return cursor.rowcount == 1

    async def release_prompt(self, sticker_id: int) -> None:
        await self._conn.execute(self._RELEASE_PROMPT, (sticker_id,))
        await self._conn.commit()

    async def set_prompt(self, sticker_id: int, message_id: int) -> None:
        await self._conn.execute(self._SET_PROMPT, (message_id, sticker_id))
        await self._conn.commit()

    async def head_sticker(self, user_id: int) -> QueuedSticker | None:
        async with self._conn.execute(self._HEAD_STICKER, (user_id,)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return _sticker(row)

    async def ready_stickers(self, user_id: int) -> list[QueuedSticker]:
        """Stickers already given an emoji, in the order they were sent."""
        async with self._conn.execute(self._READY_STICKERS, (user_id,)) as cursor:
            rows = await cursor.fetchall()
        return [_sticker(row) for row in rows]

    async def mark_duplicate(self, sticker_id: int, emoji: str) -> None:
        """Hold the sticker aside with its emoji until the user says what to do with it."""
        await self._conn.execute(self._MARK_DUP, (emoji, sticker_id))
        await self._conn.commit()

    async def first_duplicate(self, user_id: int) -> QueuedSticker | None:
        async with self._conn.execute(self._FIRST_DUP, (user_id,)) as cursor:
            row = await cursor.fetchone()
        return _sticker(row) if row else None

    async def clear_duplicate(self, sticker_id: int) -> None:
        await self._conn.execute(self._CLEAR_DUP, (sticker_id,))
        await self._conn.commit()

    async def name_sticker(self, sticker_id: int, emoji: str) -> None:
        await self._conn.execute(self._NAME_STICKER, (emoji, sticker_id))
        await self._conn.commit()

    async def pop_sticker(self, sticker_id: int) -> None:
        await self._conn.execute(self._POP_STICKER, (sticker_id,))
        await self._conn.commit()

    async def count_stickers(self, user_id: int) -> int:
        """How many stickers are still waiting for an emoji."""
        async with self._conn.execute(self._COUNT_STICKERS, (user_id,)) as cursor:
            row = await cursor.fetchone()
        return row["n"] if row else 0

    async def clear_stickers(self, user_id: int) -> int:
        async with self._conn.execute(self._COUNT_ALL, (user_id,)) as cursor:
            row = await cursor.fetchone()
        dropped = row["n"] if row else 0
        await self._conn.execute(self._CLEAR_STICKERS, (user_id,))
        await self._conn.commit()
        return dropped

    async def emoji_for(self, user_id: int) -> str:
        async with self._conn.execute(self._GET_EMOJI, (user_id,)) as cursor:
            row = await cursor.fetchone()
        return (row["emoji"] if row else None) or DEFAULT_EMOJI


def _pack(row) -> Pack:
    return Pack(row["user_id"], row["name"], row["title"], row["created_at"])


def _sticker(row) -> QueuedSticker:
    return QueuedSticker(row["id"], row["user_id"], row["file_id"], row["name"],
                         row["suggested"], row["emoji"],
                         row["source_msg"], row["prompt_msg"], row["sha"])

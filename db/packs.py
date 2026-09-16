import logging
from datetime import datetime, timedelta, timezone

import states
from models import Overview, Pack, QueuedSticker, Session
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

    _ENTER = "UPDATE users SET state = ?, target = ?, sticker = ? WHERE user_id = ?"
    _GET_STATE = "SELECT state, target, sticker FROM users WHERE user_id = ?"

    _SET_PENDING = "UPDATE users SET pending_title = ? WHERE user_id = ?"
    _GET_PENDING = "SELECT pending_title FROM users WHERE user_id = ?"

    _SET_LANG = "UPDATE users SET lang = ? WHERE user_id = ?"
    _GET_LANG = "SELECT lang FROM users WHERE user_id = ?"

    _SET_EMOJI = "UPDATE users SET emoji = ? WHERE user_id = ?"
    _GET_EMOJI = "SELECT emoji FROM users WHERE user_id = ?"

    _PUSH_STICKER = (
        "INSERT INTO queued_stickers "
        "(user_id, file_id, name, suggested, source_msg, created_at, fmt) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)"
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
        "SELECT id, user_id, file_id, name, suggested, emoji, source_msg, prompt_msg, sha, fmt "
        "FROM queued_stickers "
        "WHERE user_id = ? AND emoji IS NULL ORDER BY id LIMIT 1"
    )
    _STICKER_AT = (
        "SELECT id, user_id, file_id, name, suggested, emoji, source_msg, prompt_msg, sha, fmt "
        "FROM queued_stickers WHERE id = ?"
    )
    _READY_STICKERS = (
        "SELECT id, user_id, file_id, name, suggested, emoji, source_msg, prompt_msg, sha, fmt "
        "FROM queued_stickers "
        "WHERE user_id = ? AND emoji IS NOT NULL AND dup = 0 AND file_id IS NOT NULL ORDER BY id"
    )
    _NAME_STICKER = "UPDATE queued_stickers SET emoji = ? WHERE id = ?"
    _CLAIM_EMOJI = "UPDATE queued_stickers SET emoji = ? WHERE id = ? AND emoji IS NULL"
    _CLAIM_READY = (
        "DELETE FROM queued_stickers "
        "WHERE id = ? AND emoji IS NOT NULL AND file_id IS NOT NULL AND dup = 0 "
        "RETURNING id, user_id, file_id, name, suggested, emoji, source_msg, prompt_msg, "
        "sha, fmt"
    )
    _MARK_DUP = "UPDATE queued_stickers SET emoji = ?, dup = 1 WHERE id = ?"
    _CLEAR_DUP = "UPDATE queued_stickers SET dup = 0 WHERE id = ?"
    _FIRST_DUP = (
        "SELECT id, user_id, file_id, name, suggested, emoji, source_msg, prompt_msg, sha, fmt "
        "FROM queued_stickers WHERE user_id = ? AND dup = 1 ORDER BY id LIMIT 1"
    )
    _POP_STICKER = "DELETE FROM queued_stickers WHERE id = ?"
    _COUNT_STICKERS = (
        "SELECT COUNT(*) AS n FROM queued_stickers WHERE user_id = ? AND emoji IS NULL"
    )
    _COUNT_ALL = "SELECT COUNT(*) AS n FROM queued_stickers WHERE user_id = ?"
    _CLEAR_STICKERS = "DELETE FROM queued_stickers WHERE user_id = ?"

    _COUNT_USERS = "SELECT COUNT(*) AS n FROM users"
    _COUNT_PACKS = "SELECT COUNT(*) AS n, COUNT(DISTINCT user_id) AS owners FROM packs"
    _COUNT_PACKS_SINCE = "SELECT COUNT(*) AS n FROM packs WHERE created_at >= ?"
    _COUNT_PACK_STICKERS = "SELECT COUNT(*) AS n FROM pack_stickers"
    _COUNT_QUEUED = "SELECT COUNT(*) AS n FROM queued_stickers"
    _COUNT_BY_LANG = (
        "SELECT COALESCE(lang, '?') AS lang, COUNT(*) AS n FROM users "
        "GROUP BY 1 ORDER BY n DESC, lang"
    )

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

    async def enter(self, user_id: int, state: str, target: str | None = None,
                    sticker: str | None = None) -> None:
        """One state at a time: entering one leaves whatever the user was in before."""
        if state not in states.ALL:
            raise ValueError(f"no such state: {state}")
        await self._ensure(user_id)
        await self._conn.execute(self._ENTER, (state, target, sticker, user_id))
        await self._conn.commit()

    async def leave(self, user_id: int) -> None:
        await self.enter(user_id, states.IDLE)

    async def session(self, user_id: int) -> Session:
        async with self._conn.execute(self._GET_STATE, (user_id,)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return Session(states.IDLE)
        return Session(row["state"] or states.IDLE, row["target"], row["sticker"])

    async def open_pack(self, user_id: int) -> str | None:
        """The pack stickers go into right now, if one is open at all."""
        found = await self.session(user_id)
        return found.target if found.state == states.FILLING else None

    async def set_pending(self, user_id: int, title: str | None) -> None:
        await self._ensure(user_id)
        await self._conn.execute(self._SET_PENDING, (title, user_id))
        await self._conn.commit()

    async def peek_pending(self, user_id: int) -> str | None:
        async with self._conn.execute(self._GET_PENDING, (user_id,)) as cursor:
            row = await cursor.fetchone()
        return row["pending_title"] if row else None

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
                           suggested: str | None, source_msg: int | None = None,
                           fmt: str | None = None) -> int:
        """Reserve the sticker's place in the queue; file_id lands once it is converted."""
        created = datetime.now(timezone.utc).isoformat()
        await self._ensure(user_id)
        cursor = await self._conn.execute(
            self._PUSH_STICKER, (user_id, file_id, name, suggested, source_msg, created, fmt))
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

    async def sticker(self, sticker_id: int) -> QueuedSticker | None:
        async with self._conn.execute(self._STICKER_AT, (sticker_id,)) as cursor:
            row = await cursor.fetchone()
        return _sticker(row) if row else None

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

    async def claim_emoji(self, sticker_id: int, emoji: str) -> bool:
        """One writer names a sticker; a second one is told it came too late."""
        cursor = await self._conn.execute(self._CLAIM_EMOJI, (emoji, sticker_id))
        await self._conn.commit()
        return cursor.rowcount == 1

    async def claim_ready(self, sticker_id: int) -> QueuedSticker | None:
        """Take the sticker out of the queue and hand it over exactly once."""
        async with self._conn.execute(self._CLAIM_READY, (sticker_id,)) as cursor:
            row = await cursor.fetchone()
        await self._conn.commit()
        return _sticker(row) if row else None

    async def pop_sticker(self, sticker_id: int) -> None:
        await self._conn.execute(self._POP_STICKER, (sticker_id,))
        await self._conn.commit()

    async def count_stickers(self, user_id: int) -> int:
        """How many stickers are still waiting for an emoji."""
        async with self._conn.execute(self._COUNT_STICKERS, (user_id,)) as cursor:
            row = await cursor.fetchone()
        return row["n"] if row else 0

    async def queued_count(self, user_id: int) -> int:
        """Everything still held for this user, whether it has its emoji or its file yet."""
        async with self._conn.execute(self._COUNT_ALL, (user_id,)) as cursor:
            row = await cursor.fetchone()
        return row["n"] if row else 0

    async def clear_stickers(self, user_id: int) -> int:
        async with self._conn.execute(self._COUNT_ALL, (user_id,)) as cursor:
            row = await cursor.fetchone()
        dropped = row["n"] if row else 0
        await self._conn.execute(self._CLEAR_STICKERS, (user_id,))
        await self._conn.commit()
        return dropped

    async def chosen_emoji(self, user_id: int) -> str | None:
        """The raw column: None means the user never picked one himself."""
        async with self._conn.execute(self._GET_EMOJI, (user_id,)) as cursor:
            row = await cursor.fetchone()
        return row["emoji"] if row else None

    async def emoji_for(self, user_id: int) -> str:
        async with self._conn.execute(self._GET_EMOJI, (user_id,)) as cursor:
            row = await cursor.fetchone()
        return (row["emoji"] if row else None) or DEFAULT_EMOJI

    async def overview(self) -> Overview:
        now = datetime.now(timezone.utc)
        day = (now - timedelta(days=1)).isoformat()
        week = (now - timedelta(days=7)).isoformat()
        packs = await self._row(self._COUNT_PACKS)
        async with self._conn.execute(self._COUNT_BY_LANG) as cursor:
            spoken = tuple((row["lang"], row["n"]) for row in await cursor.fetchall())
        return Overview(
            users=await self._count(self._COUNT_USERS),
            packs=packs["n"] if packs else 0,
            owners=packs["owners"] if packs else 0,
            stickers=await self._count(self._COUNT_PACK_STICKERS),
            queued=await self._count(self._COUNT_QUEUED),
            packs_today=await self._count(self._COUNT_PACKS_SINCE, (day,)),
            packs_week=await self._count(self._COUNT_PACKS_SINCE, (week,)),
            languages=spoken,
        )

    async def _row(self, sql: str, params: tuple = ()):
        async with self._conn.execute(sql, params) as cursor:
            return await cursor.fetchone()

    async def _count(self, sql: str, params: tuple = ()) -> int:
        row = await self._row(sql, params)
        return row["n"] if row else 0


def _pack(row) -> Pack:
    return Pack(row["user_id"], row["name"], row["title"], row["created_at"])


def _sticker(row) -> QueuedSticker:
    return QueuedSticker(row["id"], row["user_id"], row["file_id"], row["name"],
                         row["suggested"], row["emoji"],
                         row["source_msg"], row["prompt_msg"], row["sha"], row["fmt"])

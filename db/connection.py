import logging
from pathlib import Path

import aiosqlite

log = logging.getLogger(__name__)

DB_DIR = Path(__file__).parent.parent / "data"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"
DB_PATH = DB_DIR / "stickerloom.db"


_MIGRATIONS = (
    ("users", "asking", "TEXT"),
    ("users", "building", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "editing", "TEXT"),
    ("users", "importing", "TEXT"),
    ("users", "deleting", "TEXT"),
    ("users", "editing_pack", "TEXT"),
    ("users", "lang", "TEXT"),
    ("users", "next_emoji", "TEXT"),
    ("queued_stickers", "emoji", "TEXT"),
    ("queued_stickers", "sha", "TEXT"),
    ("queued_stickers", "dup", "INTEGER NOT NULL DEFAULT 0"),
    ("queued_stickers", "source_msg", "INTEGER"),
    ("queued_stickers", "prompt_msg", "INTEGER"),
    ("queued_stickers", "fmt", "TEXT"),
)


async def _rebuild_queue(conn: aiosqlite.Connection) -> None:
    """A queued row now exists before its file is converted, so file_id must be nullable."""
    async with conn.execute("PRAGMA table_info(queued_stickers)") as cursor:
        columns = await cursor.fetchall()
    if any(row[1] == "file_id" and row[3] for row in columns):
        await conn.execute("DROP TABLE queued_stickers")
        log.info("rebuilt queued_stickers")


async def _migrate(conn: aiosqlite.Connection) -> None:
    for table, column, decl in _MIGRATIONS:
        async with conn.execute(f"PRAGMA table_info({table})") as cursor:
            existing = {row[1] for row in await cursor.fetchall()}
        if column not in existing:
            await conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            log.info("migrated: added %s.%s", table, column)


async def connect() -> aiosqlite.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys = ON")
    await conn.execute("PRAGMA journal_mode = WAL")
    await _rebuild_queue(conn)
    await conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    await _migrate(conn)
    await conn.commit()
    log.info("connected to %s", DB_PATH)
    return conn

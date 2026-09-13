import logging
from pathlib import Path

import aiosqlite

log = logging.getLogger(__name__)

DB_DIR = Path(__file__).parent.parent / "data"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"
DB_PATH = DB_DIR / "stickerloom.db"


_MIGRATIONS = (
    ("users", "awaiting_title", "INTEGER NOT NULL DEFAULT 0"),
)


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
    await conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    await _migrate(conn)
    await conn.commit()
    log.info("connected to %s", DB_PATH)
    return conn

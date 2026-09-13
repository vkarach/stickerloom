import logging
from pathlib import Path

import aiosqlite

log = logging.getLogger(__name__)

DB_DIR = Path(__file__).parent.parent / "data"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"
DB_PATH = DB_DIR / "stickerloom.db"


async def connect() -> aiosqlite.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys = ON")
    await conn.execute("PRAGMA journal_mode = WAL")
    await conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    await conn.commit()
    log.info("connected to %s", DB_PATH)
    return conn

CREATE TABLE IF NOT EXISTS users (
    user_id        INTEGER PRIMARY KEY,
    active_pack    TEXT,
    pending_title  TEXT,
    emoji          TEXT,
    asking         TEXT,
    building       INTEGER NOT NULL DEFAULT 0,
    editing        TEXT,
    importing      TEXT,
    deleting       TEXT,
    editing_pack   TEXT,
    lang           TEXT
);

CREATE TABLE IF NOT EXISTS packs (
    user_id    INTEGER NOT NULL,
    name       TEXT NOT NULL,
    title      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, name)
);

CREATE INDEX IF NOT EXISTS idx_packs_owner ON packs(user_id, created_at);

CREATE TABLE IF NOT EXISTS queued_stickers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    file_id    TEXT,
    name       TEXT NOT NULL,
    suggested  TEXT,
    emoji      TEXT,
    sha        TEXT,
    dup        INTEGER NOT NULL DEFAULT 0,
    source_msg INTEGER,
    prompt_msg INTEGER,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_queued_owner ON queued_stickers(user_id, id);

CREATE TABLE IF NOT EXISTS pack_stickers (
    name TEXT NOT NULL,
    sha  TEXT NOT NULL,
    PRIMARY KEY (name, sha)
);

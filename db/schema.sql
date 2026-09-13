CREATE TABLE IF NOT EXISTS users (
    user_id       INTEGER PRIMARY KEY,
    active_pack   TEXT,
    pending_title TEXT,
    emoji         TEXT
);

CREATE TABLE IF NOT EXISTS packs (
    user_id    INTEGER NOT NULL,
    name       TEXT NOT NULL,
    title      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, name)
);

CREATE INDEX IF NOT EXISTS idx_packs_owner ON packs(user_id, created_at);

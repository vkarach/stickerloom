# Sticker Packs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and grow sticker packs from inside Stickerloom, so a converted file can go straight into a pack without touching @Stickers.

**Architecture:** A new `packs/` domain owns pack naming and the Bot API sticker methods; a new `db/` layer remembers which pack a user is filling. The conversion flow gains one optional step: when a pack is active, the finished file is added to it.

**Tech Stack:** Python 3.12 on the server, aiogram 3, aiosqlite.

**Spec:** `docs/superpowers/specs/2026-09-12-stickerloom-design.md` (phase 1), extended here.

## Global Constraints

Verified against the live API before planning:

- A set name must end in `_by_<bot_username>`, so the running bot's username decides it. Dev and main bots therefore own different packs and cannot manage each other's.
- `createNewStickerSet` needs 1-50 stickers: an empty pack cannot exist, so a pack is created together with its first sticker.
- `emoji_list` is mandatory for every sticker.
- `addStickerToSet` on a set this bot did not create fails with `STICKERSET_INVALID`. Packs made in @Stickers can only be copied, never extended.
- Stickers read out of a foreign set can be reused by `file_id` to build our own set, and their emoji survive the copy.
- Comments are one terse line or absent. English in files. ASCII only.

---

### Task 1: Pack naming

**Files:** Create `packs/names.py`, `tests/test_pack_names.py`

**Interfaces:**
- Produces: `pack_name(title: str, bot_username: str) -> str` and `SUFFIX_TEMPLATE`.

- [ ] Write failing tests: a title becomes a lowercase slug; spaces and punctuation collapse to underscores; non-ASCII titles still yield a legal name; a leading digit is prefixed with a letter; the result always ends in `_by_<bot_username>`; length stays within 64; two calls with the same title differ, since names are globally unique across Telegram.
- [ ] Run them, confirm they fail.
- [ ] Implement, then confirm they pass, then commit.

---

### Task 2: Storage

**Files:** Create `db/connection.py`, `db/schema.sql`, `db/packs.py`, `db/__init__.py`; modify `models.py`; create `tests/test_pack_repo.py`

**Interfaces:**
- Produces: `Pack(user_id, name, title, created_at)` in `models.py`.
- Produces: `connect()` mirroring Semestra, database at `data/stickerloom.db`.
- Produces: `PackRepo` with `remember`, `list_for`, `set_active`, `active_for`, `clear_active`, `set_pending`, `pending_for`, `set_emoji`, `emoji_for`.

- [ ] Write failing tests against a temporary database: a remembered pack is listed for its owner and not for anyone else; the active pack survives a reconnect; clearing it leaves the pack listed; a pending title is consumed once and then gone; the default emoji round-trips.
- [ ] Run them, confirm they fail.
- [ ] Implement schema and repo in Semestra's style, then confirm they pass, then commit.

---

### Task 3: Pack manager

**Files:** Create `packs/manager.py`, `packs/errors.py`, `packs/__init__.py`; create `tests/test_pack_manager.py`

**Interfaces:**
- Produces: `PackManager(bot, repo)` with `create(user_id, title, path, emoji) -> Pack`, `add(user_id, pack, path, emoji)`, `import_set(user_id, source_name, title) -> Pack`, `link(pack) -> str`.
- Produces: `errors.py` with `PackFull`, `PackNotOurs`, `PackNotFound`, `NameTaken`, each carrying a user-facing message.

- [ ] Write failing tests with a fake bot recording calls: creating uses `createNewStickerSet` with format video and the given emoji; adding uses `addStickerToSet`; a `STICKERSET_INVALID` reply becomes `PackNotOurs`; a full set becomes `PackFull`; importing copies every source sticker with its own emoji and falls back to a default when a source sticker has none; a source set of more than 50 is created from the first 50 and the rest appended.
- [ ] Run them, confirm they fail.
- [ ] Implement, then confirm they pass, then commit.

---

### Task 4: Pack commands

**Files:** Create `bot/handlers/packs.py`; modify `bot/commands.py`, `bot/handlers/__init__.py`

**Commands:** `/newpack <title>`, `/nopack`, `/mypacks`, `/emoji <emoji>`, `/import <link>`.

- [ ] `/newpack` stores the title as pending and says the pack will be born with the next file.
- [ ] `/mypacks` lists the user's packs with inline buttons that switch the active one; the active one is marked.
- [ ] `/nopack` clears the active pack and says conversion continues as before.
- [ ] `/emoji` sets the default emoji used for sources that carry none, and rejects input that is not an emoji.
- [ ] `/import` accepts a `t.me/addstickers/<name>` link or a bare name, copies the set, makes the copy active.
- [ ] Commit.

---

### Task 5: Wire packs into conversion

**Files:** Modify `bot/handlers/convert.py`, `bot/main.py`

- [ ] After the file is delivered, if a pending title exists, create the pack from this file; else if a pack is active, add to it.
- [ ] Report the outcome on the result message, with the pack link when a pack was just created.
- [ ] A pack failure must never lose the converted file: the file is sent first, the pack step reports its own error.
- [ ] Pass the repo and manager through the dispatcher, open and close the database in `main`.
- [ ] Run the full suite, confirm it passes, then commit.

---

### Task 6: Documentation

**Files:** Modify `README.md`, `bot/handlers/common.py`

- [ ] Document the pack flow, the naming rule, and the two hard limits: no empty packs, and no extending a pack that @Stickers created.
- [ ] Update `/start` and `/pack` so the manual @Stickers route is presented as the fallback it now is.
- [ ] Commit.

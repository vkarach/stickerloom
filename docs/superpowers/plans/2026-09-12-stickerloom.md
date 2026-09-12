# Stickerloom Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Telegram bot that converts any supported picture, sticker, GIF or short video into one canonical WebM accepted by @Stickers as a video sticker.

**Architecture:** Two independent packages. `convert/` owns the format and shells out to ffmpeg, importable and testable without a bot token. `bot/` is the aiogram layer and holds no conversion logic. They meet only at the dataclasses in `models.py`. An in-memory queue with a fixed worker pool keeps the bot responsive under a batch.

**Tech Stack:** Python 3.14, aiogram 3, python-dotenv, pytest + pytest-asyncio, ffmpeg/ffprobe on PATH.

**Spec:** `docs/superpowers/specs/2026-09-12-stickerloom-design.md`

## Global Constraints

- Output: WebM, VP9, `yuva420p`, long side exactly 512, other side <= 512 and even, aspect ratio preserved, never padded.
- Duration <= 3 s; a still input becomes a 1 s clip. 30 fps. No audio stream. <= 256 KB.
- `.tgs` is rejected by design. Sources over 20 MB are rejected (Bot API download limit).
- The result is delivered as a document, never as a video.
- Comments are one terse line or absent. English in all files. ASCII only.
- Commit at the end of every task, one topic per commit, no attribution lines.

---

### Task 1: Project skeleton and logging

**Files:**
- Create: `logging_config.py`, `requirements.txt`, `.env`, `README.md`, `bot/__init__.py`, `convert/__init__.py`

**Interfaces:**
- Produces: `setup_logging() -> Logger`, writing to `logs/log_<dd.mm.YYYY_HH-MM-SS>.log` and to the console.

- [ ] Port Semestra's `logging_config.py` unchanged in structure: `CenteredLevelFormatter`, per-run log file, DEBUG to file and INFO to console, noisy loggers muted (`asyncio`, `aiogram.event`).
- [ ] Pin `aiogram`, `python-dotenv`, `pytest`, `pytest-asyncio` in `requirements.txt`.
- [ ] Put `BOT_TOKEN` in `.env` (gitignored) and document the required keys in `README.md`.
- [ ] Commit.

---

### Task 2: The format spec and the scaling rule

**Files:**
- Create: `convert/spec.py`, `models.py`
- Test: `tests/test_spec.py`

**Interfaces:**
- Produces: `MediaInfo(width, height, duration, frames, is_animated)` and `ConvertResult(path, width, height, duration, size, attempts)` in `models.py`.
- Produces: `target_size(width: int, height: int) -> tuple[int, int]` plus the format constants (`LONG_SIDE`, `MAX_DURATION`, `STILL_DURATION`, `FPS`, `MAX_BYTES`, `SUPPORTED_EXTENSIONS`).

- [ ] Write the failing tests first. Cases: square stays square at 512; a wide source gets width 512 and a proportional even height; a tall source gets height 512; a source smaller than 512 is scaled up so the long side reaches 512; a rounded odd dimension lands on the nearest even value and never on zero; the aspect ratio is preserved within one pixel.
- [ ] Run them, confirm they fail.
- [ ] Implement `target_size` and the constants.
- [ ] Run them, confirm they pass.
- [ ] Commit.

---

### Task 3: ffprobe wrapper

**Files:**
- Create: `convert/probe.py`, `convert/errors.py`
- Test: `tests/test_probe.py`

**Interfaces:**
- Consumes: `MediaInfo` from Task 2.
- Produces: `async probe(path: Path) -> MediaInfo`; `parse_probe(payload: dict) -> MediaInfo` as the pure half so parsing is testable without ffprobe.
- Produces: `errors.py` with `StickerloomError` and subclasses `UnsupportedInput`, `SourceTooLarge`, `ProbeFailed`, `EncodeFailed`, `CannotFitSizeLimit`. Each carries a user-facing message.

- [ ] Write the failing tests against captured ffprobe JSON: a still image (no duration, one frame, not animated), an animated GIF, an MP4 with an audio stream present, and a payload with no video stream at all which must raise `ProbeFailed`.
- [ ] Run them, confirm they fail.
- [ ] Implement `parse_probe`, then `probe` on top of it via `asyncio.create_subprocess_exec` with `-show_streams -show_format -print_format json`.
- [ ] Run them, confirm they pass.
- [ ] Commit.

---

### Task 4: The encoder and the size ladder

**Files:**
- Create: `convert/encoder.py`
- Test: `tests/test_encoder.py`

**Interfaces:**
- Consumes: `target_size` and the constants from Task 2, `MediaInfo` from Task 3, the errors from Task 3.
- Produces: `build_args(src, dst, info, crf, fps) -> list[str]` as the pure half, and `async encode(src: Path, dst: Path, info: MediaInfo) -> ConvertResult`.
- Produces: `LADDER` - the ordered `(crf, fps)` attempts, rising in CRF first and dropping fps only once CRF is exhausted.

- [ ] Write the failing tests. On `build_args`: a still source loops a single frame for `STILL_DURATION` while an animated one is trimmed to `MAX_DURATION`; the filter chain scales without any `pad`; `format=yuva420p` is present; `-an` is present; the requested CRF and fps reach the argument list. On the ladder: it is strictly non-increasing in output size pressure, starts at the best quality, and is finite.
- [ ] Run them, confirm they fail.
- [ ] Implement `build_args` and `encode`. `encode` walks the ladder, stops at the first attempt landing under `MAX_BYTES`, and raises `CannotFitSizeLimit` carrying the smallest size reached when the ladder is exhausted. A non-zero ffmpeg exit raises `EncodeFailed` with the tail of stderr logged.
- [ ] Run them, confirm they pass.
- [ ] Commit.

---

### Task 5: End-to-end conversion against real ffmpeg

**Files:**
- Test: `tests/test_golden_format.py`

**Interfaces:**
- Consumes: `probe` and `encode`.

- [ ] Write a helper that generates sources with ffmpeg's `lavfi` inputs: a still PNG, a non-square still, and a ten second animation that must be trimmed.
- [ ] Assert on the real output via `probe`: codec is VP9, the long side is exactly 512, both sides are even, duration is within tolerance of the expected value, there is no audio stream, and the file is at most 256 KB.
- [ ] Assert the ten second source comes back trimmed to 3 s.
- [ ] Run the suite, confirm it passes.
- [ ] Commit.

---

### Task 6: Job queue and worker pool

**Files:**
- Create: `convert/queue.py`
- Modify: `models.py` - add `Job`
- Test: `tests/test_queue.py`

**Interfaces:**
- Produces: `Job(source, name, on_status, on_done, on_error)` where the callbacks are awaitables, so the queue never imports aiogram.
- Produces: `JobQueue(workers: int)` with `async submit(job) -> int` returning the queue position, `pending_for(key) -> int`, `async start()` and `async stop()`.

- [ ] Write the failing tests: jobs run in submission order; a job raising an exception invokes `on_error` and leaves the pool alive for the next job; `submit` reports a growing position; `stop` drains cleanly and cancels no half-written job mid-flight.
- [ ] Run them, confirm they fail.
- [ ] Implement the queue over `asyncio.Queue` with a fixed number of worker tasks. Every job gets its own temporary directory, removed in `finally`.
- [ ] Run them, confirm they pass.
- [ ] Commit.

---

### Task 7: Command registry and the static handlers

**Files:**
- Create: `bot/commands.py`, `bot/setup.py`, `bot/handlers/__init__.py`, `bot/handlers/common.py`

**Interfaces:**
- Produces: `CommandSpec`, `COMMANDS`, `menu()` and `help_content()` - the same shape as Semestra's registry, minus the admin access tier, which this bot has no use for.
- Produces: `setup_commands(bot)` registering the menu for all private chats.
- Commands: `/start`, `/help`, `/cancel`.

- [ ] Build the registry and render `/help` from it, grouped.
- [ ] Write `/start` as a one-liner naming what to send, `/help` from the registry, `/cancel` dropping the user's queued jobs.
- [ ] Commit.

---

### Task 8: The conversion handler

**Files:**
- Create: `bot/handlers/convert.py`, `bot/middlewares/__init__.py`, `bot/middlewares/queue_guard.py`

**Interfaces:**
- Consumes: `JobQueue` from Task 6, the errors from Task 3, the constants from Task 2.
- Produces: a router accepting `F.document`, `F.photo`, `F.sticker`, `F.animation`, `F.video` and `F.video_note`.

- [ ] Validate the incoming media: extension against `SUPPORTED_EXTENSIONS`, `.tgs` rejected with its own explanation, size against the 20 MB download limit.
- [ ] Answer immediately with a status message, then edit that same message at each transition (queued with position -> converting -> done) rather than sending new ones.
- [ ] Deliver the result with `answer_document` and a caption stating dimensions, duration and size. Never `answer_video`.
- [ ] Map every `StickerloomError` to its own message; log anything unexpected with a traceback and answer generically.
- [ ] Cap the number of jobs a single user may hold in the queue in `queue_guard.py`.
- [ ] Commit.

---

### Task 9: Entrypoint and README

**Files:**
- Create: `bot/main.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: everything above.

- [ ] Wire `main()`: load the environment, set up logging, build the `Bot` and `Dispatcher`, include the router, register the middleware, start the worker pool on startup and stop it on shutdown, poll.
- [ ] Fail loudly at startup if ffmpeg or ffprobe is missing from PATH - the bot is useless without them and a late failure is harder to read.
- [ ] Document in `README.md`: what the bot does, the golden format table, the ffmpeg prerequisite, the `.env` keys, how to run, how to run the tests, and the upload path into @Stickers.
- [ ] Run the full suite, confirm it passes.
- [ ] Commit.

---

## Self-Review

**Spec coverage.** Golden format -> Tasks 2, 4, 5. Inputs and rejections -> Tasks 2, 8. Architecture and interfaces -> Tasks 2-9. Size ladder -> Task 4. Data flow -> Tasks 6, 8. Error handling -> Tasks 3, 4, 8. Interface design -> Tasks 7, 8. State -> Task 6, in memory only. Testing -> Tasks 2-6.

**Type consistency.** `MediaInfo`, `ConvertResult` and `Job` are defined once in `models.py` and consumed unchanged. `target_size`, `parse_probe`, `build_args`, `encode`, `probe`, `JobQueue.submit` keep one name and one signature throughout.

**Placeholders.** None. Every task names its files, its contract and its test cases; the bodies are deliberately left to the implementer per the project's plan convention.

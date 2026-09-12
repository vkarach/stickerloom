# Stickerloom - design

Telegram bot that turns any picture, sticker, GIF or short video into a single
canonical WebM ready to be uploaded to @Stickers as a video sticker.

## Purpose

@Stickers accepts video stickers only in a narrow WebM/VP9 shape. Producing that
shape by hand with ffmpeg is where the mistakes happen - the usual one is padding
everything to a 512x512 square, which adds empty bars to non-square art. The bot
owns the correct recipe so the user never writes an ffmpeg line again.

Phase 1, this spec: file in, WebM out. Building the pack through the Bot API is
the obvious next step and the naming leaves room for it, but it is out of scope.

## The golden format

| Property | Value |
| --- | --- |
| Container / codec | WebM, VP9 |
| Pixel format | yuva420p (alpha preserved) |
| Size | long side exactly 512, other side <= 512 and even, aspect ratio kept, never padded |
| Duration | <= 3 s; a still image becomes a 1 s clip |
| Frame rate | 30 fps |
| Audio | none |
| File size | <= 256 KB |

A still input is stretched into a short clip on purpose: that is what lets a
static sticker live in a video sticker pack.

## Inputs

Accepted: PNG, JPEG, WebP (still and animated), GIF, APNG, MP4, WebM, MOV, plus
Telegram stickers (static and video) and photos.

Rejected: `.tgs` (Lottie). Animated Telegram stickers already work inside packs,
so converting them buys nothing and would drag in a native rlottie build.

Sources larger than 20 MB are rejected - the Bot API cannot download them.

## Architecture

```
bot/                  aiogram layer, knows nothing about ffmpeg
  main.py             entrypoint: Bot, Dispatcher, router, worker pool lifecycle
  commands.py         CommandSpec registry + rendered /help
  setup.py            set_my_commands
  handlers/
    common.py         /start, /help, /cancel
    convert.py        media intake, enqueue, progress message, delivery
  middlewares/
    queue_guard.py    per-user cap on queued jobs
convert/              domain, knows nothing about aiogram
  spec.py             the golden format as constants + the size/fps ladder
  probe.py            ffprobe -> MediaInfo
  encoder.py          ffmpeg argument construction and execution
  queue.py            asyncio.Queue plus a fixed worker pool
  errors.py           domain exceptions
models.py             MediaInfo, Job, ConvertResult
logging_config.py     file + console logging, same scheme as Semestra
tests/
```

The two packages talk through dataclasses in `models.py` only. `convert/` is
importable and testable without a bot token.

## Interfaces

- `probe(path: Path) -> MediaInfo` - raises `ProbeFailed` on unreadable input.
- `MediaInfo` - width, height, duration, frame count, whether it is animated.
- `encode(src: Path, dst: Path, info: MediaInfo) -> ConvertResult` - raises
  `EncodeFailed` or `CannotFitSizeLimit`.
- `ConvertResult` - path, width, height, duration, size in bytes, attempts used.
- `target_size(width, height) -> tuple[int, int]` - the scaling rule, pure.
- `JobQueue.submit(job) -> position` and a worker pool started and stopped with
  the dispatcher.

## Fitting the size limit

Encode, measure, and if the result exceeds 256 KB walk a bounded ladder: raise
CRF first, then drop the frame rate, re-encoding at each step. A still image will
never need a second pass; a busy three second GIF may need several. When the
ladder runs out, `CannotFitSizeLimit` carries the smallest size achieved so the
user is told what actually happened instead of getting a silent failure.

## Data flow

1. A message with any supported media arrives.
2. The type and the source size are validated; a rejection explains itself.
3. The job is queued and the user immediately gets a status message.
4. A worker downloads the source into a per-job temporary directory, probes it,
   encodes it, and edits the status message at each transition.
5. The result is sent back **as a document**. Sending it as a video would let
   Telegram re-encode it and @Stickers would then reject the file.
6. The temporary directory is removed whether or not the job succeeded.

## Error handling

Every failure mode is a domain exception carrying a message fit to show a user:
unsupported type, source too large, probe failure, encode failure, size limit
unreachable. Unexpected exceptions are logged with a traceback and answered with
a generic apology - the worker pool must survive any single bad job.

## Interface design

There are no settings and no option keyboards. One output format means no knobs
to expose. What makes it pleasant instead:

- one self-editing status message per file (queued -> converting -> done),
- queue position when several files are in flight, so a batch reads in order,
- a caption stating the real result: dimensions, duration, size,
- errors phrased as what to do next,
- `/start`, `/help`, `/cancel` driven by the same command registry as Semestra.

Dropping twenty files in a row yields twenty finished WebM files in order.

## State

None. The queue lives in memory and a restart drops it. No database, because
nothing needs to outlive a job. If per-user settings ever appear, an aiosqlite
`db/` package mirroring Semestra is the place to add them.

## Testing

pytest over the pure parts: ffprobe output parsing, the scaling rule against
square, wide, tall and undersized inputs, ffmpeg argument construction, and the
ladder's progression and exhaustion. One end-to-end test encodes a generated
`lavfi` source with the real ffmpeg and asserts the output matches the golden
format. Bot handlers are not unit tested; they hold no logic worth testing.

# Stickerloom

Telegram bot that turns a picture, sticker, GIF or short video into the one WebM
shape @Stickers accepts as a video sticker. Send a file, get a file back.

The point is mixing media in a single pack: a still picture comes back as a one
second clip, so static art can live in a video sticker pack next to real
animations.

## The output format

| Property | Value |
| --- | --- |
| Container / codec | WebM, VP9 |
| Transparency | preserved |
| Size | long side exactly 512 px, aspect ratio kept, never padded |
| Duration | at most 3 s; a still picture becomes 1 s |
| Frame rate | 30 fps |
| Audio | none |
| File size | at most 256 KB |

Dense sources are re-encoded at rising CRF and, once that is spent, at a lower
frame rate until they fit the size limit.

## Accepted inputs

PNG, JPEG, WebP (still and animated), GIF, APNG, MP4, WebM, MOV, M4V, plus
Telegram photos, stickers, animations, videos and video notes.

`.tgs` is rejected on purpose: animated Telegram stickers already work in a
pack, so there is nothing to convert. Sources over 20 MB are rejected because
the Bot API will not let a bot download them.

## Requirements

- Python 3.14
- ffmpeg and ffprobe on PATH

ffmpeg cannot decode animated WebP, so those are read through Pillow and
expanded into frames before encoding.

## Environment

`.env` in the project root:

```
BOT_TOKEN=<token from @BotFather>
```

## Running

```
pip install -r requirements.txt
python -m bot.main
```

## Tests

```
pytest
```

The suite covers the scaling rule, ffprobe parsing, ffmpeg argument
construction, the size ladder and the queue, plus end-to-end encodes against a
real ffmpeg that assert the output really matches the format table above.

## Commands

- `/start` - what the bot does
- `/help` - all commands
- `/cancel` - drop everything still queued
- `/format` - the exact output format
- `/pack` - how to load the files into a pack

## Building the pack

Open @Stickers, send `/newpack` (or `/addsticker`), choose **video sticker**,
then forward the files this bot produced **as files, not as videos**. Sending
them as video lets Telegram re-encode them and @Stickers then refuses the
result.

When the source was a sticker, its emoji comes back as a second message, because
@Stickers asks for one right after the file.

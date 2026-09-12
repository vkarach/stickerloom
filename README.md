# Stickerloom

Telegram bot that converts pictures, stickers, GIFs and short videos into the
WebM shape @Stickers accepts as a video sticker.

Work in progress. See `docs/superpowers/specs/` for the design and
`docs/superpowers/plans/` for the implementation plan.

## Requirements

- Python 3.14
- ffmpeg and ffprobe on PATH

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

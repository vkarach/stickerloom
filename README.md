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
Telegram photos, stickers, animations, videos and video notes, or a link to
any of those.

A link to a file works the same as the file: paste one and the page behind it
is read for its `og:video` or `og:image`, so a Tenor or Giphy page yields the
GIF it shows. A page that ships no meta tags is searched for a file that
carries the same id as the page itself, so a recommendation next to it is never
picked up by mistake. An animated image is preferred over a video, because only
the image can carry transparency. Links are fetched by the same worker pool
that converts, the download is capped at the source limit, and a link that
resolves to a private or loopback address is refused - a user's link may not
reach inside the network the bot runs in. A `t.me` pack link is not media:
`/import` copies packs.

`.tgs` is rejected on purpose: animated Telegram stickers already work in a
pack, so there is nothing to convert. Sources sent in the chat are capped at 20
MB, because the Bot API will not let a bot download more than that; a link is
fetched from the web instead, where the cap is 200 MB.

## Requirements

- Python 3.14
- ffmpeg and ffprobe on PATH

ffmpeg cannot decode animated WebP, so those are read through Pillow and
expanded into frames before encoding.

Scaling is lanczos, except for a drawn source whose first frame holds 64 colors
or fewer: pixel art is scaled with nearest neighbour, which keeps its edges.

## Backup

Backup writes the whole set into a zip: every sticker in order, plus a
pack.json naming the set, its title, the day it was taken and the emoji of each
file. Telegram is the only copy of a pack, and a deleted set is gone for good,
so the zip is the copy that is yours.

Sending that zip back restores it. The stickers keep their emoji and their
order, and the kind of sticker is read from the files, so a backup of an
animated or a static pack comes back as one - a set holds one kind, and a zip
that mixes them is refused. With a pack open in /mypacks the stickers go into
it; otherwise the bot asks for a link prefix and builds a new pack, exactly as
/newpack does. Only the files the manifest lists are unpacked, and only from
the zip's own top level.

## State

A user is in exactly one state at a time, held in one column: idle, naming,
collecting, prefix, source, filling, picking, retagging or confirming. Entering
one leaves the one before by construction, so nothing has to be cleared by hand
and no two half-finished flows can overlap. What the state is about travels
with it: the pack, the set being imported, the sticker being retagged. A plain
text message means whatever the state says it means, and files go into a pack
only while collecting or filling.

## Language

Every user-facing string lives in `locales/<lang>.json` and is looked up by key;
nothing is spelled out in the handlers. `en.json` is the reference: a locale
that gains or loses a key against it stops the bot at startup. A value may be a
list of forms when it carries a count, and the form is chosen by the language's
own plural rule.

A user is answered in the language he picked with `/lang`, else in the one
Telegram reports, else in English. The command menu is registered once per
language, so the `/` list is translated too.

## Environment

`.env` in the project root:

```
BOT_TOKEN=<token from @BotFather>
ADMIN_IDS=<your Telegram user id, comma separated for several>
```

## Admin

`/stats` prints usage totals: users and the languages they were answered in,
packs and how many were made in the last day and week, stickers stored and the
depth of the convert queue. It is the only admin surface and it reads counts
only, never a user's packs or files.

It speaks the language you picked, like everything else the bot says.

Who may run it is decided by `ADMIN_IDS` in `.env`, which is never committed, so
the repository can be public without naming anyone. There is no command that
adds an admin: the list changes on the server and nowhere else. A user who is
not on it gets no answer at all - `/stats` behaves exactly like a command that
does not exist, so the panel cannot be found by guessing. An empty or missing
`ADMIN_IDS` means nobody is an admin.

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
- `/cancel` - stop whatever is in progress
- `/newpack`, `/done`, `/mypacks`, `/import`, `/emoji` - the pack flow
- `/format` - the exact output format
- `/stats` - usage totals, admins only

## Building a pack

`/newpack` asks for a name, then takes files until `/done`, which asks for the
link prefix and creates the whole set in one call. Every file is converted,
parked, and shown as a reply to the message it came from, so a batch is
answered in the order it was sent. An emoji sent while a file of yours is still
converting is never dropped for arriving early: with a pack open it is held for
that file and used the moment it lands, and with none open it waits for the
file that comes back and answers for it when that file is put into a pack. With
nothing converting there is nothing for it to belong to, so it is left alone.
One written next to the file itself counts as the answer rather than a
suggestion, so nothing is typed twice. `/mypacks` lists your packs; picking one
opens a menu that adds stickers, edits a sticker emoji, removes a sticker,
saves a backup or deletes the pack. `/emoji` sets the emoji used for files that
carry none of their own.

A pack built here is named `<prefix>_by_<bot username>`, because Telegram
requires that suffix. The running bot owns it, which has two consequences worth
knowing:

- **A pack created in @Stickers can never be filled by this bot.**
  `addStickerToSet` answers `STICKERSET_INVALID` for any set the bot did not
  create. `/import` copies such a pack into one this bot owns, emoji included,
  and that copy can be filled forever after. It reads the source first, reports
  its title and size, asks for a link prefix like `/newpack` does, and says how
  many stickers made it across.
- Packs made by the dev bot belong to the dev bot, not to the main one.

Telegram refuses writes to a set for a while after it is created - measured at
19 seconds - so anything added past the first 50 stickers is retried for half a
minute. `getStickerSet` keeps answering for deleted sets, so a pack is checked
for life with a title write instead.

The same file added twice is caught by a sha256 of the converted WebM, kept per
pack, and answered with `Add anyway` or `Skip`.

### By hand instead

Open @Stickers, send `/newpack` (or `/addsticker`), choose **video sticker**,
then forward the files this bot produced **as files, not as videos**. Sending
them as video lets Telegram re-encode them and @Stickers then refuses the
result. When the source was a sticker, its emoji comes back as a second message,
because @Stickers asks for one right after the file.

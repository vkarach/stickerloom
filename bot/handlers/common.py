from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.utils.formatting import Bold, Code, Text, as_list, as_marked_section

from bot.commands import help_content
from convert.queue import JobQueue
from convert.spec import FPS, LONG_SIDE, MAX_BYTES, MAX_DURATION

router = Router()

START = Text(
    Bold("Stickerloom"), "\n\n",
    "Send a picture, sticker, GIF or short video. You get back a ",
    Code(".webm"), " shaped exactly the way a video sticker has to be.\n\n",
    "To build a pack without leaving this chat, run /newpack and keep sending files. "
    "Already have a pack made in @Stickers? /import copies it here.\n\n",
    "/format for the output details, /pack for the manual @Stickers route.",
)

FORMAT = as_marked_section(
    Bold("Every file comes back as"),
    Text("WebM, VP9, transparency preserved"),
    Text(f"long side exactly {LONG_SIDE} px, aspect ratio untouched, never padded"),
    Text(f"at most {MAX_DURATION:.0f} s, {FPS} fps, no audio"),
    Text(f"at most {MAX_BYTES // 1024} KB"),
    Text("a still picture becomes a one second clip, so it fits a video pack"),
    marker="- ",
)

PACK = as_list(
    Bold("Building a pack by hand"),
    Text("This bot can do it for you with /newpack. Do it yourself like this:"),
    Text("1. Open @Stickers and send /newpack, or /addsticker for an existing one."),
    Text("2. Pick ", Bold("video sticker"), " when it asks for the type."),
    Text("3. Forward the files this bot sent you, as files, not as videos."),
    Text("4. Send an emoji for each one."),
    Text("\nA pack made in @Stickers cannot be filled by this bot afterwards, "
         "Telegram only lets a bot touch packs it created itself. /import copies one over."),
    sep="\n",
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(**START.as_kwargs())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(**help_content().as_kwargs())


@router.message(Command("format"))
async def cmd_format(message: Message) -> None:
    await message.answer(**FORMAT.as_kwargs())


@router.message(Command("pack"))
async def cmd_pack(message: Message) -> None:
    await message.answer(**PACK.as_kwargs())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, queue: JobQueue) -> None:
    assert message.from_user
    dropped = queue.cancel(message.from_user.id)
    if not dropped:
        await message.answer("Nothing queued.")
        return
    await message.answer(f"Dropped {dropped} queued file(s).")

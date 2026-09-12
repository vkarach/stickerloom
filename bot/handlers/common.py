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
    Code(".webm"), " that @Stickers accepts as a video sticker.\n\n",
    "Drop as many files as you like, they are converted in order. "
    "/format for the details, /pack for what to do with the result.",
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
    Bold("Putting the files into a pack"),
    Text("1. Open @Stickers and send /newpack, or /addsticker for an existing one."),
    Text("2. Pick ", Bold("video sticker"), " when it asks for the type."),
    Text("3. Forward the files this bot sent you, as files, not as videos."),
    Text("4. Send an emoji for each one."),
    Text("\nStatic and video stickers can live in the same video pack, "
         "which is the whole point of converting the still ones."),
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

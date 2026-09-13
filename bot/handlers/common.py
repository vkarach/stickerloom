from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.utils.formatting import Bold, Text, as_list, as_marked_section

from bot.commands import help_content
from convert.queue import JobQueue
from convert.spec import FPS, LONG_SIDE, MAX_BYTES, MAX_DURATION

router = Router()

START = Text(
    "Send a picture, sticker, GIF or video, get back a video sticker.\n\n",
    "/newpack to build a pack here.\n",
    "/import to copy a pack made in @Stickers.",
)

FORMAT = as_marked_section(
    Bold("Output"),
    Text("WebM, VP9, transparency kept"),
    Text(f"long side {LONG_SIDE} px, never padded"),
    Text(f"up to {MAX_DURATION:.0f} s, {FPS} fps, no audio"),
    Text(f"up to {MAX_BYTES // 1024} KB"),
    Text("a still picture becomes a 1 s clip"),
    marker="- ",
)

PACK = as_list(
    Bold("By hand in @Stickers"),
    Text("1. /newpack in @Stickers, or /addsticker."),
    Text("2. Pick ", Bold("video sticker"), "."),
    Text("3. Forward the files as files, not as videos."),
    Text("4. Send an emoji for each."),
    Text("\nThis bot cannot fill a pack @Stickers made. /import copies one over."),
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
    await message.answer(f"Dropped {dropped} queued.")

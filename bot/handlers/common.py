from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.utils.formatting import Bold, Text, as_list, as_marked_section

from bot.commands import help_content
from bot.handlers.packs import drop_preview
from db.packs import PackRepo
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
async def cmd_cancel(message: Message, queue: JobQueue, repo: PackRepo) -> None:
    """One stop button: the convert queue, the pack being built and the sticker editor."""
    assert message.from_user
    user_id = message.from_user.id

    converting = queue.cancel(user_id)
    waiting = await repo.clear_stickers(user_id)
    busy = bool(await repo.active_for(user_id) or await repo.is_building(user_id)
                or await repo.asking_for(user_id) or await repo.editing_for(user_id)
                or await repo.importing_for(user_id))

    await repo.clear_active(user_id)
    await repo.set_building(user_id, False)
    await repo.set_pending(user_id, None)
    await repo.set_asking(user_id, None)
    await repo.set_editing(user_id, None)
    await repo.set_importing(user_id, None)
    await drop_preview(message, user_id)

    if not (converting or waiting or busy):
        await message.answer("Nothing to cancel.")
        return
    dropped = f" {converting + waiting} dropped." if converting + waiting else ""
    await message.answer(f"Cancelled.{dropped}")

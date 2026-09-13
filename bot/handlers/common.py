from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.utils.formatting import Bold, Text, as_marked_section

from bot.commands import help_content
from bot.handlers.packs import drop_preview
from db.packs import PackRepo
from convert.queue import JobQueue
from convert.spec import FPS, LONG_SIDE, MAX_BYTES, MAX_DURATION, STILL_DURATION

router = Router()

START = Text(
    "Send a picture, sticker, GIF or video - it comes back as a video sticker, "
    "ready to go into a pack.\n\n",
    "Or build the pack right here:\n",
    "/newpack - name it, send files, /done\n",
    "/mypacks - add stickers, change an emoji, delete a pack\n",
    "/import - copy a pack made in @Stickers or another bot\n\n",
    "/help for the rest.",
)

FORMAT = as_marked_section(
    Bold("Every file comes back as"),
    Text("WebM video, VP9 codec, transparency kept"),
    Text(f"{LONG_SIDE} px on the long side, no black bars added"),
    Text(f"{MAX_DURATION:.0f} seconds at most, {FPS} frames per second, sound stripped"),
    Text(f"under {MAX_BYTES // 1024} KB, the limit Telegram sets"),
    Text(f"a still picture turned into a {STILL_DURATION:g} second clip"),
    marker="- ",
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

"""The guided pack flow: one sticker at a time, each waiting for its emoji."""

import logging

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from db.packs import PackRepo
from models import QueuedSticker
from packs import PackError, PackManager

log = logging.getLogger(__name__)

USE_SUGGESTED = "emoji:use"


def prompt_keyboard(suggested: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"Click to {suggested}", callback_data=USE_SUGGESTED),
    ]])


def prompt_text(sticker: QueuedSticker, waiting: int) -> str:
    queued = f"\n{waiting - 1} more waiting." if waiting > 1 else ""
    return f"Sticker accepted. Send the emoji for it.{queued}"


async def ask_for_emoji(message: Message, user_id: int, repo: PackRepo) -> bool:
    """Show the prompt for the sticker at the head of the queue, if there is one."""
    sticker = await repo.head_sticker(user_id)
    if sticker is None:
        return False

    suggested = sticker.suggested or await repo.emoji_for(user_id)
    waiting = await repo.count_stickers(user_id)
    await message.answer(prompt_text(sticker, waiting),
                         reply_markup=prompt_keyboard(suggested))
    return True


async def accept_emoji(message: Message, user_id: int, emoji: str,
                       repo: PackRepo, packs: PackManager) -> None:
    """Put the waiting sticker into the pack, then move on to the next one."""
    sticker = await repo.head_sticker(user_id)
    if sticker is None:
        await message.answer("Nothing is waiting for an emoji. Send a file.")
        return

    title = await repo.take_pending(user_id)
    try:
        if title:
            pack = await packs.create(user_id, title, sticker.file_id, emoji)
            await repo.pop_sticker(sticker.id)
            await message.answer(
                f"Sticker added! {pack.title} is live: {PackManager.link(pack.name)}\n"
                "Send another file, or /done when you are finished.",
                link_preview_options={"is_disabled": True},
            )
        else:
            name = await repo.active_for(user_id)
            if not name:
                await message.answer("No pack is active. /newpack starts one.")
                return
            await packs.add(user_id, name, sticker.file_id, emoji)
            await repo.pop_sticker(sticker.id)
            await message.answer("Sticker added! Send another, or /done when you are finished.")
    except PackError as exc:
        if title:
            await repo.set_pending(user_id, title)
        await message.answer(str(exc))
        return
    except Exception:
        log.exception("could not add a sticker for user %s", user_id)
        if title:
            await repo.set_pending(user_id, title)
        await message.answer("Could not add that one. Send the emoji again to retry.")
        return

    await ask_for_emoji(message, user_id, repo)

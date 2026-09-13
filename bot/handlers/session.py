"""The guided pack flow: one sticker at a time, each waiting for its emoji."""

import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from db.packs import PackRepo
from packs import PackError, PackManager

log = logging.getLogger(__name__)

USE_SUGGESTED = "emoji:use"


def prompt_keyboard(suggested: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"Click to {suggested}", callback_data=USE_SUGGESTED),
    ]])


def prompt_text(waiting: int) -> str:
    queued = f" {waiting - 1} more." if waiting > 1 else ""
    return f"Sticker accepted. Send an emoji.{queued}"


async def ask_for_emoji(message: Message, user_id: int, repo: PackRepo) -> bool:
    """Ask about the sticker at the head of the queue, quoting the file it came from."""
    sticker = await repo.head_sticker(user_id)
    if sticker is None or sticker.file_id is None or sticker.prompt_msg is not None:
        return False

    suggested = sticker.suggested or await repo.emoji_for(user_id)
    waiting = await repo.count_stickers(user_id)
    text = prompt_text(waiting)
    keyboard = prompt_keyboard(suggested)
    try:
        sent = await message.answer(text, reply_markup=keyboard,
                                    reply_to_message_id=sticker.source_msg)
    except TelegramBadRequest:
        sent = await message.answer(text, reply_markup=keyboard)
    await repo.set_prompt(sticker.id, sent.message_id)
    return True


async def accept_emoji(message: Message, user_id: int, emoji: str,
                       repo: PackRepo, packs: PackManager) -> None:
    """Give the waiting sticker its emoji, then move on to the next one."""
    sticker = await repo.head_sticker(user_id)
    if sticker is None:
        await message.answer("Send a file first.")
        return

    name = await repo.active_for(user_id)
    if name:
        # an existing pack takes stickers straight away, a new one is only built on /done
        try:
            await packs.add(user_id, name, sticker.file_id, emoji)
        except PackError as exc:
            await message.answer(str(exc))
            return
        except Exception:
            log.exception("could not add a sticker for user %s", user_id)
            await message.answer("Failed. Send the emoji again.")
            return
        await repo.pop_sticker(sticker.id)
    else:
        await repo.name_sticker(sticker.id, emoji)

    await _mark(message, sticker, emoji)
    if await ask_for_emoji(message, user_id, repo):
        return
    if await repo.count_stickers(user_id) == 0:
        await message.answer("Send another or /done.")


async def _mark(message: Message, sticker, emoji: str) -> None:
    """Leave the answered prompt showing which emoji it got."""
    if sticker.prompt_msg is None:
        return
    try:
        await message.bot.edit_message_text(f"{emoji} added.", chat_id=message.chat.id,
                                            message_id=sticker.prompt_msg)
    except TelegramBadRequest:
        log.debug("prompt %s could not be marked", sticker.prompt_msg)

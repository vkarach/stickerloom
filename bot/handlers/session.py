"""The guided pack flow: one sticker at a time, each waiting for its emoji."""

import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from db.packs import PackRepo
from i18n import Translator
from packs import PackError, PackManager

log = logging.getLogger(__name__)

USE_SUGGESTED = "emoji:use"
ADD_ANYWAY = "dup:add"
SKIP_DUPLICATE = "dup:skip"


def duplicate_keyboard(t: Translator) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t("dup.add_anyway"), callback_data=ADD_ANYWAY),
        InlineKeyboardButton(text=t("dup.skip"), callback_data=SKIP_DUPLICATE),
    ]])


async def is_duplicate(user_id: int, sticker, name: str | None, repo: PackRepo) -> bool:
    """The same file twice, either already in the pack or twice in this batch."""
    if not sticker.sha:
        return False
    if name:
        return await repo.has_sha(name, sticker.sha)
    return sticker.sha in await repo.queued_shas(user_id, sticker.id)


def prompt_keyboard(suggested: str, t: Translator) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t("sticker.button", emoji=suggested),
                             callback_data=USE_SUGGESTED),
    ]])


def prompt_text(waiting: int, t: Translator) -> str:
    if waiting > 1:
        return t("sticker.accepted_more", n=waiting - 1)
    return t("sticker.accepted")


async def ask_for_emoji(message: Message, user_id: int, repo: PackRepo,
                        t: Translator) -> bool:
    """Ask about the sticker at the head of the queue, quoting the file it came from."""
    sticker = await repo.head_sticker(user_id)
    if sticker is None or sticker.file_id is None or sticker.prompt_msg is not None:
        return False

    if not await repo.claim_prompt(sticker.id):
        return False

    suggested = sticker.suggested or await repo.emoji_for(user_id)
    waiting = await repo.count_stickers(user_id)
    text = prompt_text(waiting, t)
    keyboard = prompt_keyboard(suggested, t)
    try:
        try:
            sent = await message.answer(text, reply_markup=keyboard,
                                        reply_to_message_id=sticker.source_msg)
        except TelegramBadRequest:
            sent = await message.answer(text, reply_markup=keyboard)
    except Exception:
        await repo.release_prompt(sticker.id)
        raise
    await repo.set_prompt(sticker.id, sent.message_id)
    return True


async def accept_emoji(message: Message, user_id: int, emoji: str,
                       repo: PackRepo, packs: PackManager, t: Translator) -> None:
    """Give the waiting sticker its emoji, then move on to the next one."""
    sticker = await repo.head_sticker(user_id)
    if sticker is None:
        await message.answer(t("sticker.none_waiting"))
        return

    name = await repo.active_for(user_id)
    if await is_duplicate(user_id, sticker, name, repo):
        await repo.mark_duplicate(sticker.id, emoji)
        warning, keys = t("dup.warn"), duplicate_keyboard(t)
        if not await _mark(message, sticker, warning, keys):
            await message.answer(warning, reply_markup=keys)
        return
    if name:
        # an existing pack takes stickers straight away, a new one is only built on /done
        try:
            await packs.add(user_id, name, sticker.file_id, emoji)
        except PackError as exc:
            await message.answer(t(exc.key, **exc.params))
            return
        except Exception:
            log.exception("could not add a sticker for user %s", user_id)
            await message.answer(t("sticker.add_failed"))
            return
        await repo.pop_sticker(sticker.id)
        await repo.remember_sha(name, sticker.sha)
    else:
        await repo.name_sticker(sticker.id, emoji)

    await _mark(message, sticker, t("sticker.added", emoji=emoji))
    if await ask_for_emoji(message, user_id, repo, t):
        return
    if await repo.count_stickers(user_id) == 0:
        await message.answer(t("sticker.send_another"))


async def resolve_duplicate(message: Message, user_id: int, keep: bool,
                            repo: PackRepo, packs: PackManager, t: Translator) -> None:
    """Answer the Add anyway / Skip question about the sticker held aside."""
    sticker = await repo.first_duplicate(user_id)
    if sticker is None:
        return

    if not keep:
        await repo.pop_sticker(sticker.id)
        await _mark(message, sticker, t("sticker.skipped"))
    else:
        name = await repo.active_for(user_id)
        if name:
            try:
                await packs.add(user_id, name, sticker.file_id, sticker.emoji)
            except Exception as exc:
                log.warning("could not add a duplicate for user %s: %s", user_id, exc)
                await message.answer(t("sticker.add_failed"))
                return
            await repo.pop_sticker(sticker.id)
            await repo.remember_sha(name, sticker.sha)
        else:
            await repo.clear_duplicate(sticker.id)
        await _mark(message, sticker, t("sticker.added", emoji=sticker.emoji))

    if await ask_for_emoji(message, user_id, repo, t):
        return
    if await repo.count_stickers(user_id) == 0:
        await message.answer(t("sticker.send_another"))


async def _mark(message: Message, sticker, text: str,
                keyboard: InlineKeyboardMarkup | None = None) -> bool:
    """Leave the answered prompt showing what became of it."""
    if sticker.prompt_msg is None:
        return False
    try:
        await message.bot.edit_message_text(text, chat_id=message.chat.id,
                                            message_id=sticker.prompt_msg,
                                            reply_markup=keyboard)
    except TelegramBadRequest:
        log.debug("prompt %s could not be marked", sticker.prompt_msg)
        return False
    return True

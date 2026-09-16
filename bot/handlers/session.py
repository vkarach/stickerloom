"""The guided pack flow: one sticker at a time, each waiting for its emoji."""

import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from db.packs import PackRepo
from i18n import Translator
from packs import PackError, PackManager
from packs.manager import STICKER_FORMAT

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


def _format_of(sticker) -> str:
    return sticker.fmt or STICKER_FORMAT


async def accept_emoji(message: Message, user_id: int, emoji: str,
                       repo: PackRepo, packs: PackManager, t: Translator) -> None:
    """Give the waiting sticker its emoji, then move on to the next one."""
    sticker = await repo.head_sticker(user_id)
    if sticker is None:
        await message.answer(t("sticker.none_waiting"))
        return

    # the file is still converting: hold the emoji, it goes in the moment the file lands
    if sticker.file_id is None:
        if not await repo.claim_emoji(sticker.id, emoji):
            return
        await _say(message, sticker, t("sticker.remembered", emoji=emoji))
        # the file may have landed between that read and that write, leaving it to nobody
        await settle(message, user_id, sticker.id, repo, packs, t)
        return

    name = await repo.open_pack(user_id)
    if await is_duplicate(user_id, sticker, name, repo):
        await repo.mark_duplicate(sticker.id, emoji)
        warning, keys = t("dup.warn"), duplicate_keyboard(t)
        if not await _mark(message, sticker, warning, keys):
            await message.answer(warning, reply_markup=keys)
        return
    if not await repo.claim_emoji(sticker.id, emoji):
        return

    if name:
        # an existing pack takes stickers straight away, a new one is only built on /done
        owned = await repo.claim_ready(sticker.id)
        if owned is None:
            return
        try:
            await packs.add(user_id, name, owned.file_id, emoji, _format_of(owned))
        except PackError as exc:
            await message.answer(t(exc.key, **exc.params))
            return
        except Exception:
            log.exception("could not add a sticker for user %s", user_id)
            await message.answer(t("sticker.add_failed"))
            return
        await repo.remember_sha(name, owned.sha)

    await _mark(message, sticker, t("sticker.added", emoji=emoji))
    await _move_on(message, user_id, repo, t)


# a sticker answered before it was ready is settled here, once the file exists
async def settle(message: Message, user_id: int, sticker_id: int,
                 repo: PackRepo, packs: PackManager, t: Translator) -> None:
    waiting = await repo.sticker(sticker_id)
    if waiting is None or waiting.emoji is None or waiting.file_id is None:
        return

    name = await repo.open_pack(user_id)
    if await is_duplicate(user_id, waiting, name, repo):
        await repo.mark_duplicate(waiting.id, waiting.emoji)
        await message.answer(t("dup.warn"), reply_markup=duplicate_keyboard(t))
        return
    if not name:
        return

    # whoever takes it out of the queue owns it, so it cannot be added twice
    sticker = await repo.claim_ready(sticker_id)
    if sticker is None:
        return

    try:
        await packs.add(user_id, name, sticker.file_id, sticker.emoji, _format_of(sticker))
    except PackError as exc:
        await message.answer(t(exc.key, **exc.params))
        return
    except Exception:
        log.exception("could not add a held sticker for user %s", user_id)
        await message.answer(t("sticker.add_failed"))
        return

    await repo.remember_sha(name, sticker.sha)
    await _say(message, sticker, t("sticker.added", emoji=sticker.emoji))
    await _move_on(message, user_id, repo, t)


# ask about the next one, and nudge only when there is nothing left to wait for at all
async def _move_on(message: Message, user_id: int, repo: PackRepo, t: Translator) -> None:
    if await ask_for_emoji(message, user_id, repo, t):
        return
    if await repo.queued_count(user_id) == 0:
        await message.answer(t("sticker.send_another"))


async def _say(message: Message, sticker, text: str) -> None:
    try:
        await message.answer(text, reply_to_message_id=sticker.source_msg)
    except TelegramBadRequest:
        await message.answer(text)


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
        name = await repo.open_pack(user_id)
        await repo.clear_duplicate(sticker.id)
        if name:
            owned = await repo.claim_ready(sticker.id)
            if owned is None:
                return
            try:
                await packs.add(user_id, name, owned.file_id, owned.emoji, _format_of(owned))
            except Exception as exc:
                log.warning("could not add a duplicate for user %s: %s", user_id, exc)
                await message.answer(t("sticker.add_failed"))
                return
            await repo.remember_sha(name, owned.sha)
        await _mark(message, sticker, t("sticker.added", emoji=sticker.emoji))

    await _move_on(message, user_id, repo, t)


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

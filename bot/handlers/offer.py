"""The way into a pack from a plain conversion, so the answer is not a dead end."""

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.handlers.session import ask_for_emoji
from db.packs import PackRepo
from packs.emoji import is_emoji

log = logging.getLogger(__name__)

router = Router()

OFFER = "offer:open"
PICK = "offer:pick:"
NEW = "offer:new"


def offer_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Add to a pack", callback_data=OFFER),
    ]])


def _picker(packs: list) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=pack.title, callback_data=f"{PICK}{index}")]
            for index, pack in enumerate(packs)]
    rows.append([InlineKeyboardButton(text="New pack", callback_data=NEW)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == OFFER)
async def show_packs(callback: CallbackQuery, repo: PackRepo) -> None:
    assert callback.from_user
    mine = await repo.list_for(callback.from_user.id)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=_picker(mine))


@router.callback_query(F.data.startswith(PICK) | (F.data == NEW))
async def take_it(callback: CallbackQuery, repo: PackRepo) -> None:
    assert callback.data and callback.from_user
    user_id = callback.from_user.id
    if not isinstance(callback.message, Message) or not callback.message.document:
        await callback.answer("That file is gone")
        return

    if callback.data == NEW:
        await repo.clear_active(user_id)
        await repo.set_building(user_id, True)
        await repo.set_asking(user_id, "title")
    else:
        mine = await repo.list_for(user_id)
        index = int(callback.data[len(PICK):])
        if index >= len(mine):
            await callback.answer("That pack is gone")
            return
        await repo.set_active(user_id, mine[index].name)
        await repo.set_building(user_id, False)
        await repo.set_asking(user_id, None)

    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)

    # the document this bot just sent is already a valid sticker file on Telegram
    document = callback.message.document
    await repo.push_sticker(user_id, document.file_id, document.file_name or "sticker",
                            _emoji_of(callback.message), callback.message.message_id)

    if callback.data == NEW:
        await callback.message.answer("Send a name for the pack.")
        return
    await ask_for_emoji(callback.message, user_id, repo)


def _emoji_of(message: Message) -> str | None:
    """The conversion put the source emoji at the head of the caption."""
    head = (message.caption or "").split(" ", 1)[0]
    return head if is_emoji(head) else None

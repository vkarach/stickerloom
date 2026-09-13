from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.formatting import Bold, Text, as_marked_section

from bot.commands import help_content
from bot.handlers.packs import drop_preview
from bot.setup import setup_commands
from convert.queue import JobQueue
from convert.spec import FPS, LONG_SIDE, MAX_BYTES, MAX_DURATION, STILL_DURATION
from db.packs import PackRepo
from i18n import Translator, languages

router = Router()

PICK_LANG = "lang:"


def _format(t: Translator):
    return as_marked_section(
        Bold(t("format.title")),
        Text(t("format.codec")),
        Text(t("format.side", side=LONG_SIDE)),
        Text(t("format.length", seconds=f"{MAX_DURATION:.0f}", fps=FPS)),
        Text(t("format.weight", kb=MAX_BYTES // 1024)),
        Text(t("format.still", seconds=f"{STILL_DURATION:g}")),
        marker="- ",
    )


def _language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=Translator(lang)("lang.name"),
                              callback_data=PICK_LANG + lang)]
        for lang in languages()
    ])


@router.message(CommandStart())
async def cmd_start(message: Message, t: Translator) -> None:
    await message.answer(t("start"))


@router.message(Command("help"))
async def cmd_help(message: Message, t: Translator) -> None:
    await message.answer(**help_content(t).as_kwargs())


@router.message(Command("format"))
async def cmd_format(message: Message, t: Translator) -> None:
    await message.answer(**_format(t).as_kwargs())


@router.message(Command("lang"))
async def cmd_lang(message: Message, t: Translator) -> None:
    await message.answer(t("lang.ask"), reply_markup=_language_keyboard())


@router.callback_query(lambda c: c.data and c.data.startswith(PICK_LANG))
async def pick_lang(callback: CallbackQuery, repo: PackRepo) -> None:
    assert callback.data and callback.from_user
    lang = callback.data[len(PICK_LANG):]
    await repo.set_lang(callback.from_user.id, lang)

    spoken = Translator(lang)
    if await _emoji_is_untouched(callback.from_user.id, repo):
        await repo.set_emoji(callback.from_user.id, spoken("lang.emoji"))
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.edit_text(spoken("lang.set"))
        await setup_commands(callback.message.bot, spoken, callback.from_user.id)


async def _emoji_is_untouched(user_id: int, repo: PackRepo) -> bool:
    """A language may set the default emoji, but never overwrite one a user picked."""
    chosen = await repo.chosen_emoji(user_id)
    return chosen is None or chosen in {Translator(lang)("lang.emoji") for lang in languages()}


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, queue: JobQueue, repo: PackRepo, t: Translator) -> None:
    """One stop button: the convert queue, the pack being built and the sticker editor."""
    assert message.from_user
    user_id = message.from_user.id

    converting = queue.cancel(user_id)
    waiting = await repo.clear_stickers(user_id)
    busy = bool(await repo.active_for(user_id) or await repo.is_building(user_id)
                or await repo.asking_for(user_id) or await repo.editing_for(user_id)
                or await repo.importing_for(user_id) or await repo.deleting_for(user_id))

    await repo.clear_active(user_id)
    await repo.set_building(user_id, False)
    await repo.set_pending(user_id, None)
    await repo.set_asking(user_id, None)
    await repo.set_editing(user_id, None)
    await repo.set_importing(user_id, None)
    await repo.set_deleting(user_id, None)
    await repo.set_editing_pack(user_id, None)
    await drop_preview(message, user_id)

    dropped = converting + waiting
    if not (dropped or busy):
        await message.answer(t("cancel.nothing"))
        return
    await message.answer(t("cancel.dropped", n=dropped) if dropped else t("cancel.done"))

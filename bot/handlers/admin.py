import time

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import BaseFilter, Command
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
                           TelegramObject)
from aiogram.utils.formatting import Bold, Text, as_list, as_marked_section

from convert.queue import JobQueue
from db.packs import PackRepo
from i18n import Translator
from models import Overview

router = Router()

REFRESH = "admin:refresh"
STARTED = time.monotonic()


class IsAdmin(BaseFilter):
    # a stranger gets no reply at all, so the panel cannot be probed for
    async def __call__(self, event: TelegramObject, is_admin: bool = False) -> bool:
        return is_admin


router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


def _uptime(t: Translator) -> str:
    seconds = int(time.monotonic() - STARTED)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60
    if days:
        return t("admin.days", n=days, hours=hours)
    return t("admin.hours", n=hours, minutes=minutes) if hours else t("admin.minutes", n=minutes)


def _report(overview: Overview, queue: JobQueue, t: Translator) -> Text:
    spoken = ", ".join(f"{lang} {n}" for lang, n in overview.languages) or t("admin.nobody")
    return as_list(
        as_marked_section(
            Bold(t("admin.runtime")),
            Text(t("admin.uptime", value=_uptime(t))),
            Text(t("admin.converting", n=queue.depth())),
            marker="- ",
        ),
        as_marked_section(
            Bold(t("admin.stored")),
            Text(t("admin.users", n=overview.users, spoken=spoken)),
            Text(t("admin.packs", n=overview.packs, owners=overview.owners)),
            Text(t("admin.new_packs", today=overview.packs_today, week=overview.packs_week)),
            Text(t("admin.stickers", n=overview.stickers)),
            Text(t("admin.queued", n=overview.queued)),
            marker="- ",
        ),
        sep="\n\n",
    )


def _keyboard(t: Translator) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t("admin.refresh"), callback_data=REFRESH)]
    ])


@router.message(Command("stats"))
async def cmd_stats(message: Message, repo: PackRepo, queue: JobQueue, t: Translator) -> None:
    report = _report(await repo.overview(), queue, t)
    await message.answer(**report.as_kwargs(), reply_markup=_keyboard(t))


@router.callback_query(lambda c: c.data == REFRESH)
async def refresh_stats(callback: CallbackQuery, repo: PackRepo, queue: JobQueue,
                        t: Translator) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    report = _report(await repo.overview(), queue, t)
    try:
        await callback.message.edit_text(**report.as_kwargs(), reply_markup=_keyboard(t))
    except TelegramBadRequest:
        pass

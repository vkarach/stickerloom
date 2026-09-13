import asyncio
import logging
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, InputSticker

from models import Pack
from packs.errors import NameTaken, PackFull, PackNotFound, PackNotOurs
from packs.names import pack_name

log = logging.getLogger(__name__)

MAX_INITIAL = 50
STICKER_FORMAT = "video"
ADDSTICKERS_URL = "https://t.me/addstickers/"

# a freshly created set rejects additions for a moment, so STICKERSET_INVALID is retried first
RETRY_DELAYS = (0.0, 0.6, 1.5)


class PackManager:
    """Every sticker set operation, mapped to errors a user can act on."""

    def __init__(self, bot, repo):
        self._bot = bot
        self._repo = repo

    @staticmethod
    def link(name: str) -> str:
        return ADDSTICKERS_URL + name

    async def create(self, user_id: int, title: str, path: Path, emoji: str) -> Pack:
        me = await self._bot.me()
        name = pack_name(title, me.username)
        sticker = InputSticker(
            sticker=FSInputFile(path), format=STICKER_FORMAT, emoji_list=[emoji],
        )
        try:
            await self._bot.create_new_sticker_set(
                user_id=user_id, name=name, title=title, stickers=[sticker],
            )
        except TelegramBadRequest as exc:
            raise _translate(exc, creating=True) from exc

        log.info("user %s created pack %s", user_id, name)
        pack = await self._repo.remember(user_id, name, title)
        await self._repo.set_active(user_id, name)
        return pack

    async def add(self, user_id: int, name: str, path: Path, emoji: str) -> None:
        sticker = InputSticker(
            sticker=FSInputFile(path), format=STICKER_FORMAT, emoji_list=[emoji],
        )
        await self._push(user_id, name, sticker)
        log.info("user %s added a sticker to %s", user_id, name)

    async def _push(self, user_id: int, name: str, sticker: InputSticker) -> None:
        last: TelegramBadRequest | None = None
        for delay in RETRY_DELAYS:
            if delay:
                await asyncio.sleep(delay)
            try:
                await self._bot.add_sticker_to_set(user_id=user_id, name=name, sticker=sticker)
                return
            except TelegramBadRequest as exc:
                last = exc
                if "STICKERSET_INVALID" not in exc.message.upper():
                    break
                log.debug("%s not ready yet, retrying", name)
        raise _translate(last) from last

    async def import_set(self, user_id: int, source_name: str, title: str) -> Pack:
        try:
            source = await self._bot.get_sticker_set(name=source_name)
        except TelegramBadRequest as exc:
            raise PackNotFound(f"No sticker set called {source_name}") from exc

        stickers = list(source.stickers or [])
        if not stickers:
            raise PackNotFound(f"{source_name} has no stickers to copy")

        fallback = await self._repo.emoji_for(user_id)
        me = await self._bot.me()
        name = pack_name(title, me.username)

        first = [self._copy(s, fallback) for s in stickers[:MAX_INITIAL]]
        try:
            await self._bot.create_new_sticker_set(
                user_id=user_id, name=name, title=title, stickers=first,
            )
        except TelegramBadRequest as exc:
            raise _translate(exc, creating=True) from exc

        pack = await self._repo.remember(user_id, name, title)
        await self._repo.set_active(user_id, name)

        for sticker in stickers[MAX_INITIAL:]:
            await self._push(user_id, name, self._copy(sticker, fallback))

        log.info("user %s imported %s into %s", user_id, source_name, name)
        return pack

    @staticmethod
    def _copy(sticker, fallback: str) -> InputSticker:
        return InputSticker(
            sticker=sticker.file_id,
            format=STICKER_FORMAT,
            emoji_list=[sticker.emoji or fallback],
        )


def _translate(exc: TelegramBadRequest, creating: bool = False) -> Exception:
    message = exc.message.upper()
    if "TOO_MUCH" in message or "TOO MUCH" in message:
        return PackFull("That pack is full. Start a new one with /newpack.")
    if "OCCUPIED" in message:
        return NameTaken("That name is taken, try /newpack again.")
    if "STICKERSET_INVALID" in message:
        if creating:
            return NameTaken("Telegram refused that name, try /newpack again.")
        return PackNotOurs(
            "This bot cannot edit that pack. Only packs it created itself can be changed, "
            "so copy it first with /import."
        )
    return exc

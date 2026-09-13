import asyncio
import logging
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, InputSticker

from models import Pack
from packs.emoji import MAX_EMOJI, split_emoji
from packs.errors import NameTaken, PackFull, PackNotFound, PackNotOurs
from packs.names import build_name

log = logging.getLogger(__name__)

MAX_INITIAL = 50
STICKER_FORMAT = "video"
ADDSTICKERS_URL = "https://t.me/addstickers/"

# a set answers STICKERSET_INVALID to writes for a while after it is created
RETRY_DELAYS = (0.0, 0.6, 1.5)
# measured: writes to a fresh set were refused for 19s, so a new pack gets a far longer budget
FRESH_DELAYS = (0.0, 1.0, 2.0, 3.0, 5.0, 5.0, 5.0, 5.0, 5.0)


class PackManager:
    """Every sticker set operation, mapped to errors a user can act on."""

    def __init__(self, bot, repo):
        self._bot = bot
        self._repo = repo

    @staticmethod
    def link(name: str) -> str:
        return ADDSTICKERS_URL + name

    async def upload(self, user_id: int, path: Path) -> str:
        """Put the file on Telegram's servers without posting it, and keep its file_id."""
        uploaded = await self._bot.upload_sticker_file(
            user_id=user_id, sticker=FSInputFile(path), sticker_format=STICKER_FORMAT,
        )
        return uploaded.file_id

    async def size(self, name: str) -> int | None:
        """Sticker count, or None when the set is gone."""
        try:
            found = await self._bot.get_sticker_set(name=name)
        except TelegramBadRequest:
            return None
        if not await self.alive(name, found.title):
            return None
        return len(found.stickers or [])

    async def alive(self, name: str, title: str) -> bool:
        """getStickerSet answers for deleted sets too, so liveness needs a write."""
        try:
            await self._bot.set_sticker_set_title(name=name, title=title)
        except TelegramBadRequest:
            return False
        return True

    async def remove(self, user_id: int, name: str) -> None:
        try:
            await self._bot.delete_sticker_set(name=name)
        except TelegramBadRequest as exc:
            raise _translate(exc) from exc
        await self._repo.forget(user_id, name)
        log.info("user %s deleted pack %s", user_id, name)

    async def stickers(self, name: str) -> list:
        """Every sticker in the set as (file_id, emoji)."""
        found = await self._bot.get_sticker_set(name=name)
        return [(s.file_id, s.emoji or "") for s in found.stickers or []]

    async def retag(self, file_id: str, emoji: str) -> None:
        try:
            await self._bot.set_sticker_emoji_list(sticker=file_id, emoji_list=_emoji_list(emoji))
        except TelegramBadRequest as exc:
            raise _translate(exc) from exc

    async def drop_sticker(self, file_id: str) -> None:
        try:
            await self._bot.delete_sticker_from_set(sticker=file_id)
        except TelegramBadRequest as exc:
            raise _translate(exc) from exc

    async def create(self, user_id: int, base: str, title: str,
                     entries: list) -> tuple[Pack, int]:
        """Create the set with everything at once; Telegram only balks at more than 50."""
        me = await self._bot.me()
        name = build_name(base, me.username)
        first = [_sticker(source, emoji) for source, emoji in entries[:MAX_INITIAL]]
        try:
            await self._bot.create_new_sticker_set(
                user_id=user_id, name=name, title=title, stickers=first,
            )
        except TelegramBadRequest as exc:
            raise _translate(exc, creating=True) from exc

        added = len(first)
        for source, emoji in entries[MAX_INITIAL:]:
            try:
                await self._push(user_id, name, _sticker(source, emoji), fresh=True)
                added += 1
            except Exception as exc:
                log.warning("could not top up %s: %s", name, exc)

        log.info("user %s created pack %s with %d stickers", user_id, name, added)
        pack = await self._repo.remember(user_id, name, title)
        await self._repo.set_active(user_id, name)
        return pack, added

    async def add(self, user_id: int, name: str, source, emoji: str) -> None:
        await self._push(user_id, name, _sticker(source, emoji))
        log.info("user %s added a sticker to %s", user_id, name)

    async def _push(self, user_id: int, name: str, sticker: InputSticker,
                    fresh: bool = False) -> None:
        last: TelegramBadRequest | None = None
        for delay in (FRESH_DELAYS if fresh else RETRY_DELAYS):
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

    async def look_up(self, name: str):
        """The source pack of an import, read before the user is asked anything."""
        try:
            return await self._bot.get_sticker_set(name=name)
        except TelegramBadRequest as exc:
            raise PackNotFound(f"No pack called {name}.") from exc

    async def import_set(self, user_id: int, source_name: str, base: str,
                         title: str) -> tuple[Pack, int]:
        source = await self.look_up(source_name)
        stickers = list(source.stickers or [])
        if not stickers:
            raise PackNotFound(f"{source_name} is empty.")

        fallback = await self._repo.emoji_for(user_id)
        me = await self._bot.me()
        name = build_name(base, me.username)

        fmt = _format_of(stickers[0])
        first = [self._copy(s, fallback, fmt) for s in stickers[:MAX_INITIAL]]
        try:
            await self._bot.create_new_sticker_set(
                user_id=user_id, name=name, title=title, stickers=first,
            )
        except TelegramBadRequest as exc:
            raise _translate(exc, creating=True) from exc

        copied = len(first)
        for sticker in stickers[MAX_INITIAL:]:
            try:
                await self._push(user_id, name, self._copy(sticker, fallback, fmt), fresh=True)
                copied += 1
            except Exception as exc:
                log.warning("could not copy a sticker into %s: %s", name, exc)

        log.info("user %s imported %s into %s, %d of %d", user_id, source_name, name,
                 copied, len(stickers))
        pack = await self._repo.remember(user_id, name, title)
        return pack, copied

    @staticmethod
    def _copy(sticker, fallback: str, fmt: str) -> InputSticker:
        return _sticker(sticker.file_id, sticker.emoji or fallback, fmt)


def _sticker(source, emoji: str, fmt: str = STICKER_FORMAT) -> InputSticker:
    """Accepts a local path or a file_id already on Telegram's servers."""
    payload = FSInputFile(source) if isinstance(source, Path) else source
    return InputSticker(sticker=payload, format=fmt, emoji_list=_emoji_list(emoji))


def _format_of(sticker) -> str:
    """A set holds one kind of sticker, so the source decides what the copy is."""
    if sticker.is_video:
        return "video"
    return "animated" if sticker.is_animated else "static"


def _emoji_list(emoji: str) -> list[str]:
    return split_emoji(emoji)[:MAX_EMOJI] or [emoji]


def _translate(exc: TelegramBadRequest, creating: bool = False) -> Exception:
    message = exc.message.upper()
    if "TOO_MUCH" in message or "TOO MUCH" in message:
        return PackFull("Pack is full. /newpack starts another.")
    if "OCCUPIED" in message:
        return NameTaken("Prefix taken. Send another.")
    if "STICKERSET_INVALID" in message:
        if creating:
            return NameTaken("Telegram refused that prefix. Send another.")
        return PackNotOurs("This bot can only edit packs it made. Copy it with /import.")
    return exc

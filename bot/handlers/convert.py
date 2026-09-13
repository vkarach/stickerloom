import hashlib
import logging
from pathlib import Path
from typing import NamedTuple

from aiogram import Bot, F, Router
from aiogram.types import FSInputFile, Message

from bot.handlers.offer import offer_keyboard
from bot.handlers.session import ask_for_emoji
from db.packs import PackRepo
from packs import PackManager

from convert.errors import StickerloomError, UnsupportedInput
from convert.queue import JobQueue
from convert.spec import (
    MAX_SOURCE_BYTES,
    STILL_DURATION,
    OUTPUT_SUFFIX,
    REJECTED_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
)
from models import ConvertResult, Job

log = logging.getLogger(__name__)

router = Router()

MEDIA = F.document | F.photo | F.sticker | F.animation | F.video | F.video_note

TGS_HINT = "Animated stickers already work in a pack, nothing to convert."

# a file from the GIF panel arrives with a caption for a name, or with none
BY_MIME = {
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
}


def _named(file_name: str | None, mime: str | None, fallback: str) -> str:
    """Name the file so its extension is one we know, whatever Telegram called it."""
    suffix = Path(file_name or "").suffix.lower()
    if suffix in SUPPORTED_EXTENSIONS or suffix in REJECTED_EXTENSIONS:
        return file_name
    known = BY_MIME.get(mime or "")
    if not known:
        return file_name or fallback
    return Path(file_name or fallback).stem + known


class Source(NamedTuple):
    file_id: str
    name: str
    size: int
    emoji: str | None = None


def _source(message: Message) -> Source:
    """Pick the file to convert and name it, so the extension drives validation."""
    if message.document:
        doc = message.document
        name = _named(doc.file_name, doc.mime_type, "file")
        return Source(doc.file_id, name, doc.file_size or 0)
    if message.photo:
        photo = message.photo[-1]
        return Source(photo.file_id, "photo.jpg", photo.file_size or 0)
    if message.sticker:
        sticker = message.sticker
        if sticker.is_animated:
            raise UnsupportedInput(TGS_HINT)
        suffix = ".webm" if sticker.is_video else ".webp"
        return Source(sticker.file_id, f"sticker{suffix}", sticker.file_size or 0, sticker.emoji)
    if message.animation:
        anim = message.animation
        name = _named(anim.file_name, anim.mime_type, "animation.mp4")
        return Source(anim.file_id, name, anim.file_size or 0)
    if message.video:
        video = message.video
        name = _named(video.file_name, video.mime_type, "video.mp4")
        return Source(video.file_id, name, video.file_size or 0)
    if message.video_note:
        note = message.video_note
        return Source(note.file_id, "video_note.mp4", note.file_size or 0)
    raise UnsupportedInput("Send a picture, sticker, GIF or short video.")


def _validate(name: str, size: int) -> None:
    suffix = Path(name).suffix.lower()
    if suffix in REJECTED_EXTENSIONS:
        raise UnsupportedInput(TGS_HINT)
    if suffix not in SUPPORTED_EXTENSIONS:
        listed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise UnsupportedInput(f"Cannot read {suffix or 'that'}. Supported: {listed}")
    if size > MAX_SOURCE_BYTES:
        raise UnsupportedInput(f"Too big, limit is {MAX_SOURCE_BYTES // (1024 * 1024)} MB.")


def _caption(result: ConvertResult, emoji: str | None) -> str:
    """The emoji rides along with the file, so a batch of answers stays paired up."""
    lead = f"{emoji} " if emoji else ""
    # a still is a clip only because Telegram wants one, its length says nothing
    length = f"{result.duration:.1f}s - " if result.duration > STILL_DURATION else ""
    return f"{lead}{result.width}x{result.height} - {length}{result.size // 1024} KB"


async def _in_pack_mode(user_id: int, repo: PackRepo) -> bool:
    return bool(await repo.is_building(user_id) or await repo.active_for(user_id))


async def _queue_for_pack(message: Message, user_id: int, spot: int, name: str,
                          result: ConvertResult, repo: PackRepo, packs: PackManager) -> None:
    """Fill in the reserved queue slot, then ask about it if it is the one in turn."""
    try:
        file_id = await packs.upload(user_id, result.path)
    except Exception:
        log.exception("could not upload %r for user %s", name, user_id)
        await repo.pop_sticker(spot)
        await message.answer("Telegram rejected that file.")
    else:
        await repo.attach(spot, file_id, _sha(result.path))
    await ask_for_emoji(message, user_id, repo)


def _sha(path: Path) -> str:
    """The only way to spot the same sticker twice: Telegram hands out no content hash."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


@router.message(MEDIA)
async def handle_media(message: Message, bot: Bot, queue: JobQueue,
                       repo: PackRepo, packs: PackManager) -> None:
    assert message.from_user
    user_id = message.from_user.id

    try:
        source = _source(message)
        _validate(source.name, source.size)
    except StickerloomError as exc:
        await message.answer(str(exc))
        return

    name = source.name
    # the slot is taken now, so a batch is asked about in the order it was sent
    spot = None
    if await _in_pack_mode(user_id, repo):
        spot = await repo.push_sticker(user_id, None, name, source.emoji, message.message_id)
    status = await message.answer(f"{name}: queued")

    async def fetch(work_dir: Path) -> Path:
        target = work_dir / name
        await bot.download(source.file_id, destination=target)
        return target

    async def on_status(_: str) -> None:
        await _edit(status, f"{name}: converting")

    async def on_done(result: ConvertResult) -> None:
        await _delete(status)
        if spot is not None:
            await _queue_for_pack(message, user_id, spot, name, result, repo, packs)
            return

        document = FSInputFile(result.path, filename=Path(name).stem + OUTPUT_SUFFIX)
        await message.answer_document(document, caption=_caption(result, source.emoji),
                                      reply_markup=offer_keyboard())

    async def on_error(exc: Exception) -> None:
        if spot is not None:
            await repo.pop_sticker(spot)
            await ask_for_emoji(message, user_id, repo)
        if isinstance(exc, StickerloomError):
            await _edit(status, f"{name}: {exc}")
            return
        log.exception("unexpected failure converting %r", name)
        await _edit(status, f"{name}: something went wrong")

    position = await queue.submit(Job(
        key=user_id, name=name, fetch=fetch,
        on_status=on_status, on_done=on_done, on_error=on_error,
    ))
    if position > 1:
        await _edit(status, f"{name}: queued, {position} in line")


async def _edit(status: Message, text: str) -> None:
    try:
        await status.edit_text(text)
    except Exception:
        log.debug("could not edit status message", exc_info=True)


async def _delete(status: Message) -> None:
    try:
        await status.delete()
    except Exception:
        log.debug("could not delete status message", exc_info=True)

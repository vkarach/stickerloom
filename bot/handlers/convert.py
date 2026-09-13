import logging
from pathlib import Path
from typing import NamedTuple

from aiogram import Bot, F, Router
from aiogram.types import FSInputFile, Message

from db.packs import PackRepo
from packs import PackError, PackManager

from convert.errors import StickerloomError, UnsupportedInput
from convert.queue import JobQueue
from convert.spec import (
    MAX_SOURCE_BYTES,
    OUTPUT_SUFFIX,
    REJECTED_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
)
from models import ConvertResult, Job

log = logging.getLogger(__name__)

router = Router()

MEDIA = F.document | F.photo | F.sticker | F.animation | F.video | F.video_note

TGS_HINT = (
    "Animated Telegram stickers (.tgs) are already usable in a pack, "
    "there is nothing to convert. Send a picture, GIF or video instead."
)


class Source(NamedTuple):
    file_id: str
    name: str
    size: int
    emoji: str | None = None


def _source(message: Message) -> Source:
    """Pick the file to convert and name it, so the extension drives validation."""
    if message.document:
        doc = message.document
        return Source(doc.file_id, doc.file_name or "file", doc.file_size or 0)
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
        return Source(anim.file_id, anim.file_name or "animation.mp4", anim.file_size or 0)
    if message.video:
        video = message.video
        return Source(video.file_id, video.file_name or "video.mp4", video.file_size or 0)
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
        raise UnsupportedInput(f"Cannot read {suffix or 'this file'}. Supported: {listed}")
    if size > MAX_SOURCE_BYTES:
        raise UnsupportedInput(
            f"That file is {size // (1024 * 1024)} MB. "
            f"Telegram only lets bots download up to {MAX_SOURCE_BYTES // (1024 * 1024)} MB."
        )


def _caption(result: ConvertResult) -> str:
    return (f"{result.width}x{result.height} - {result.duration:.1f}s - "
            f"{result.size // 1024} KB")


async def _into_pack(message: Message, user_id: int, result: ConvertResult,
                     emoji: str | None, repo: PackRepo, packs: PackManager) -> None:
    """Runs after the file is delivered, so a pack failure never costs the conversion."""
    pending = await repo.take_pending(user_id)
    active = None if pending else await repo.active_for(user_id)
    if not pending and not active:
        return

    chosen = emoji or await repo.emoji_for(user_id)
    try:
        if pending:
            pack = await packs.create(user_id, pending, result.path, chosen)
            await message.answer(
                f"Created {pack.title}: {PackManager.link(pack.name)}\n"
                "Keep sending files, they go into it. /nopack to stop.",
                link_preview_options={"is_disabled": True},
            )
            return
        await packs.add(user_id, active, result.path, chosen)
        await message.answer(f"Added to your pack with {chosen}")
    except PackError as exc:
        await message.answer(str(exc))
    except Exception:
        log.exception("pack step failed for user %s", user_id)
        await message.answer("The file is fine, but adding it to the pack failed.")


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
    status = await message.answer(f"{name}: queued")

    async def fetch(work_dir: Path) -> Path:
        target = work_dir / name
        await bot.download(source.file_id, destination=target)
        return target

    async def on_status(_: str) -> None:
        await _edit(status, f"{name}: converting")

    async def on_done(result: ConvertResult) -> None:
        document = FSInputFile(result.path, filename=Path(name).stem + OUTPUT_SUFFIX)
        await message.answer_document(document, caption=_caption(result))
        if source.emoji:
            await message.answer(source.emoji)
        await _delete(status)
        await _into_pack(message, user_id, result, source.emoji, repo, packs)

    async def on_error(exc: Exception) -> None:
        if isinstance(exc, StickerloomError):
            await _edit(status, f"{name}: {exc}")
            return
        log.exception("unexpected failure converting %r", name)
        await _edit(status, f"{name}: something went wrong, try another file")

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

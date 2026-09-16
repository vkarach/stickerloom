import hashlib
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import NamedTuple

from aiogram import Bot, F, Router
from aiogram.types import FSInputFile, Message

from bot.handlers.offer import offer_keyboard
from bot.handlers.session import ask_for_emoji, settle
import states
from db.packs import PackRepo
from i18n import Translator
from packs import PackManager
from packs.emoji import split_emoji

from convert.download import download, resolve
from convert.errors import StickerloomError, UnsupportedInput
from convert.queue import JobQueue
from convert.spec import (
    EXTENSION_BY_MIME,
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

READY_NAME = "sticker" + OUTPUT_SUFFIX

Pull = Callable[[Path], Awaitable[None]]


def _named(file_name: str | None, mime: str | None, fallback: str) -> str:
    """Name the file so its extension is one we know, whatever Telegram called it."""
    suffix = Path(file_name or "").suffix.lower()
    if suffix in SUPPORTED_EXTENSIONS or suffix in REJECTED_EXTENSIONS:
        return file_name
    known = EXTENSION_BY_MIME.get(mime or "")
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
            raise UnsupportedInput("error.tgs")
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
    raise UnsupportedInput("error.send_media")


def _validate(name: str, size: int) -> None:
    suffix = Path(name).suffix.lower()
    if suffix in REJECTED_EXTENSIONS:
        raise UnsupportedInput("error.tgs")
    if suffix not in SUPPORTED_EXTENSIONS:
        kinds = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        key = "error.unsupported" if suffix else "error.unsupported_unknown"
        raise UnsupportedInput(key, suffix=suffix, kinds=kinds)
    if size > MAX_SOURCE_BYTES:
        raise UnsupportedInput("error.too_big", mb=MAX_SOURCE_BYTES // (1024 * 1024))


def _caption(result: ConvertResult, emoji: str | None, t: Translator) -> str:
    """The emoji rides along with the file, so a batch of answers stays paired up."""
    # a still is a clip only because Telegram wants one, its length says nothing
    key = "caption.clip" if result.duration > STILL_DURATION else "caption.still"
    body = t(key, width=result.width, height=result.height,
             seconds=f"{result.duration:.1f}", kb=result.size // 1024)
    return f"{emoji} {body}" if emoji else body


async def _in_pack_mode(user_id: int, repo: PackRepo) -> bool:
    return (await repo.session(user_id)).state in states.PACK_MODE


async def _queue_for_pack(message: Message, user_id: int, spot: int, name: str,
                          result: ConvertResult, repo: PackRepo, packs: PackManager,
                          t: Translator) -> None:
    """Fill in the reserved queue slot, then ask about it if it is the one in turn."""
    try:
        file_id = await packs.upload(user_id, result.path)
    except Exception:
        log.exception("could not upload %r for user %s", name, user_id)
        await repo.pop_sticker(spot)
        await message.answer(t("convert.rejected"))
    else:
        await repo.attach(spot, file_id, sha_of(result.path))
        await settle(message, user_id, spot, repo, packs, t)
    await ask_for_emoji(message, user_id, repo, t)


# the only way to spot the same sticker twice: Telegram hands out no content hash
def sha_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


@router.message(MEDIA)
async def handle_media(message: Message, bot: Bot, queue: JobQueue,
                       repo: PackRepo, packs: PackManager, t: Translator) -> None:
    assert message.from_user

    # what Telegram already serves as a video sticker is one, whatever ffprobe makes of it
    if message.sticker and message.sticker.is_video:
        await _take_ready(message, t, repo)
        return

    try:
        source = _source(message)
        _validate(source.name, source.size)
    except StickerloomError as exc:
        await message.answer(t(exc.key, **exc.params))
        return

    async def pull(target: Path) -> None:
        await bot.download(source.file_id, destination=target)

    # an emoji typed on the file itself is an answer, not a suggestion
    answered = "".join(split_emoji(message.caption or ""))
    await _start(message, source.name, source.emoji, pull, queue, repo, packs, t, answered)


async def _take_ready(message: Message, t: Translator, repo: PackRepo) -> None:
    assert message.from_user and message.sticker
    user_id = message.from_user.id
    sticker = message.sticker
    if not await _in_pack_mode(user_id, repo):
        await message.answer_sticker(sticker.file_id, reply_markup=offer_keyboard(t))
        return

    spot = await repo.push_sticker(user_id, sticker.file_id, READY_NAME, sticker.emoji,
                                   message.message_id)
    # a sticker carries no bytes to hash, but Telegram gives every file its own id
    await repo.attach(spot, sticker.file_id, f"tg:{sticker.file_unique_id}")
    await ask_for_emoji(message, user_id, repo, t)


# a link is intake too: the page is read here, the file itself is pulled by the worker
async def handle_link(message: Message, url: str, queue: JobQueue, repo: PackRepo,
                      packs: PackManager, t: Translator) -> None:
    assert message.from_user
    looking = await message.answer(t("link.looking"))
    try:
        target = await resolve(url)
        _validate(target.name, 0)
    except StickerloomError as exc:
        await _edit(looking, t(exc.key, **exc.params))
        return
    except Exception:
        log.exception("could not resolve %r", url)
        await _edit(looking, t("error.link_unreachable"))
        return
    await _delete(looking)

    async def pull(destination: Path) -> None:
        await download(target.url, destination)

    answered = "".join(split_emoji(message.text or ""))
    await _start(message, target.name, None, pull, queue, repo, packs, t, answered)


async def _start(message: Message, name: str, emoji: str | None, pull: Pull, queue: JobQueue,
                 repo: PackRepo, packs: PackManager, t: Translator,
                 answered: str = "") -> None:
    assert message.from_user
    user_id = message.from_user.id
    emoji = answered or emoji

    # every file holds a slot of its own, so an emoji typed next lands on the right one
    spot = await repo.push_sticker(user_id, None, name, emoji, message.message_id)
    if answered:
        await repo.name_sticker(spot, answered)
    into_pack = await _in_pack_mode(user_id, repo)
    status = await message.answer(t("convert.queued", name=name))

    async def fetch(work_dir: Path) -> Path:
        target = work_dir / name
        await pull(target)
        return target

    async def on_status(_: str) -> None:
        await _edit(status, t("convert.converting", name=name))

    async def on_done(result: ConvertResult) -> None:
        await _delete(status)
        if into_pack:
            await _queue_for_pack(message, user_id, spot, name, result, repo, packs, t)
            return
        await _hand_back(message, spot, name, emoji, result, repo, t)

    async def on_cancel() -> None:
        await _delete(status)
        await repo.pop_sticker(spot)

    async def on_error(exc: Exception) -> None:
        await repo.pop_sticker(spot)
        if into_pack:
            await ask_for_emoji(message, user_id, repo, t)
        if isinstance(exc, StickerloomError):
            await _edit(status, t("convert.failed", name=name, reason=t(exc.key, **exc.params)))
            return
        log.exception("unexpected failure converting %r", name)
        await _edit(status, t("convert.crashed", name=name))

    position = await queue.submit(Job(
        key=user_id, name=name, fetch=fetch,
        on_status=on_status, on_done=on_done, on_error=on_error, on_cancel=on_cancel,
    ))
    if position > 1:
        await _edit(status, t("convert.queued_position", name=name, n=position))


# a plain conversion keeps its slot only until the file is handed back
async def _hand_back(message: Message, spot: int, name: str, emoji: str | None,
                     result: ConvertResult, repo: PackRepo, t: Translator) -> None:
    waiting = await repo.sticker(spot)
    chosen = (waiting.emoji if waiting else None) or emoji
    await repo.pop_sticker(spot)
    document = FSInputFile(result.path, filename=Path(name).stem + OUTPUT_SUFFIX)
    await message.answer_document(document, caption=_caption(result, chosen, t),
                                  reply_markup=offer_keyboard(t))


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

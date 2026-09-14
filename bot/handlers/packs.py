import asyncio
import logging
import re
import shutil

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import (CallbackQuery, FSInputFile, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)
from aiogram.utils.formatting import Bold, Text, TextLink, as_list

from bot.handlers.convert import handle_link, sha_of
from bot.handlers.session import (ADD_ANYWAY, SKIP_DUPLICATE, USE_SUGGESTED,
                                  accept_emoji, ask_for_emoji, resolve_duplicate)
from convert.download import first_url
from convert.queue import JobQueue
from convert.spec import MAX_SOURCE_BYTES
from db.packs import PackRepo
from i18n import Translator
from packs import PackError, PackManager
from packs.manager import STICKER_FORMAT
from packs.archive import BadBackup
from packs.archive import read as read_backup
from packs.archive import work_dir as backup_dir
from packs.emoji import is_emoji, split_emoji
from packs.names import build_name, check_base, tag_for

log = logging.getLogger(__name__)

router = Router()

KEEP_TITLE = "title:keep"
MAX_PICKERS = 50
PICKERS_PER_ROW = 5
# a long pack takes a while to pull down, so the status only moves every so many stickers
PROGRESS_EVERY = 10

# the sticker shown while its menu is open, so it can be taken away again
_PREVIEWS: dict[int, int] = {}

# a link can arrive as a t.me url, a tg:// one, or just the name, with text around it
_LINK = re.compile(r"(?:addstickers/|addstickers\?set=)([A-Za-z0-9_]{1,64})", re.IGNORECASE)
_BARE = re.compile(r"[A-Za-z0-9_]{1,64}")


def linked(text: str, label: str, url: str) -> Text:
    """Put the link where the translation left {label}."""
    before, _, after = text.partition("{label}")
    return Text(before, TextLink(label, url=url), after)


def set_name_from(raw: str) -> str:
    """Pull the set name out of whatever the user pasted, or hand the text back as it came."""
    found = _LINK.search(raw)
    if found:
        return found.group(1)
    bare = raw.strip().lstrip("@").rstrip("/")
    return bare if _BARE.fullmatch(bare) else raw.strip()


async def _ask_for_prefix(message: Message, user_id: int, repo: PackRepo,
                          bot_name: str, t: Translator) -> None:
    await repo.set_asking(user_id, "prefix")
    shape = PackManager.link(build_name("<prefix>", bot_name))
    await message.answer(t("prefix.ask", link=shape),
                         link_preview_options={"is_disabled": True})


async def _usable_prefix(message: Message, user_id: int, base: str, bot_name: str,
                         repo: PackRepo, packs: PackManager, t: Translator) -> bool:
    problem = check_base(base, bot_name)
    if problem:
        key, params = problem
        await message.answer(t(key, **params))
        return False

    name = build_name(base, bot_name)
    known = await repo.find(user_id, name)
    if known is None:
        return True
    if await packs.alive(name, known.title):
        await _say_it_is_yours(message, known, t)
        return False

    await repo.forget(user_id, name)
    return True


async def _say_it_is_yours(message: Message, pack, t: Translator) -> None:
    content = linked(t("pack.yours", label="{label}"), pack.title, PackManager.link(pack.name))
    await message.answer(**content.as_kwargs(), link_preview_options={"is_disabled": True})


async def _build_pack(message: Message, user_id: int, base: str,
                      repo: PackRepo, packs: PackManager, t: Translator) -> None:
    """Turn everything collected since /newpack into a real pack."""
    stickers = await repo.ready_stickers(user_id)
    if not stickers:
        await message.answer(t("pack.nothing_to_finish"))
        return
    title = await repo.peek_pending(user_id) or base
    entries = [(sticker.file_id, sticker.emoji) for sticker in stickers]
    fmt = stickers[0].fmt or STICKER_FORMAT

    try:
        pack, added = await packs.create(user_id, base, title, entries, fmt)
    except PackError as exc:
        await repo.set_asking(user_id, "prefix")
        await message.answer(t(exc.key, **exc.params))
        return
    except Exception:
        log.exception("could not create pack %r for user %s", base, user_id)
        await repo.set_asking(user_id, "prefix")
        await message.answer(t("pack.failed"))
        return

    for sticker in stickers[:added]:
        await repo.remember_sha(pack.name, sticker.sha)

    await repo.clear_stickers(user_id)
    await repo.set_pending(user_id, None)
    await repo.set_asking(user_id, None)
    await repo.set_building(user_id, False)
    await repo.clear_active(user_id)

    link = PackManager.link(pack.name)
    left = len(stickers) - added
    done = t("pack.done_missing", link=link, n=left) if left else t("pack.done", link=link)
    await message.answer(done, link_preview_options={"is_disabled": True})


@router.message(Command("newpack"))
async def cmd_newpack(message: Message, command: CommandObject, bot: Bot,
                      repo: PackRepo, packs: PackManager, t: Translator) -> None:
    assert message.from_user
    user_id = message.from_user.id
    title = (command.args or "").strip()

    await repo.clear_active(user_id)
    await repo.set_pending(user_id, None)
    await repo.set_editing(user_id, None)
    await repo.set_importing(user_id, None)
    await repo.set_deleting(user_id, None)
    await repo.set_editing_pack(user_id, None)
    await drop_preview(message, user_id)
    await repo.clear_stickers(user_id)

    if not title:
        await repo.set_asking(user_id, "title")
        await message.answer(t("pack.ask_name"))
        return

    await _start_collecting(message, user_id, title, repo, t)


async def _start_collecting(message: Message, user_id: int, title: str,
                            repo: PackRepo, t: Translator) -> None:
    await repo.set_pending(user_id, title)
    await repo.set_asking(user_id, None)
    await repo.set_building(user_id, True)
    await message.answer(t("pack.collecting"))
    await ask_for_emoji(message, user_id, repo, t)


@router.message(Command("done"))
async def cmd_done(message: Message, bot: Bot, repo: PackRepo,
                   packs: PackManager, t: Translator) -> None:
    assert message.from_user
    user_id = message.from_user.id
    await repo.set_editing(user_id, None)
    await repo.set_importing(user_id, None)
    await repo.set_deleting(user_id, None)
    await repo.set_editing_pack(user_id, None)
    await drop_preview(message, user_id)
    name = await repo.active_for(user_id)

    if name:
        dropped = await repo.clear_stickers(user_id)
        await repo.clear_active(user_id)
        await repo.set_building(user_id, False)
        link = PackManager.link(name)
        done = (t("pack.done_dropped", link=link, n=dropped) if dropped
                else t("pack.done", link=link))
        await message.answer(done, link_preview_options={"is_disabled": True})
        return

    if not await repo.is_building(user_id):
        await message.answer(t("pack.nothing_to_finish"))
        return

    if not await repo.ready_stickers(user_id):
        await repo.set_building(user_id, False)
        await repo.clear_stickers(user_id)
        await message.answer(t("pack.nothing_to_finish"))
        return

    me = await bot.me()
    await _ask_for_prefix(message, user_id, repo, me.username, t)


@router.callback_query(lambda c: c.data == USE_SUGGESTED)
async def use_suggested(callback: CallbackQuery, repo: PackRepo, packs: PackManager,
                        t: Translator) -> None:
    assert callback.from_user
    user_id = callback.from_user.id
    sticker = await repo.head_sticker(user_id)
    if sticker is None:
        await callback.answer(t("sticker.nothing_waiting"))
        return

    emoji = sticker.suggested or await repo.emoji_for(user_id)
    await callback.answer(emoji)
    if isinstance(callback.message, Message):
        await accept_emoji(callback.message, user_id, emoji, repo, packs, t)


@router.callback_query(lambda c: c.data == KEEP_TITLE)
async def keep_title(callback: CallbackQuery, bot: Bot, repo: PackRepo,
                     t: Translator) -> None:
    assert callback.from_user
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    if callback.message.reply_markup:
        await callback.message.edit_reply_markup(reply_markup=None)
    me = await bot.me()
    await _ask_for_prefix(callback.message, callback.from_user.id, repo, me.username, t)


@router.callback_query(lambda c: c.data in (ADD_ANYWAY, SKIP_DUPLICATE))
async def settle_duplicate(callback: CallbackQuery, repo: PackRepo, packs: PackManager,
                           t: Translator) -> None:
    assert callback.data and callback.from_user
    await callback.answer()
    if isinstance(callback.message, Message):
        await resolve_duplicate(callback.message, callback.from_user.id,
                                callback.data == ADD_ANYWAY, repo, packs, t)


ZIP_MIMES = ("application/zip", "application/x-zip-compressed")


def is_backup(message: Message) -> bool:
    doc = message.document
    if doc is None:
        return False
    return ((doc.file_name or "").lower().endswith(".zip")
            or (doc.mime_type or "") in ZIP_MIMES)


# a backup zip goes back in the way it came out: every sticker with its own emoji
@router.message(is_backup)
async def take_backup(message: Message, bot: Bot, repo: PackRepo, packs: PackManager,
                      t: Translator) -> None:
    assert message.from_user and message.document
    user_id = message.from_user.id
    if (message.document.file_size or 0) > MAX_SOURCE_BYTES:
        await message.answer(t("error.too_big", mb=MAX_SOURCE_BYTES // (1024 * 1024)))
        return

    status = await message.answer(t("backup.reading"))
    work = backup_dir()
    try:
        bundle = work / "backup.zip"
        await bot.download(message.document.file_id, destination=bundle)
        restored = read_backup(bundle, work)
    except BadBackup as exc:
        await _retitle(status, t(exc.key, **exc.params))
        shutil.rmtree(work, ignore_errors=True)
        return
    except Exception:
        log.exception("could not read a backup from user %s", user_id)
        await _retitle(status, t("error.backup_broken"))
        shutil.rmtree(work, ignore_errors=True)
        return

    try:
        await _restore(message, status, user_id, restored, repo, packs, t)
    finally:
        shutil.rmtree(work, ignore_errors=True)


async def _restore(message: Message, status: Message, user_id: int, restored,
                   repo: PackRepo, packs: PackManager, t: Translator) -> None:
    into = await repo.active_for(user_id)
    fallback = await repo.emoji_for(user_id)
    total = len(restored.entries)
    taken = 0

    for spot, (path, emoji) in enumerate(restored.entries, start=1):
        emoji = emoji or fallback
        try:
            file_id = await packs.upload(user_id, path, restored.fmt)
            if into:
                await packs.add(user_id, into, file_id, emoji, restored.fmt)
                await repo.remember_sha(into, sha_of(path))
            else:
                slot = await repo.push_sticker(user_id, file_id, path.name, None, None,
                                               restored.fmt)
                await repo.attach(slot, file_id, sha_of(path))
                await repo.name_sticker(slot, emoji)
        except Exception as exc:
            log.warning("could not restore %s for user %s: %s", path.name, user_id, exc)
            continue
        taken += 1
        if spot % PROGRESS_EVERY == 0 and spot < total:
            await _retitle(status, t("backup.unpacking", done=spot, n=total))

    await _drop(status)
    if not taken:
        await message.answer(t("backup.restore_failed"))
        return
    if into:
        await message.answer(t("backup.restored_into", n=taken, link=PackManager.link(into)),
                             link_preview_options={"is_disabled": True})
        return

    await repo.set_pending(user_id, restored.title or None)
    await repo.set_building(user_id, True)
    await message.answer(t("backup.restored", n=taken))
    me = await message.bot.me()
    await _ask_for_prefix(message, user_id, repo, me.username, t)


@router.message(F.text, ~F.text.startswith("/"))
async def plain_text(message: Message, bot: Bot, queue: JobQueue, repo: PackRepo,
                     packs: PackManager, t: Translator) -> None:
    """Plain text answers whatever the bot last asked for: a pack name, a prefix, or an emoji."""
    assert message.from_user and message.text
    user_id = message.from_user.id
    text = message.text.strip()

    asking = await repo.asking_for(user_id)
    if asking == "title":
        if await repo.importing_for(user_id):
            await repo.set_pending(user_id, text)
            me = await bot.me()
            await _ask_for_prefix(message, user_id, repo, me.username, t)
            return
        await _start_collecting(message, user_id, text, repo, t)
        return

    if asking == "source":
        await _take_source(message, user_id, text, repo, packs, t)
        return

    if asking == "prefix":
        me = await bot.me()
        if not await _usable_prefix(message, user_id, text, me.username, repo, packs, t):
            return
        await repo.set_asking(user_id, None)
        if await repo.importing_for(user_id):
            await _copy_pack(message, user_id, text, repo, packs, t)
        else:
            await _build_pack(message, user_id, text, repo, packs, t)
        return

    doomed = await repo.deleting_for(user_id)
    if doomed:
        await _settle_deletion(message, user_id, doomed, text, repo, packs, t)
        return

    editing = await repo.editing_for(user_id)
    if editing:
        if not is_emoji(text):
            await message.answer(t("emoji.only_plain"))
            return
        text = "".join(split_emoji(text))
        try:
            await packs.retag(editing, text)
        except Exception as exc:
            log.warning("could not retag a sticker: %s", exc)
            await message.answer(t("emoji.change_failed"))
            return
        await repo.set_editing(user_id, None)
        await drop_preview(message, user_id)
        await message.answer(t("emoji.changed", emoji=text))
        return

    if link := first_url(text):
        await handle_link(message, link, queue, repo, packs, t)
        return

    if await repo.head_sticker(user_id) is None:
        return

    if not is_emoji(text):
        await message.answer(t("emoji.only"))
        return

    await accept_emoji(message, user_id, "".join(split_emoji(text)), repo, packs, t)


async def _settle_deletion(message: Message, user_id: int, name: str, typed: str,
                           repo: PackRepo, packs: PackManager, t: Translator) -> None:
    pack = await repo.find(user_id, name)
    if pack is None:
        await repo.set_deleting(user_id, None)
        await message.answer(t("delete.gone"))
        return

    if typed.strip().casefold() != pack.title.strip().casefold():
        await message.answer(t("delete.mismatch"))
        return

    try:
        await packs.remove(user_id, name)
    except Exception as exc:
        log.warning("could not delete %s: %s", name, exc)
        await message.answer(t("delete.failed"))
        return

    if name == await repo.active_for(user_id):
        await repo.clear_active(user_id)
    await repo.set_deleting(user_id, None)
    await message.answer(t("delete.done", title=pack.title))


@router.message(Command("mypacks"))
async def cmd_mypacks(message: Message, repo: PackRepo, packs: PackManager,
                      t: Translator) -> None:
    assert message.from_user
    user_id = message.from_user.id
    await repo.set_editing(user_id, None)
    await drop_preview(message, user_id)
    mine = await _surviving(user_id, repo, packs)
    if not mine:
        await message.answer(t("packs.none"))
        return

    content, keyboard = _list_view(mine, t)
    await message.answer(**content.as_kwargs(), reply_markup=keyboard,
                         link_preview_options={"is_disabled": True})


async def _surviving(user_id: int, repo: PackRepo, packs: PackManager) -> list:
    """Pair every pack still on Telegram with its size, forgetting the deleted ones."""
    known = await repo.list_for(user_id)
    sizes = await asyncio.gather(*(packs.size(p.name) for p in known))

    active = await repo.active_for(user_id)
    for pack, size in zip(known, sizes):
        if size is None:
            await repo.forget(user_id, pack.name)
            if pack.name == active:
                await repo.clear_active(user_id)
    return [(pack, size) for pack, size in zip(known, sizes) if size is not None]


def _list_view(mine: list, t: Translator) -> tuple[Text, InlineKeyboardMarkup]:
    if not mine:
        return Text(t("packs.none")), InlineKeyboardMarkup(inline_keyboard=[])

    rows = []
    buttons = []
    for pack, count in mine:
        row = t("packs.row", label="{label}", n=count)
        rows.append(linked(row, pack.title, PackManager.link(pack.name)))
        buttons.append([InlineKeyboardButton(
            text=pack.title, callback_data=f"pack:open:{tag_for(pack.name)}")])
    return (as_list(Bold(t("packs.title")), *rows, sep="\n"),
            InlineKeyboardMarkup(inline_keyboard=buttons))


def _menu_view(pack, count: int, active: bool, t: Translator) -> tuple[Text,
                                                                       InlineKeyboardMarkup]:
    tag = tag_for(pack.name)
    fill = ((t("menu.stop"), f"pack:stop:{tag}") if active
            else (t("menu.add"), f"pack:add:{tag}"))
    buttons = [
        [InlineKeyboardButton(text=fill[0], callback_data=fill[1])],
        [InlineKeyboardButton(text=t("menu.edit"), callback_data=f"edit:list:{tag}:0")],
        [InlineKeyboardButton(text=t("menu.backup"), callback_data=f"pack:save:{tag}")],
        [InlineKeyboardButton(text=t("menu.delete"), callback_data=f"pack:drop:{tag}")],
        [InlineKeyboardButton(text=t("menu.back"), callback_data="pack:back:0")],
    ]
    head = t("menu.adding" if active else "menu.count", label="{label}", n=count)
    return (linked(head, pack.title, PackManager.link(pack.name)),
            InlineKeyboardMarkup(inline_keyboard=buttons))


def _confirm_view(pack, t: Translator) -> tuple[Text, InlineKeyboardMarkup]:
    buttons = [[InlineKeyboardButton(text=t("delete.keep"),
                                     callback_data=f"pack:open:{tag_for(pack.name)}")]]
    warning = t("delete.confirm", label="{label}")
    return (linked(warning, pack.title, PackManager.link(pack.name)),
            InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(lambda c: c.data and c.data.startswith("pack:"))
async def pack_menu(callback: CallbackQuery, repo: PackRepo, packs: PackManager,
                    t: Translator) -> None:
    assert callback.data and callback.from_user
    user_id = callback.from_user.id
    _, action, raw = callback.data.split(":")

    if isinstance(callback.message, Message):
        await drop_preview(callback.message, user_id)

    mine = await _surviving(user_id, repo, packs)
    if action == "back":
        await callback.answer()
        await _render(callback, *_list_view(mine, t))
        return

    chosen = _by_tag(mine, raw)
    if chosen is None:
        await callback.answer(t("packs.gone"))
        await _render(callback, *_list_view(mine, t))
        return
    pack, count = chosen

    if action == "add":
        await repo.set_active(user_id, pack.name)
        await repo.set_building(user_id, False)
    elif action == "stop":
        await repo.clear_active(user_id)
    await callback.answer()
    if action == "save":
        await _send_backup(callback, pack, count, packs, t)
        return

    if action == "drop":
        await repo.set_deleting(user_id, pack.name)
        await _render(callback, *_confirm_view(pack, t))
        return

    await repo.set_deleting(user_id, None)
    await repo.set_editing_pack(user_id, None)

    active = pack.name == await repo.active_for(user_id)
    await _render(callback, *_menu_view(pack, count, active, t))


async def _send_backup(callback: CallbackQuery, pack, count: int, packs: PackManager,
                       t: Translator) -> None:
    if not isinstance(callback.message, Message):
        return
    chat = callback.message
    if not count:
        await chat.answer(t("backup.empty"))
        return

    status = await chat.answer(t("backup.packing", title=pack.title))
    work = backup_dir()

    async def on_progress(done: int, total: int) -> None:
        if done % PROGRESS_EVERY == 0 and done < total:
            await _retitle(status, t("backup.progress", title=pack.title, done=done, n=total))

    try:
        bundle = await packs.backup(pack, work, on_progress)
        await chat.answer_document(FSInputFile(bundle.path),
                                   caption=t("backup.done", title=pack.title, n=bundle.count))
    except Exception:
        log.exception("could not back up %s", pack.name)
        await chat.answer(t("backup.failed"))
    finally:
        shutil.rmtree(work, ignore_errors=True)
        await _drop(status)


async def _retitle(status: Message, text: str) -> None:
    try:
        await status.edit_text(text)
    except TelegramBadRequest:
        log.debug("could not edit the backup status", exc_info=True)


async def _drop(status: Message) -> None:
    try:
        await status.delete()
    except TelegramBadRequest:
        log.debug("could not delete the backup status", exc_info=True)


def _by_tag(mine: list, tag: str):
    return next((row for row in mine if tag_for(row[0].name) == tag), None)


def _sticker_list_view(pack, entries: list, t: Translator) -> tuple[Text,
                                                                    InlineKeyboardMarkup]:
    tag = tag_for(pack.name)
    shown = entries[:MAX_PICKERS]
    rows = [
        [InlineKeyboardButton(text=f"{n + 1} {emoji}", callback_data=f"edit:pick:{tag}:{n}")
         for n, (_, emoji, _unique) in group]
        for group in _chunks(list(enumerate(shown)), PICKERS_PER_ROW)
    ]
    rows.append([InlineKeyboardButton(text=t("menu.back"), callback_data=f"pack:open:{tag}")])
    capped = len(entries) > MAX_PICKERS
    ask = t("editor.pick_capped" if capped else "editor.pick",
            label="{label}", n=MAX_PICKERS)
    return (linked(ask, pack.title, PackManager.link(pack.name)),
            InlineKeyboardMarkup(inline_keyboard=rows))


def _sticker_view(emoji: str, tag: str, spot: int, waiting: bool,
                  t: Translator) -> tuple[Text, InlineKeyboardMarkup]:
    buttons = [
        [InlineKeyboardButton(text=t("editor.change"), callback_data=f"edit:emoji:{tag}:{spot}")],
        [InlineKeyboardButton(text=t("editor.remove"), callback_data=f"edit:drop:{tag}:{spot}")],
        [InlineKeyboardButton(text=t("menu.back"), callback_data=f"edit:list:{tag}:0")],
    ]
    key = "editor.sticker_waiting" if waiting else "editor.sticker"
    return (Text(t(key, n=spot + 1, emoji=emoji)),
            InlineKeyboardMarkup(inline_keyboard=buttons))


async def _show_preview(message: Message, user_id: int, file_id: str) -> None:
    await drop_preview(message, user_id)
    sent = await message.answer_sticker(file_id)
    _PREVIEWS[user_id] = sent.message_id


async def drop_preview(message: Message, user_id: int) -> None:
    """Take the previewed sticker out of the chat once the user leaves it."""
    shown = _PREVIEWS.pop(user_id, None)
    if shown is None:
        return
    try:
        await message.bot.delete_message(message.chat.id, shown)
    except TelegramBadRequest:
        log.debug("preview %s was already gone", shown)


def _chunks(items: list, size: int) -> list:
    return [items[start:start + size] for start in range(0, len(items), size)]


async def editing_a_pack(message: Message, repo: PackRepo) -> bool:
    """False lets the sticker fall through to the converter, as any other file would."""
    assert message.from_user
    name = await repo.editing_pack_for(message.from_user.id)
    return bool(name and message.sticker and message.sticker.set_name == name)


@router.message(F.sticker, editing_a_pack)
async def pick_by_sticker(message: Message, repo: PackRepo, packs: PackManager,
                          t: Translator) -> None:
    assert message.from_user and message.sticker
    user_id = message.from_user.id
    name = await repo.editing_pack_for(user_id)
    pack = await repo.find(user_id, name)
    if pack is None:
        await repo.set_editing_pack(user_id, None)
        await message.answer(t("delete.gone"))
        return

    entries = await packs.stickers(name)
    spot = next((n for n, (_, _emoji, unique) in enumerate(entries)
                 if unique == message.sticker.file_unique_id), None)
    if spot is None:
        await message.answer(t("editor.not_in_pack"))
        return

    content, keyboard = _sticker_view(entries[spot][1], tag_for(name), spot, False, t)
    await message.answer(**content.as_kwargs(), reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith("edit:"))
async def edit_menu(callback: CallbackQuery, repo: PackRepo, packs: PackManager,
                    t: Translator) -> None:
    assert callback.data and callback.from_user
    user_id = callback.from_user.id
    _, action, raw_pack, raw_spot = callback.data.split(":")
    spot = int(raw_spot)

    if isinstance(callback.message, Message):
        await drop_preview(callback.message, user_id)

    mine = await _surviving(user_id, repo, packs)
    chosen = _by_tag(mine, raw_pack)
    if chosen is None:
        await callback.answer(t("packs.gone"))
        await _render(callback, *_list_view(mine, t))
        return

    pack = chosen[0]
    entries = await packs.stickers(pack.name)
    if action != "list" and spot >= len(entries):
        await callback.answer(t("editor.sticker_gone"))
        await _render(callback, *_sticker_list_view(pack, entries, t))
        return

    if action == "list":
        await repo.set_editing_pack(user_id, pack.name)
        await callback.answer()
        await _render(callback, *_sticker_list_view(pack, entries, t))
        return

    file_id, emoji, _unique = entries[spot]

    if action in ("pick", "emoji"):
        if action == "emoji":
            await repo.set_editing(user_id, file_id)
        await callback.answer()
        if isinstance(callback.message, Message):
            await _show_preview(callback.message, user_id, file_id)
        waiting = action == "emoji"
        await _render(callback, *_sticker_view(emoji, tag_for(pack.name), spot, waiting, t))
        return

    try:
        await packs.drop_sticker(file_id)
    except Exception as exc:
        log.warning("could not remove a sticker from %s: %s", pack.name, exc)
        await callback.answer(t("editor.remove_failed"))
        return

    await callback.answer(t("editor.removed"))
    entries = await packs.stickers(pack.name)
    await _render(callback, *_sticker_list_view(pack, entries, t))


async def _render(callback: CallbackQuery, content: Text, keyboard: InlineKeyboardMarkup) -> None:
    if not isinstance(callback.message, Message):
        return
    try:
        await callback.message.edit_text(**content.as_kwargs(), reply_markup=keyboard,
                                         link_preview_options={"is_disabled": True})
    except TelegramBadRequest as exc:
        if "not modified" not in str(exc):
            raise


@router.message(Command("emoji"))
async def cmd_emoji(message: Message, command: CommandObject, repo: PackRepo,
                    t: Translator) -> None:
    assert message.from_user
    raw = (command.args or "").strip()
    if not raw:
        current = await repo.emoji_for(message.from_user.id)
        await message.answer(t("emoji.default", emoji=current, sample="\U0001f631"))
        return

    if not is_emoji(raw):
        await message.answer(t("emoji.only_plain"))
        return

    emoji = "".join(split_emoji(raw))
    await repo.set_emoji(message.from_user.id, emoji)
    await message.answer(t("emoji.set", emoji=emoji))


@router.message(Command("import"))
async def cmd_import(message: Message, command: CommandObject,
                     repo: PackRepo, packs: PackManager, t: Translator) -> None:
    assert message.from_user
    user_id = message.from_user.id
    raw = (command.args or "").strip()

    if not raw:
        await repo.set_asking(user_id, "source")
        await message.answer(t("import.ask"))
        return

    await _take_source(message, user_id, raw, repo, packs, t)


async def _take_source(message: Message, user_id: int, raw: str,
                       repo: PackRepo, packs: PackManager, t: Translator) -> None:
    """Read the pack being copied now, so a bad link fails before anything else is asked."""
    source = set_name_from(raw)
    try:
        found = await packs.look_up(source)
    except PackError as exc:
        await repo.set_asking(user_id, "source")
        await message.answer(t(exc.key, **exc.params))
        return

    count = len(found.stickers or [])
    if not count:
        await repo.set_asking(user_id, "source")
        await message.answer(t("import.empty"))
        return

    await repo.set_importing(user_id, source)
    await repo.set_pending(user_id, found.title)
    await repo.set_asking(user_id, "title")
    keep = InlineKeyboardButton(text=t("import.keep_name"), callback_data=KEEP_TITLE)
    await message.answer(t("import.found", title=found.title, n=count),
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[[keep]]))


async def _copy_pack(message: Message, user_id: int, base: str,
                     repo: PackRepo, packs: PackManager, t: Translator) -> None:
    source = await repo.importing_for(user_id)
    if not source:
        await message.answer(t("import.nothing"))
        return
    title = await repo.peek_pending(user_id) or base
    status = await message.answer(t("import.copying", title=title))

    try:
        pack, copied = await packs.import_set(user_id, source, base, title)
    except PackError as exc:
        await repo.set_asking(user_id, "prefix")
        await status.edit_text(t(exc.key, **exc.params))
        return
    except Exception:
        log.exception("import of %r failed for user %s", source, user_id)
        await repo.set_asking(user_id, "prefix")
        await status.edit_text(t("import.failed"))
        return

    await repo.set_importing(user_id, None)
    await repo.set_pending(user_id, None)
    await repo.set_asking(user_id, None)
    await status.edit_text(t("import.copied", n=copied, link=PackManager.link(pack.name)),
                           link_preview_options={"is_disabled": True})

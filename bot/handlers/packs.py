import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.formatting import Bold, Text, TextLink, as_list

from bot.handlers.session import (ADD_ANYWAY, SKIP_DUPLICATE, USE_SUGGESTED,
                                  accept_emoji, ask_for_emoji, resolve_duplicate)
from db.packs import PackRepo
from packs import PackError, PackManager
from packs.emoji import is_emoji, split_emoji
from packs.names import build_name, check_base, tag_for

log = logging.getLogger(__name__)

router = Router()

KEEP_TITLE = "title:keep"
MAX_PICKERS = 50
PICKERS_PER_ROW = 5

# the sticker shown while its menu is open, so it can be taken away again
_PREVIEWS: dict[int, int] = {}

LINK_PREFIXES = ("https://t.me/addstickers/", "http://t.me/addstickers/", "t.me/addstickers/")


def set_name_from(raw: str) -> str:
    name = raw.strip()
    for prefix in LINK_PREFIXES:
        if name.lower().startswith(prefix):
            name = name[len(prefix):]
            break
    return name.strip().strip("/")


async def _ask_for_prefix(message: Message, user_id: int, repo: PackRepo,
                          bot_name: str) -> None:
    await repo.set_asking(user_id, "prefix")
    shape = PackManager.link(build_name("<prefix>", bot_name))
    await message.answer(f"Pick a prefix for the link.\n{shape}",
                         link_preview_options={"is_disabled": True})


async def _usable_prefix(message: Message, user_id: int, base: str, bot_name: str,
                         repo: PackRepo, packs: PackManager) -> bool:
    problem = check_base(base, bot_name)
    if problem:
        await message.answer(problem)
        return False

    name = build_name(base, bot_name)
    known = await repo.find(user_id, name)
    if known is None:
        return True
    if await packs.alive(name, known.title):
        await _say_it_is_yours(message, known)
        return False

    await repo.forget(user_id, name)
    return True


async def _say_it_is_yours(message: Message, pack) -> None:
    content = Text("That is one of your packs ",
                   TextLink(pack.title, url=PackManager.link(pack.name)),
                   ". /mypacks to add to it.")
    await message.answer(**content.as_kwargs(), link_preview_options={"is_disabled": True})


async def _build_pack(message: Message, user_id: int, base: str,
                      repo: PackRepo, packs: PackManager) -> None:
    """Turn everything collected since /newpack into a real pack."""
    stickers = await repo.ready_stickers(user_id)
    if not stickers:
        await message.answer("Nothing to finish.")
        return
    title = await repo.peek_pending(user_id) or base
    entries = [(sticker.file_id, sticker.emoji) for sticker in stickers]

    try:
        pack, added = await packs.create(user_id, base, title, entries)
    except PackError as exc:
        await repo.set_asking(user_id, "prefix")
        await message.answer(str(exc))
        return
    except Exception:
        log.exception("could not create pack %r for user %s", base, user_id)
        await repo.set_asking(user_id, "prefix")
        await message.answer("Failed. Send another prefix.")
        return

    for sticker in stickers[:added]:
        await repo.remember_sha(pack.name, sticker.sha)

    await repo.clear_stickers(user_id)
    await repo.set_pending(user_id, None)
    await repo.set_asking(user_id, None)
    await repo.set_building(user_id, False)
    await repo.clear_active(user_id)

    missing = f" {len(stickers) - added} left out." if added < len(stickers) else ""
    await message.answer(f"Done. {PackManager.link(pack.name)}{missing}",
                         link_preview_options={"is_disabled": True})


@router.message(Command("newpack"))
async def cmd_newpack(message: Message, command: CommandObject, bot: Bot,
                      repo: PackRepo, packs: PackManager) -> None:
    assert message.from_user
    user_id = message.from_user.id
    title = (command.args or "").strip()

    await repo.clear_active(user_id)
    await repo.set_pending(user_id, None)
    await repo.set_editing(user_id, None)
    await repo.set_importing(user_id, None)
    await drop_preview(message, user_id)
    await repo.clear_stickers(user_id)

    if not title:
        await repo.set_asking(user_id, "title")
        await message.answer("Send a name for the pack.")
        return

    await _start_collecting(message, user_id, title, repo)


async def _start_collecting(message: Message, user_id: int, title: str,
                            repo: PackRepo) -> None:
    await repo.set_pending(user_id, title)
    await repo.set_asking(user_id, None)
    await repo.set_building(user_id, True)
    await message.answer("Send files or stickers. /done to finish.")
    await ask_for_emoji(message, user_id, repo)


@router.message(Command("done"))
async def cmd_done(message: Message, bot: Bot, repo: PackRepo,
                   packs: PackManager) -> None:
    assert message.from_user
    user_id = message.from_user.id
    await repo.set_editing(user_id, None)
    await repo.set_importing(user_id, None)
    await drop_preview(message, user_id)
    name = await repo.active_for(user_id)

    if name:
        dropped = await repo.clear_stickers(user_id)
        await repo.clear_active(user_id)
        await repo.set_building(user_id, False)
        extra = f" {dropped} dropped." if dropped else ""
        await message.answer(f"Done. {PackManager.link(name)}{extra}",
                             link_preview_options={"is_disabled": True})
        return

    if not await repo.is_building(user_id):
        await message.answer("Nothing to finish.")
        return

    if not await repo.ready_stickers(user_id):
        await repo.set_building(user_id, False)
        await repo.clear_stickers(user_id)
        await message.answer("Nothing to finish.")
        return

    me = await bot.me()
    await _ask_for_prefix(message, user_id, repo, me.username)


@router.callback_query(lambda c: c.data == USE_SUGGESTED)
async def use_suggested(callback: CallbackQuery, repo: PackRepo, packs: PackManager) -> None:
    assert callback.from_user
    user_id = callback.from_user.id
    sticker = await repo.head_sticker(user_id)
    if sticker is None:
        await callback.answer("Nothing waiting")
        return

    emoji = sticker.suggested or await repo.emoji_for(user_id)
    await callback.answer(emoji)
    if isinstance(callback.message, Message):
        await accept_emoji(callback.message, user_id, emoji, repo, packs)


@router.callback_query(lambda c: c.data == KEEP_TITLE)
async def keep_title(callback: CallbackQuery, bot: Bot, repo: PackRepo) -> None:
    assert callback.from_user
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    if callback.message.reply_markup:
        await callback.message.edit_reply_markup(reply_markup=None)
    me = await bot.me()
    await _ask_for_prefix(callback.message, callback.from_user.id, repo, me.username)


@router.callback_query(lambda c: c.data in (ADD_ANYWAY, SKIP_DUPLICATE))
async def settle_duplicate(callback: CallbackQuery, repo: PackRepo, packs: PackManager) -> None:
    assert callback.data and callback.from_user
    await callback.answer()
    if isinstance(callback.message, Message):
        await resolve_duplicate(callback.message, callback.from_user.id,
                                callback.data == ADD_ANYWAY, repo, packs)


@router.message(F.text, ~F.text.startswith("/"))
async def plain_text(message: Message, bot: Bot, repo: PackRepo, packs: PackManager) -> None:
    """Plain text answers whatever the bot last asked for: a pack name, a prefix, or an emoji."""
    assert message.from_user and message.text
    user_id = message.from_user.id
    text = message.text.strip()

    asking = await repo.asking_for(user_id)
    if asking == "title":
        if await repo.importing_for(user_id):
            await repo.set_pending(user_id, text)
            me = await bot.me()
            await _ask_for_prefix(message, user_id, repo, me.username)
            return
        await _start_collecting(message, user_id, text, repo)
        return

    if asking == "source":
        await _take_source(message, user_id, text, repo, packs)
        return

    if asking == "prefix":
        me = await bot.me()
        if not await _usable_prefix(message, user_id, text, me.username, repo, packs):
            return
        await repo.set_asking(user_id, None)
        if await repo.importing_for(user_id):
            await _copy_pack(message, user_id, text, repo, packs)
        else:
            await _build_pack(message, user_id, text, repo, packs)
        return

    editing = await repo.editing_for(user_id)
    if editing:
        if not is_emoji(text):
            await message.answer("Emoji only.")
            return
        text = "".join(split_emoji(text))
        try:
            await packs.retag(editing, text)
        except Exception as exc:
            log.warning("could not retag a sticker: %s", exc)
            await message.answer("Could not change it.")
            return
        await repo.set_editing(user_id, None)
        await drop_preview(message, user_id)
        await message.answer(f"Emoji is now {text}.")
        return

    if await repo.head_sticker(user_id) is None:
        return

    if not is_emoji(text):
        await message.answer("Emoji only, or tap the button.")
        return

    await accept_emoji(message, user_id, "".join(split_emoji(text)), repo, packs)


@router.message(Command("mypacks"))
async def cmd_mypacks(message: Message, repo: PackRepo, packs: PackManager) -> None:
    assert message.from_user
    user_id = message.from_user.id
    await repo.set_editing(user_id, None)
    await drop_preview(message, user_id)
    mine = await _surviving(user_id, repo, packs)
    if not mine:
        await message.answer("No packs yet. /newpack")
        return

    content, keyboard = _list_view(mine)
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


def _list_view(mine: list) -> tuple[Text, InlineKeyboardMarkup]:
    if not mine:
        return Text("No packs yet. /newpack"), InlineKeyboardMarkup(inline_keyboard=[])

    rows = []
    buttons = []
    for pack, count in mine:
        rows.append(Text("- ", TextLink(pack.title, url=PackManager.link(pack.name)),
                         f" ({count})"))
        buttons.append([InlineKeyboardButton(
            text=pack.title, callback_data=f"pack:open:{tag_for(pack.name)}")])
    return (as_list(Bold("Your packs"), *rows, sep="\n"),
            InlineKeyboardMarkup(inline_keyboard=buttons))


def _menu_view(pack, count: int, active: bool) -> tuple[Text, InlineKeyboardMarkup]:
    tag = tag_for(pack.name)
    fill = ("Stop adding", f"pack:stop:{tag}") if active else ("Add stickers", f"pack:add:{tag}")
    buttons = [
        [InlineKeyboardButton(text=fill[0], callback_data=fill[1])],
        [InlineKeyboardButton(text="Edit stickers", callback_data=f"edit:list:{tag}:0")],
        [InlineKeyboardButton(text="Delete pack", callback_data=f"pack:drop:{tag}")],
        [InlineKeyboardButton(text="Back", callback_data="pack:back:0")],
    ]
    state = "\nSend files or stickers here. /done when finished." if active else ""
    content = Text(TextLink(pack.title, url=PackManager.link(pack.name)), f" ({count}){state}")
    return content, InlineKeyboardMarkup(inline_keyboard=buttons)


def _confirm_view(pack) -> tuple[Text, InlineKeyboardMarkup]:
    buttons = [[
        InlineKeyboardButton(text="Delete", callback_data=f"pack:kill:{tag_for(pack.name)}"),
        InlineKeyboardButton(text="Keep", callback_data=f"pack:open:{tag_for(pack.name)}"),
    ]]
    return Text("Delete ", pack.title, "?"), InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(lambda c: c.data and c.data.startswith("pack:"))
async def pack_menu(callback: CallbackQuery, repo: PackRepo, packs: PackManager) -> None:
    assert callback.data and callback.from_user
    user_id = callback.from_user.id
    _, action, raw = callback.data.split(":")

    if isinstance(callback.message, Message):
        await drop_preview(callback.message, user_id)

    mine = await _surviving(user_id, repo, packs)
    if action == "back":
        await callback.answer()
        await _render(callback, *_list_view(mine))
        return

    chosen = _by_tag(mine, raw)
    if chosen is None:
        await callback.answer("That pack is gone")
        await _render(callback, *_list_view(mine))
        return
    pack, count = chosen

    if action == "add":
        await repo.set_active(user_id, pack.name)
        await repo.set_building(user_id, False)
    elif action == "stop":
        await repo.clear_active(user_id)
    elif action == "kill":
        try:
            await packs.remove(user_id, pack.name)
        except Exception as exc:
            log.warning("could not delete %s: %s", pack.name, exc)
            await callback.answer("Could not delete it")
            return
        if pack.name == await repo.active_for(user_id):
            await repo.clear_active(user_id)
        await callback.answer("Deleted")
        await _render(callback, *_list_view([row for row in mine if row[0].name != pack.name]))
        return

    await callback.answer()
    if action == "drop":
        await _render(callback, *_confirm_view(pack))
        return

    active = pack.name == await repo.active_for(user_id)
    await _render(callback, *_menu_view(pack, count, active))


def _by_tag(mine: list, tag: str):
    return next((row for row in mine if tag_for(row[0].name) == tag), None)


def _sticker_list_view(pack, entries: list) -> tuple[Text, InlineKeyboardMarkup]:
    tag = tag_for(pack.name)
    shown = entries[:MAX_PICKERS]
    rows = [
        [InlineKeyboardButton(text=f"{n + 1} {emoji}", callback_data=f"edit:pick:{tag}:{n}")
         for n, (_, emoji) in group]
        for group in _chunks(list(enumerate(shown)), PICKERS_PER_ROW)
    ]
    rows.append([InlineKeyboardButton(text="Back", callback_data=f"pack:open:{tag}")])
    tail = f" First {MAX_PICKERS} shown." if len(entries) > MAX_PICKERS else ""
    return (Text("Pick a sticker in ",
                 TextLink(pack.title, url=PackManager.link(pack.name)), ".", tail),
            InlineKeyboardMarkup(inline_keyboard=rows))


def _sticker_view(emoji: str, tag: str, spot: int,
                  waiting: bool = False) -> tuple[Text, InlineKeyboardMarkup]:
    buttons = [
        [InlineKeyboardButton(text="Change emoji", callback_data=f"edit:emoji:{tag}:{spot}")],
        [InlineKeyboardButton(text="Remove", callback_data=f"edit:drop:{tag}:{spot}")],
        [InlineKeyboardButton(text="Back", callback_data=f"edit:list:{tag}:0")],
    ]
    ask = "\nSend a new emoji." if waiting else ""
    return (Text(f"Sticker {spot + 1} - {emoji}{ask}"),
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


@router.callback_query(lambda c: c.data and c.data.startswith("edit:"))
async def edit_menu(callback: CallbackQuery, repo: PackRepo, packs: PackManager) -> None:
    assert callback.data and callback.from_user
    user_id = callback.from_user.id
    _, action, raw_pack, raw_spot = callback.data.split(":")
    spot = int(raw_spot)

    if isinstance(callback.message, Message):
        await drop_preview(callback.message, user_id)

    mine = await _surviving(user_id, repo, packs)
    chosen = _by_tag(mine, raw_pack)
    if chosen is None:
        await callback.answer("That pack is gone")
        await _render(callback, *_list_view(mine))
        return

    pack = chosen[0]
    entries = await packs.stickers(pack.name)
    if action != "list" and spot >= len(entries):
        await callback.answer("That sticker is gone")
        await _render(callback, *_sticker_list_view(pack, entries))
        return

    if action == "list":
        await callback.answer()
        await _render(callback, *_sticker_list_view(pack, entries))
        return

    file_id, emoji = entries[spot]

    if action in ("pick", "emoji"):
        if action == "emoji":
            await repo.set_editing(user_id, file_id)
        await callback.answer()
        if isinstance(callback.message, Message):
            await _show_preview(callback.message, user_id, file_id)
        waiting = action == "emoji"
        await _render(callback, *_sticker_view(emoji, tag_for(pack.name), spot, waiting))
        return

    try:
        await packs.drop_sticker(file_id)
    except Exception as exc:
        log.warning("could not remove a sticker from %s: %s", pack.name, exc)
        await callback.answer("Could not remove it")
        return

    await callback.answer("Removed")
    entries = await packs.stickers(pack.name)
    await _render(callback, *_sticker_list_view(pack, entries))


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
async def cmd_emoji(message: Message, command: CommandObject, repo: PackRepo) -> None:
    assert message.from_user
    raw = (command.args or "").strip()
    if not raw:
        current = await repo.emoji_for(message.from_user.id)
        await message.answer(f"Default emoji: {current}. Send /emoji 😱 to change.")
        return

    if not is_emoji(raw):
        await message.answer("Emoji only.")
        return

    emoji = "".join(split_emoji(raw))
    await repo.set_emoji(message.from_user.id, emoji)
    await message.answer(f"Default emoji: {emoji}")


@router.message(Command("import"))
async def cmd_import(message: Message, command: CommandObject,
                     repo: PackRepo, packs: PackManager) -> None:
    assert message.from_user
    user_id = message.from_user.id
    raw = (command.args or "").strip()

    if not raw:
        await repo.set_asking(user_id, "source")
        await message.answer("Send the link of the pack to copy.")
        return

    await _take_source(message, user_id, raw, repo, packs)


async def _take_source(message: Message, user_id: int, raw: str,
                       repo: PackRepo, packs: PackManager) -> None:
    """Read the pack being copied now, so a bad link fails before anything else is asked."""
    source = set_name_from(raw)
    try:
        found = await packs.look_up(source)
    except PackError as exc:
        await repo.set_asking(user_id, "source")
        await message.answer(str(exc))
        return

    count = len(found.stickers or [])
    if not count:
        await repo.set_asking(user_id, "source")
        await message.answer("That pack is empty.")
        return

    await repo.set_importing(user_id, source)
    await repo.set_pending(user_id, found.title)
    await repo.set_asking(user_id, "title")
    keep = InlineKeyboardButton(text="Keep previous name", callback_data=KEEP_TITLE)
    await message.answer(f"{found.title}, {count} stickers. Send a name for the pack.",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[[keep]]))


async def _copy_pack(message: Message, user_id: int, base: str,
                     repo: PackRepo, packs: PackManager) -> None:
    source = await repo.importing_for(user_id)
    if not source:
        await message.answer("Nothing to copy. /import")
        return
    title = await repo.peek_pending(user_id) or base
    status = await message.answer(f"Copying {title}...")

    try:
        pack, copied = await packs.import_set(user_id, source, base, title)
    except PackError as exc:
        await repo.set_asking(user_id, "prefix")
        await status.edit_text(str(exc))
        return
    except Exception:
        log.exception("import of %r failed for user %s", source, user_id)
        await repo.set_asking(user_id, "prefix")
        await status.edit_text("Failed. Send another prefix.")
        return

    await repo.set_importing(user_id, None)
    await repo.set_pending(user_id, None)
    await repo.set_asking(user_id, None)
    await status.edit_text(f"Copied {copied}. {PackManager.link(pack.name)}",
                           link_preview_options={"is_disabled": True})

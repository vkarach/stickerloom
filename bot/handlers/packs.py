import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.formatting import Bold, Code, Text, as_list

from db.packs import PackRepo
from packs import PackError, PackManager
from packs.emoji import is_emoji

log = logging.getLogger(__name__)

router = Router()

LINK_PREFIXES = ("https://t.me/addstickers/", "http://t.me/addstickers/", "t.me/addstickers/")


def set_name_from(raw: str) -> str:
    name = raw.strip()
    for prefix in LINK_PREFIXES:
        if name.lower().startswith(prefix):
            name = name[len(prefix):]
            break
    return name.strip().strip("/")


def _keyboard(packs, active: str | None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=("* " if pack.name == active else "") + pack.title,
            callback_data=f"pack:{index}",
        )]
        for index, pack in enumerate(packs)
    ]
    rows.append([InlineKeyboardButton(text="Stop adding to a pack", callback_data="pack:off")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("newpack"))
async def cmd_newpack(message: Message, command: CommandObject, repo: PackRepo) -> None:
    assert message.from_user
    title = (command.args or "").strip()
    if not title:
        content = Text("Give the pack a title, for example ", Code("/newpack Tiktok comments"))
        await message.answer(**content.as_kwargs())
        return

    await repo.set_pending(message.from_user.id, title)
    content = Text(
        "Next file you send becomes the first sticker of ", Bold(title), ".\n",
        "Telegram cannot make an empty pack, so it is created together with that file.",
    )
    await message.answer(**content.as_kwargs())


@router.message(Command("nopack"))
async def cmd_nopack(message: Message, repo: PackRepo) -> None:
    assert message.from_user
    await repo.clear_active(message.from_user.id)
    await message.answer("Stopped. Files come back converted and go nowhere else.")


@router.message(Command("mypacks"))
async def cmd_mypacks(message: Message, repo: PackRepo) -> None:
    assert message.from_user
    user_id = message.from_user.id
    packs = await repo.list_for(user_id)
    if not packs:
        await message.answer("No packs yet. /newpack <title> starts one.")
        return

    active = await repo.active_for(user_id)
    rows = [Text(p.title, " - ", PackManager.link(p.name)) for p in packs]
    content = as_list(Bold("Your packs"), *rows, sep="\n")
    await message.answer(**content.as_kwargs(), reply_markup=_keyboard(packs, active),
                         link_preview_options={"is_disabled": True})


@router.callback_query(lambda c: c.data and c.data.startswith("pack:"))
async def switch_pack(callback: CallbackQuery, repo: PackRepo) -> None:
    assert callback.data and callback.from_user
    user_id = callback.from_user.id
    choice = callback.data.split(":", 1)[1]

    if choice == "off":
        await repo.clear_active(user_id)
        await callback.answer("Stopped adding to a pack")
    else:
        packs = await repo.list_for(user_id)
        index = int(choice)
        if index >= len(packs):
            await callback.answer("That pack is gone")
            return
        await repo.set_active(user_id, packs[index].name)
        await callback.answer(f"Now filling {packs[index].title}")

    if isinstance(callback.message, Message):
        packs = await repo.list_for(user_id)
        active = await repo.active_for(user_id)
        await callback.message.edit_reply_markup(reply_markup=_keyboard(packs, active))


@router.message(Command("emoji"))
async def cmd_emoji(message: Message, command: CommandObject, repo: PackRepo) -> None:
    assert message.from_user
    raw = (command.args or "").strip()
    if not raw:
        current = await repo.emoji_for(message.from_user.id)
        await message.answer(f"Files without an emoji of their own get {current}. "
                             f"Change it with /emoji and one emoji.")
        return

    if not is_emoji(raw):
        await message.answer("That is not an emoji. Send just the emoji, nothing else.")
        return

    await repo.set_emoji(message.from_user.id, raw)
    await message.answer(f"Files without an emoji of their own will get {raw}.")


@router.message(Command("import"))
async def cmd_import(message: Message, command: CommandObject,
                     repo: PackRepo, packs: PackManager) -> None:
    assert message.from_user
    raw = (command.args or "").strip()
    if not raw:
        content = Text("Send the pack link, for example ",
                       Code("/import https://t.me/addstickers/mypack"))
        await message.answer(**content.as_kwargs())
        return

    source = set_name_from(raw)
    status = await message.answer(f"Copying {source}...")
    try:
        pack = await packs.import_set(message.from_user.id, source, source)
    except PackError as exc:
        await status.edit_text(str(exc))
        return
    except Exception:
        log.exception("import of %r failed", source)
        await status.edit_text("Could not copy that pack.")
        return

    await status.edit_text(
        f"Copied into your own pack: {PackManager.link(pack.name)}\n"
        "It is active now, so every converted file goes into it."
    )

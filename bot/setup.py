from aiogram import Bot
from aiogram.types import BotCommandScopeAllPrivateChats, BotCommandScopeChat

from bot.commands import menu
from i18n import DEFAULT_LANG, Translator, languages


async def setup_commands(bot: Bot, t: Translator | None = None, user_id: int | None = None) -> None:
    """One menu per language, plus a private one when a user picks a language himself."""
    if user_id is not None and t is not None:
        await bot.set_my_commands(menu(t), scope=BotCommandScopeChat(chat_id=user_id))
        return

    for lang in languages():
        spoken = Translator(lang)
        await bot.set_my_commands(
            menu(spoken), scope=BotCommandScopeAllPrivateChats(),
            language_code=None if lang == DEFAULT_LANG else lang,
        )

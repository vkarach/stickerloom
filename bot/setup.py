from aiogram import Bot
from aiogram.types import BotCommandScopeAllPrivateChats

from bot.commands import menu


async def setup_commands(bot: Bot) -> None:
    await bot.set_my_commands(menu(), scope=BotCommandScopeAllPrivateChats())

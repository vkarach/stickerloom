import asyncio
import logging
import os
import shutil

from aiogram import Bot, Dispatcher
from dotenv import load_dotenv

from bot.handlers import router
from bot.setup import setup_commands
from convert.queue import JobQueue
from logging_config import setup_logging

log = logging.getLogger(__name__)

WORKERS = 2
REQUIRED_BINARIES = ("ffmpeg", "ffprobe")


def check_binaries() -> None:
    missing = [name for name in REQUIRED_BINARIES if shutil.which(name) is None]
    if missing:
        raise RuntimeError(f"{', '.join(missing)} not found on PATH, the bot cannot convert anything")


async def main() -> None:
    setup_logging()
    load_dotenv()
    check_binaries()

    queue = JobQueue(workers=WORKERS)

    async def on_startup(bot: Bot) -> None:
        await setup_commands(bot)
        await queue.start()

    async def on_shutdown() -> None:
        await queue.stop()
        log.info("shut down")

    bot = Bot(token=os.environ["BOT_TOKEN"])
    dp = Dispatcher()
    dp.include_router(router)
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    await dp.start_polling(bot, queue=queue)


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import logging
import os
import shutil

from aiogram import Bot, Dispatcher
from dotenv import load_dotenv

from bot.admin import admin_ids
from bot.handlers import router
from bot.middlewares import AdminMiddleware
from bot.setup import setup_commands
from convert.queue import JobQueue, sweep_leftovers
from db import PackRepo, connect
from i18n import Translator
from i18n import load as load_locales
from logging_config import setup_logging
from packs import PackManager

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
    load_locales()

    admins = admin_ids()
    log.info("%d admin(s) configured", len(admins))

    queue = JobQueue(workers=WORKERS)
    conn = await connect()
    repo = PackRepo(conn)

    async def on_startup(bot: Bot) -> None:
        left = sweep_leftovers()
        if left:
            log.info("swept %d leftover work directories", left)
        await setup_commands(bot)
        for admin in admins:
            await setup_commands(bot, Translator(await repo.lang_for(admin)), admin, admin=True)
        await queue.start()

    async def on_shutdown() -> None:
        await queue.stop()
        await conn.close()
        log.info("shut down")

    bot = Bot(token=os.environ["BOT_TOKEN"])
    dp = Dispatcher()
    dp.update.outer_middleware(AdminMiddleware(admins))
    dp.include_router(router)
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    await dp.start_polling(bot, queue=queue, repo=repo, packs=PackManager(bot, repo))


if __name__ == "__main__":
    asyncio.run(main())

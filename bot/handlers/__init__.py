from aiogram import Router

from bot.middlewares import QueueGuardMiddleware

from .common import router as common_router
from .convert import router as convert_router
from .inline import router as inline_router

router = Router()
router.include_router(common_router)
router.include_router(inline_router)

convert_router.message.middleware(QueueGuardMiddleware())
router.include_router(convert_router)

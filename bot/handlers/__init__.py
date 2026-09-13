from aiogram import Router

from bot.middlewares import QueueGuardMiddleware

from .common import router as common_router
from .convert import router as convert_router
from .offer import router as offer_router
from .packs import router as packs_router

router = Router()
router.include_router(common_router)
router.include_router(packs_router)
router.include_router(offer_router)

convert_router.message.middleware(QueueGuardMiddleware())
router.include_router(convert_router)

import logging

from aiogram import BaseMiddleware

from i18n import Translator

log = logging.getLogger(__name__)


class LanguageMiddleware(BaseMiddleware):
    """Hands every handler a translator: the user's choice, else what Telegram reports."""

    async def __call__(self, handler, event, data):
        repo = data.get("repo")
        user = data.get("event_from_user")
        chosen = None
        if repo is not None and user is not None:
            chosen = await repo.lang_for(user.id)
        data["t"] = Translator(chosen or (user.language_code if user else None))
        return await handler(event, data)

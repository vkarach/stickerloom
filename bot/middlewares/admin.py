from aiogram import BaseMiddleware


class AdminMiddleware(BaseMiddleware):
    def __init__(self, ids) -> None:
        self._ids = frozenset(ids)

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        data["is_admin"] = user is not None and user.id in self._ids
        return await handler(event, data)

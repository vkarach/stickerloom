import logging

from aiogram import BaseMiddleware
from aiogram.types import Message

log = logging.getLogger(__name__)

MAX_PENDING_PER_USER = 30


class QueueGuardMiddleware(BaseMiddleware):
    """Keeps one user from filling the queue for everyone else."""

    async def __call__(self, handler, event: Message, data):
        queue = data.get("queue")
        user = data.get("event_from_user")
        if queue is None or user is None:
            return await handler(event, data)

        if queue.pending_for(user.id) >= MAX_PENDING_PER_USER:
            log.info("user %s hit the queue cap", user.id)
            await event.answer(
                f"You already have {MAX_PENDING_PER_USER} files waiting. "
                "Let them finish, or /cancel to drop them."
            )
            return None
        return await handler(event, data)

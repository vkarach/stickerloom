import logging

from aiogram import Router
from aiogram.types import (
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultCachedDocument,
    InputTextMessageContent,
)

from bot.recent import Delivered, recent

log = logging.getLogger(__name__)

router = Router()

CACHE_SECONDS = 5


def _results(items: list[Delivered]) -> list:
    results = []
    for index, item in enumerate(items):
        results.append(InlineQueryResultCachedDocument(
            id=f"f{index}",
            title=item.name,
            document_file_id=item.file_id,
            description="send this file",
        ))
        if item.emoji:
            results.append(InlineQueryResultArticle(
                id=f"e{index}",
                title=item.emoji,
                description=f"send the emoji for {item.name}",
                input_message_content=InputTextMessageContent(message_text=item.emoji),
            ))
    return results


@router.inline_query()
async def serve_recent(query: InlineQuery) -> None:
    token = query.query.strip()
    user_id = query.from_user.id

    if token:
        item = recent.get(token, user_id)
        items = [item] if item else []
    else:
        items = recent.latest_for(user_id)

    if not items:
        await query.answer(
            [], cache_time=CACHE_SECONDS, is_personal=True,
            button={"text": "Convert a file first", "start_parameter": "start"},
        )
        return

    await query.answer(_results(items), cache_time=CACHE_SECONDS, is_personal=True)

from aiogram.types import InlineQueryResultArticle, InlineQueryResultCachedDocument

from bot.handlers.inline import _results
from bot.recent import Delivered, RecentFiles


def item(user_id=1, file_id="fid", name="sticker.webm", emoji=None):
    return Delivered(user_id=user_id, file_id=file_id, name=name, emoji=emoji)


def test_a_stored_file_comes_back_by_token():
    store = RecentFiles()
    token = store.reserve()
    store.store(token, item())
    assert store.get(token, 1).file_id == "fid"


def test_tokens_are_unique():
    store = RecentFiles()
    assert len({store.reserve() for _ in range(100)}) == 100


def test_another_user_cannot_read_your_token():
    store = RecentFiles()
    token = store.reserve()
    store.store(token, item(user_id=1))
    assert store.get(token, 2) is None


def test_unknown_token_is_not_found():
    assert RecentFiles().get("nope", 1) is None


def test_the_oldest_entries_are_dropped():
    store = RecentFiles(limit=3)
    tokens = []
    for index in range(5):
        token = store.reserve()
        store.store(token, item(file_id=f"f{index}"))
        tokens.append(token)
    assert store.get(tokens[0], 1) is None
    assert store.get(tokens[-1], 1).file_id == "f4"


def test_latest_lists_newest_first_and_only_that_user():
    store = RecentFiles()
    for index in range(3):
        store.store(store.reserve(), item(file_id=f"mine{index}"))
    store.store(store.reserve(), item(user_id=2, file_id="theirs"))

    found = store.latest_for(1)
    assert [d.file_id for d in found] == ["mine2", "mine1", "mine0"]


def test_results_carry_the_document():
    results = _results([item(file_id="abc")])
    assert isinstance(results[0], InlineQueryResultCachedDocument)
    assert results[0].document_file_id == "abc"


def test_results_add_the_emoji_when_known():
    results = _results([item(emoji="\U0001f631")])
    assert len(results) == 2
    assert isinstance(results[1], InlineQueryResultArticle)
    assert results[1].input_message_content.message_text == "\U0001f631"


def test_results_skip_the_emoji_when_unknown():
    assert len(_results([item()])) == 1


def test_result_ids_stay_unique_across_items():
    results = _results([item(emoji="\U0001f525"), item(emoji="\U0001f600")])
    assert len({r.id for r in results}) == len(results)

from datetime import datetime

import pytest
from aiogram.types import Chat, Document, Message, PhotoSize, Sticker

from bot.handlers.convert import _caption, _source, _validate
from convert.errors import UnsupportedInput
from convert.spec import MAX_SOURCE_BYTES
from models import ConvertResult


@pytest.mark.parametrize("name", ["a.png", "A.PNG", "clip.mp4", "sticker.webp", "loop.gif"])
def test_supported_files_pass(name):
    _validate(name, 1024)


@pytest.mark.parametrize("name", ["notes.pdf", "song.mp3", "archive.zip", "noextension"])
def test_unsupported_files_are_rejected(name):
    with pytest.raises(UnsupportedInput):
        _validate(name, 1024)


def test_tgs_gets_its_own_explanation():
    with pytest.raises(UnsupportedInput, match="already work"):
        _validate("pack.tgs", 1024)


def test_oversized_source_is_rejected_before_download():
    with pytest.raises(UnsupportedInput, match="Too big"):
        _validate("big.mp4", MAX_SOURCE_BYTES + 1)


def test_source_at_the_limit_is_allowed():
    _validate("big.mp4", MAX_SOURCE_BYTES)


def test_caption_reports_the_real_result(tmp_path):
    result = ConvertResult(path=tmp_path / "x.webm", width=512, height=374,
                           duration=1.0, size=41 * 1024, attempts=1)
    assert _caption(result) == "512x374 - 1.0s - 41 KB"


def _message(**payload):
    return Message(message_id=1, date=datetime(2026, 1, 1),
                   chat=Chat(id=1, type="private"), **payload)


def _sticker(emoji=None, is_video=False, is_animated=False):
    return Sticker(file_id="fid", file_unique_id="uid", type="regular",
                   width=512, height=512, is_animated=is_animated,
                   is_video=is_video, emoji=emoji, file_size=1024)


def test_sticker_emoji_is_carried_through():
    source = _source(_message(sticker=_sticker(emoji="\U0001f631")))
    assert source.emoji == "\U0001f631"
    assert source.name == "sticker.webp"


def test_video_sticker_keeps_its_emoji_and_extension():
    source = _source(_message(sticker=_sticker(emoji="\U0001f525", is_video=True)))
    assert source.emoji == "\U0001f525"
    assert source.name == "sticker.webm"


def test_whatever_string_telegram_sends_is_passed_along():
    many = "\U0001f631\U0001f628\U0001f630"
    assert _source(_message(sticker=_sticker(emoji=many))).emoji == many


def test_sticker_without_emoji_reports_none():
    assert _source(_message(sticker=_sticker())).emoji is None


def test_photo_has_no_emoji():
    photo = PhotoSize(file_id="fid", file_unique_id="uid", width=512, height=512, file_size=1024)
    assert _source(_message(photo=[photo])).emoji is None


def test_document_has_no_emoji():
    document = Document(file_id="fid", file_unique_id="uid", file_name="a.png", file_size=1024)
    assert _source(_message(document=document)).emoji is None

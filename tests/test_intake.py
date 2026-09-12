import pytest

from bot.handlers.convert import _caption, _validate
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
    with pytest.raises(UnsupportedInput, match="already usable"):
        _validate("pack.tgs", 1024)


def test_oversized_source_is_rejected_before_download():
    with pytest.raises(UnsupportedInput, match="download"):
        _validate("big.mp4", MAX_SOURCE_BYTES + 1)


def test_source_at_the_limit_is_allowed():
    _validate("big.mp4", MAX_SOURCE_BYTES)


def test_caption_reports_the_real_result(tmp_path):
    result = ConvertResult(path=tmp_path / "x.webm", width=512, height=374,
                           duration=1.0, size=41 * 1024, attempts=1)
    assert _caption(result) == "512x374 - 1.0s - 41 KB"

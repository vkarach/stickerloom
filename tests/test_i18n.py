import json

import pytest

from i18n import DEFAULT_LANG, LOCALES_DIR, Translator, known, languages, load

load()


def test_the_default_locale_is_there():
    assert DEFAULT_LANG in languages()


def test_every_locale_carries_the_same_keys():
    expected = set(json.loads((LOCALES_DIR / f"{DEFAULT_LANG}.json").read_text(encoding="utf-8")))
    for lang in languages():
        bundle = json.loads((LOCALES_DIR / f"{lang}.json").read_text(encoding="utf-8"))
        assert set(bundle) == expected


def test_a_missing_key_is_loud():
    with pytest.raises(KeyError):
        Translator()("no.such.key")


def test_a_placeholder_is_filled():
    assert Translator()("pack.done", link="t.me/x") == "Done. t.me/x"


def test_english_picks_the_plural_form():
    english = Translator("en")
    assert english("cancel.dropped", n=1) == "Cancelled. 1 file dropped."
    assert english("cancel.dropped", n=3) == "Cancelled. 3 files dropped."


@pytest.mark.parametrize("tag,expected", [
    ("en", "en"), ("en-GB", "en"), ("EN", "en"), (None, "en"), ("xx", "en"),
])
def test_a_telegram_language_tag_maps_to_what_we_have(tag, expected):
    assert known(tag) == expected

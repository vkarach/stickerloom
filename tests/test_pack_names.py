import re

import pytest

from packs.names import MAX_NAME, pack_name

BOT = "stickerloom_bot"
LEGAL = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


@pytest.mark.parametrize("title", [
    "My Pack", "tiktok comments", "UPPER CASE", "dots.and,commas!",
    "кошки", "123 start", "a", "  spaced  out  ",
    "double__underscore", "_leading", "trailing_",
])
def test_every_name_is_legal_for_telegram(title):
    name = pack_name(title, BOT)
    assert LEGAL.match(name), name
    assert "__" not in name
    assert len(name) <= MAX_NAME


@pytest.mark.parametrize("title", ["My Pack", "кошки", "123"])
def test_the_bot_suffix_is_always_there(title):
    assert pack_name(title, BOT).endswith(f"_by_{BOT}")


def test_the_slug_keeps_the_title_readable():
    assert pack_name("My Pack", BOT).startswith("my_pack_")


def test_a_leading_digit_is_made_legal():
    name = pack_name("123 start", BOT)
    assert name[0].isalpha()


def test_a_title_that_slugs_to_nothing_still_works():
    name = pack_name("❤️!!!", BOT)
    assert LEGAL.match(name), name
    assert name.endswith(f"_by_{BOT}")


def test_names_are_unique_per_call():
    assert len({pack_name("My Pack", BOT) for _ in range(50)}) == 50


def test_a_long_title_is_trimmed_to_fit_the_suffix():
    name = pack_name("x" * 200, BOT)
    assert len(name) <= MAX_NAME
    assert name.endswith(f"_by_{BOT}")


def test_the_suffix_follows_the_running_bot():
    assert pack_name("p", "Stickerloom_dev_bot").endswith("_by_Stickerloom_dev_bot")

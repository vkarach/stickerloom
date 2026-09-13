import pytest

from packs.emoji import is_emoji, split_emoji


@pytest.mark.parametrize("text", [
    "\U0001f631",
    "\U0001f631\U0001f628",
    "\U0001f937\U0000200d\U00002642\U0000fe0f",
    "\U00002764\U0000fe0f",
    "\U0001f44d\U0001f3fb",
    "  \U0001f525  ",
])
def test_real_emoji_are_accepted(text):
    assert is_emoji(text)


@pytest.mark.parametrize("text", ["", "   ", "cat", "123", ":)", "-"])
def test_text_without_an_emoji_is_rejected(text):
    assert not is_emoji(text)


@pytest.mark.parametrize("text", ["a\U0001f631", "\U0001f631 cat", "cat \U0001f631 dog"])
def test_an_emoji_is_picked_out_of_the_words_around_it(text):
    assert is_emoji(text)


def test_a_wall_of_emoji_is_rejected():
    wall = "".join(chr(code) for code in range(0x1F600, 0x1F600 + 25))
    assert not is_emoji(wall)


def test_repeats_collapse_the_way_telegram_stores_them():
    assert split_emoji("\U0001f642\U0001f642\U0001f642") == ["\U0001f642"]


def test_a_joined_sequence_stays_one_emoji():
    family = "\U0001f468\U0000200d\U0001f469\U0000200d\U0001f466"
    assert split_emoji(f"{family} \U0001f600") == [family, "\U0001f600"]


def test_a_flag_keeps_both_halves():
    assert split_emoji("\U0001f1fa\U0001f1e6 \U0001f600") == ["\U0001f1fa\U0001f1e6", "\U0001f600"]

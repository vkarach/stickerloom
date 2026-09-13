import pytest

from packs.emoji import is_emoji


@pytest.mark.parametrize("text", [
    "\U0001f631",
    "\U0001f631\U0001f628",
    "\U0001f937\u200d\u2642\ufe0f",
    "\u2764\ufe0f",
    "\U0001f44d\U0001f3fb",
    "  \U0001f525  ",
])
def test_real_emoji_are_accepted(text):
    assert is_emoji(text)


@pytest.mark.parametrize("text", [
    "", "   ", "cat", "123", "a\U0001f631", ":)", "\U0001f631 cat", "-",
])
def test_anything_else_is_rejected(text):
    assert not is_emoji(text)


def test_a_wall_of_emoji_is_rejected():
    assert not is_emoji("\U0001f631" * 30)

import pytest

from packs.names import MAX_NAME, build_name, check_base, room_for

BOT = "stickerloom_bot"


@pytest.mark.parametrize("base", ["cats", "Cats", "c", "a1_b2", "x" * room_for(BOT)])
def test_a_sane_prefix_is_accepted(base):
    assert check_base(base, BOT) is None


@pytest.mark.parametrize("base", [
    "", "1cats", "_cats", "cats_", "double__underscore", "with space",
    "кошки", "dots.and,commas!", "x" * (room_for(BOT) + 1),
])
def test_a_bad_prefix_is_explained(base):
    assert check_base(base, BOT)


def test_the_suffix_is_what_telegram_demands():
    assert build_name("cats", BOT) == f"cats_by_{BOT}"


def test_the_longest_allowed_prefix_still_fits():
    longest = "x" * room_for(BOT)
    assert len(build_name(longest, BOT)) == MAX_NAME


def test_a_longer_bot_name_leaves_less_room():
    assert room_for("Stickerloom_dev_bot") < room_for(BOT)

import pytest

from bot.handlers.packs import set_name_from


@pytest.mark.parametrize("raw,expected", [
    ("https://t.me/addstickers/mypack", "mypack"),
    ("http://t.me/addstickers/mypack", "mypack"),
    ("t.me/addstickers/mypack", "mypack"),
    ("HTTPS://T.ME/addstickers/MyPack", "MyPack"),
    ("mypack", "mypack"),
    ("  mypack  ", "mypack"),
    ("https://t.me/addstickers/mypack/", "mypack"),
    ("take this: https://t.me/addstickers/mypack please", "mypack"),
    ("tg://addstickers?set=mypack", "mypack"),
    ("@mypack", "mypack"),
])
def test_a_pack_link_yields_its_name(raw, expected):
    assert set_name_from(raw) == expected


def test_an_unrelated_link_is_left_alone():
    assert set_name_from("https://example.com/x") == "https://example.com/x"

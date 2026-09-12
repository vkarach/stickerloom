import pytest

from convert.spec import LONG_SIDE, target_size

CASES = [
    ((512, 512), (512, 512)),
    ((1024, 1024), (512, 512)),
    ((1000, 500), (512, 256)),
    ((500, 1000), (256, 512)),
    ((394, 512), (394, 512)),
    ((512, 374), (512, 374)),
    ((100, 100), (512, 512)),
    ((64, 128), (256, 512)),
]


@pytest.mark.parametrize("source,expected", CASES)
def test_known_sizes(source, expected):
    assert target_size(*source) == expected


@pytest.mark.parametrize("source", [s for s, _ in CASES] + [(1000, 501), (777, 333), (3, 1000)])
def test_long_side_is_exactly_512(source):
    width, height = target_size(*source)
    assert max(width, height) == LONG_SIDE


@pytest.mark.parametrize("source", [(1000, 501), (777, 333), (3, 1000), (1000, 3), (999, 999)])
def test_both_sides_are_even_and_within_range(source):
    width, height = target_size(*source)
    assert width % 2 == 0 and height % 2 == 0
    assert 2 <= width <= LONG_SIDE
    assert 2 <= height <= LONG_SIDE


@pytest.mark.parametrize("source", [(1000, 501), (777, 333), (1920, 1080), (640, 480)])
def test_aspect_ratio_survives_rounding(source):
    width, height = target_size(*source)
    exact = source[0] / source[1]
    assert abs(width / height - exact) / exact < 0.02


def test_extreme_ratio_does_not_collapse_to_zero():
    assert target_size(1000, 3) == (LONG_SIDE, 2)

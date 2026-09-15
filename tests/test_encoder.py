from pathlib import Path

import pytest

from convert.encoder import (BEST_CRF, FPS_LADDER, WORST_CRF, build_args,
                             next_crf, output_duration)
from convert.spec import FPS, MAX_BYTES, MAX_DURATION, STILL_DURATION
from models import MediaInfo

SRC = Path("in.webp")
DST = Path("out.webm")

STILL = MediaInfo(width=512, height=374, duration=0.0, frames=1, is_animated=False)
SHORT = MediaInfo(width=320, height=240, duration=2.0, frames=30, is_animated=True)
LONG = MediaInfo(width=640, height=480, duration=10.0, frames=300, is_animated=True)


def vf(args: list[str]) -> str:
    return args[args.index("-vf") + 1]


def test_still_is_looped_into_a_short_clip():
    args = build_args(SRC, DST, STILL, crf=32, fps=FPS)
    assert "-loop" in args
    assert args[args.index("-t") + 1] == str(STILL_DURATION)


def test_long_source_is_trimmed():
    assert output_duration(LONG) == MAX_DURATION
    args = build_args(SRC, DST, LONG, crf=32, fps=FPS)
    assert args[args.index("-t") + 1] == str(MAX_DURATION)


def test_short_source_keeps_its_own_length():
    assert output_duration(SHORT) == 2.0


def test_filter_chain_scales_without_padding():
    chain = vf(build_args(SRC, DST, STILL, crf=32, fps=FPS))
    assert "pad" not in chain
    assert "scale=512:374" in chain


def test_alpha_is_forced_into_the_filter_chain():
    assert "format=yuva420p" in vf(build_args(SRC, DST, STILL, crf=32, fps=FPS))


def test_audio_is_dropped():
    assert "-an" in build_args(SRC, DST, LONG, crf=32, fps=FPS)


def test_codec_is_vp9():
    args = build_args(SRC, DST, STILL, crf=32, fps=FPS)
    assert args[args.index("-c:v") + 1] == "libvpx-vp9"


@pytest.mark.parametrize("crf,fps", [(32, 30), (48, 24), (63, 15)])
def test_requested_quality_reaches_the_arguments(crf, fps):
    args = build_args(SRC, DST, LONG, crf=crf, fps=fps)
    assert args[args.index("-crf") + 1] == str(crf)
    assert f"fps={fps}" in vf(args)


def test_frame_sequence_input_replaces_the_source():
    pattern = "frames/frame_%05d.png"
    args = build_args(SRC, DST, SHORT, crf=32, fps=FPS, sequence=(pattern, 10.0))
    assert pattern in args
    assert str(SRC) not in args
    assert args[args.index("-framerate") + 1] == "10.0"


def test_the_first_try_spends_the_whole_size_budget():
    assert 0 < BEST_CRF < WORST_CRF


def test_a_miss_is_answered_by_a_step_towards_the_limit():
    assert next_crf(20, MAX_BYTES * 2) == 29
    assert next_crf(20, MAX_BYTES * 4) == 38


def test_a_near_miss_still_moves():
    assert next_crf(20, MAX_BYTES + 1) > 20


def test_crf_never_passes_the_worst_the_encoder_has():
    assert next_crf(62, 10 * 1024 * 1024) == WORST_CRF


def test_the_frame_rate_ladder_only_ever_slows_down():
    assert list(FPS_LADDER) == sorted(FPS_LADDER, reverse=True)
    assert all(0 < fps < FPS for fps in FPS_LADDER)

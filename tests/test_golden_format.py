import json
import subprocess

import pytest

from convert.encoder import encode
from convert.probe import probe
from convert.spec import LONG_SIDE, MAX_BYTES, MAX_DURATION, STILL_DURATION


def _make(path, args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", *args, "-y", str(path)],
                   check=True)
    return path


def _streams(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-print_format", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)["streams"]


async def _convert(tmp_path, source):
    info = await probe(source)
    return await encode(source, tmp_path / "out.webm", info, work_dir=tmp_path)


def assert_golden(result):
    streams = _streams(result.path)
    video = [s for s in streams if s["codec_type"] == "video"]
    assert len(video) == 1, "exactly one video stream"
    assert not [s for s in streams if s["codec_type"] == "audio"], "no audio"
    assert video[0]["codec_name"] == "vp9"
    assert max(result.width, result.height) == LONG_SIDE
    assert result.width % 2 == 0 and result.height % 2 == 0
    assert result.path.stat().st_size <= MAX_BYTES


async def test_square_still_becomes_a_short_clip(tmp_path):
    source = _make(tmp_path / "still.png",
                   ["-f", "lavfi", "-i", "color=c=red:s=400x400:d=1", "-frames:v", "1"])
    result = await _convert(tmp_path, source)
    assert_golden(result)
    assert (result.width, result.height) == (512, 512)
    assert result.duration == STILL_DURATION


async def test_wide_still_is_not_padded_to_a_square(tmp_path):
    source = _make(tmp_path / "wide.png",
                   ["-f", "lavfi", "-i", "color=c=blue:s=1000x500:d=1", "-frames:v", "1"])
    result = await _convert(tmp_path, source)
    assert_golden(result)
    assert (result.width, result.height) == (512, 256)


async def test_tall_still_keeps_its_shape(tmp_path):
    source = _make(tmp_path / "tall.png",
                   ["-f", "lavfi", "-i", "color=c=green:s=300x800:d=1", "-frames:v", "1"])
    result = await _convert(tmp_path, source)
    assert_golden(result)
    assert (result.width, result.height) == (192, 512)


async def test_transparency_survives(tmp_path):
    source = _make(tmp_path / "alpha.png",
                   ["-f", "lavfi", "-i", "color=c=red@0.0:s=400x400:d=1",
                    "-frames:v", "1", "-pix_fmt", "rgba"])
    result = await _convert(tmp_path, source)
    assert_golden(result)
    assert _streams(result.path)[0]["tags"]["alpha_mode"] == "1"


async def test_long_animation_is_trimmed(tmp_path):
    source = _make(tmp_path / "long.mp4",
                   ["-f", "lavfi", "-i", "testsrc=s=640x480:r=30:d=10"])
    result = await _convert(tmp_path, source)
    assert_golden(result)
    assert result.duration == MAX_DURATION


async def test_noisy_animation_is_squeezed_under_the_limit(tmp_path):
    source = _make(tmp_path / "noise.mkv",
                   ["-f", "lavfi", "-i", "nullsrc=s=640x640:r=30:d=3",
                    "-vf", "geq=random(1)*255:128:128", "-c:v", "ffv1"])
    result = await _convert(tmp_path, source)
    assert_golden(result)
    assert result.attempts > 1, "random noise should not fit on the first attempt"


async def test_animated_webp_round_trips(tmp_path):
    source = _make(tmp_path / "anim.webp",
                   ["-f", "lavfi", "-i", "testsrc=s=320x240:r=10:d=2",
                    "-c:v", "libwebp_anim", "-loop", "0"])
    result = await _convert(tmp_path, source)
    assert_golden(result)
    assert (result.width, result.height) == (512, 384)


async def test_source_with_audio_loses_it(tmp_path):
    source = _make(tmp_path / "sound.mp4",
                   ["-f", "lavfi", "-i", "testsrc=s=320x240:r=30:d=2",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                    "-c:v", "libx264", "-c:a", "aac"])
    result = await _convert(tmp_path, source)
    assert_golden(result)


@pytest.mark.parametrize("size,expected", [("100x100", (512, 512)), ("64x128", (256, 512))])
async def test_small_sources_are_scaled_up(tmp_path, size, expected):
    source = _make(tmp_path / "small.png",
                   ["-f", "lavfi", "-i", f"color=c=yellow:s={size}:d=1", "-frames:v", "1"])
    result = await _convert(tmp_path, source)
    assert_golden(result)
    assert (result.width, result.height) == expected

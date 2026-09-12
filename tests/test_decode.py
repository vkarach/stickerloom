import subprocess

import pytest

from convert.decode import expand_frames, inspect_webp
from convert.probe import probe


def _make(path, args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", *args, "-y", str(path)],
                   check=True)
    return path


@pytest.fixture
def still_webp(tmp_path):
    return _make(tmp_path / "still.webp",
                 ["-f", "lavfi", "-i", "color=c=red:s=320x240:d=1", "-frames:v", "1"])


@pytest.fixture
def animated_webp(tmp_path):
    return _make(tmp_path / "anim.webp",
                 ["-f", "lavfi", "-i", "testsrc=s=320x240:r=10:d=2",
                  "-c:v", "libwebp_anim", "-loop", "0"])


def test_still_webp_reports_a_single_frame(still_webp):
    width, height, frames, duration = inspect_webp(still_webp)
    assert (width, height) == (320, 240)
    assert frames == 1
    assert duration == 0.0


def test_animated_webp_reports_real_size_where_ffprobe_reports_nothing(animated_webp):
    width, height, frames, duration = inspect_webp(animated_webp)
    assert (width, height) == (320, 240)
    assert frames == 20
    assert duration == pytest.approx(2.0, abs=0.2)


def test_expansion_writes_every_frame(animated_webp, tmp_path):
    out = tmp_path / "frames"
    pattern, fps = expand_frames(animated_webp, out)
    assert len(list(out.glob("frame_*.png"))) == 20
    assert pattern.endswith("frame_%05d.png")
    assert fps == pytest.approx(10.0, abs=1.0)


@pytest.mark.asyncio
async def test_probe_routes_animated_webp_through_pillow(animated_webp):
    info = await probe(animated_webp)
    assert (info.width, info.height) == (320, 240)
    assert info.is_animated is True
    assert info.needs_frame_expansion is True


@pytest.mark.asyncio
async def test_probe_leaves_still_webp_to_ffprobe(still_webp):
    info = await probe(still_webp)
    assert (info.width, info.height) == (320, 240)
    assert info.is_animated is False
    assert info.needs_frame_expansion is False

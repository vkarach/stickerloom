import asyncio
import logging
import math
from pathlib import Path

from convert.decode import expand_frames, few_colors
from convert.errors import CannotFitSizeLimit, EncodeFailed
from convert.spec import FPS, MAX_BYTES, MAX_DURATION, STILL_DURATION, target_size
from models import ConvertResult, MediaInfo, Window

log = logging.getLogger(__name__)

# measured: vp9 halves the file about every 9 points of crf, enough to aim the next try
BEST_CRF = 20
WORST_CRF = 63
CRF_HALVING = 9.0
CRF_STEP = 2

# crf 63 maxes out the quantizer and one-pass libvpx ignores -b:v, so fps is the last lever
FPS_LADDER: tuple[int, ...] = (20, 15, 10, 8)


# aim at the limit instead of walking down a table one rung at a time
def next_crf(crf: int, size: int) -> int:
    over = max(size / MAX_BYTES, 1.0)
    aimed = crf + round(CRF_HALVING * math.log2(over))
    return min(WORST_CRF, max(crf + CRF_STEP, aimed))


def output_duration(info: MediaInfo, window: Window = Window()) -> float:
    if not info.is_animated:
        return STILL_DURATION
    if info.duration <= 0:
        return MAX_DURATION
    left = (info.duration - window.start) / window.speed
    return min(left, MAX_DURATION)


def build_args(src: Path, dst: Path, info: MediaInfo, crf: int, fps: int,
               sequence: tuple[str, float] | None = None,
               scaler: str = "lanczos", window: Window = Window()) -> list[str]:
    width, height = target_size(info.width, info.height)
    duration = output_duration(info, window)
    # seeking before -i skips the frames instead of decoding and dropping them
    seek = ["-ss", f"{window.start:.3f}"] if window.start > 0 else []

    if sequence is not None:
        pattern, source_fps = sequence
        source = [*seek, "-framerate", str(source_fps), "-i", pattern]
    elif info.is_animated:
        source = [*seek, "-i", str(src)]
    else:
        source = ["-loop", "1", "-framerate", str(fps), "-i", str(src)]

    faster = f"setpts=PTS/{window.speed:.6g}," if window.speed != 1.0 else ""
    # premultiply: white under transparent pixels bleeds into the edge as a client scales
    chain = (f"{faster}scale={width}:{height}:flags={scaler},fps={fps},"
             "format=rgba,premultiply=inplace=1,format=yuva420p")

    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        *source,
        "-t", str(duration),
        "-vf", chain,
        "-c:v", "libvpx-vp9",
        "-pix_fmt", "yuva420p",
        "-crf", str(crf),
        "-b:v", "0",
        "-g", str(fps * 2),
        "-auto-alt-ref", "0",
        "-deadline", "good",
        "-cpu-used", "2",
        "-an",
        "-f", "webm",
        str(dst),
    ]


async def encode(src: Path, dst: Path, info: MediaInfo, work_dir: Path | None = None,
                 window: Window = Window()) -> ConvertResult:
    """Produce the golden format, tightening quality until the result fits the size limit."""
    sequence = None
    if info.needs_frame_expansion:
        frames_dir = (work_dir or dst.parent) / "frames"
        sequence = expand_frames(src, frames_dir)

    scaler = "neighbor" if few_colors(src) else "lanczos"
    smallest = None
    attempt = 0
    crf, fps = BEST_CRF, FPS

    while True:
        attempt += 1
        await _run(build_args(src, dst, info, crf, fps, sequence, scaler, window))
        size = dst.stat().st_size
        smallest = size if smallest is None else min(smallest, size)
        log.debug("%s: attempt %d crf=%d fps=%d -> %d bytes", src.name, attempt, crf, fps, size)

        if size <= MAX_BYTES:
            width, height = target_size(info.width, info.height)
            return ConvertResult(
                path=dst, width=width, height=height,
                duration=output_duration(info, window), size=size, attempts=attempt,
            )

        if crf < WORST_CRF:
            crf = next_crf(crf, size)
        elif fps == FPS_LADDER[-1]:
            break
        elif fps == FPS:
            fps = FPS_LADDER[0]
        else:
            fps = FPS_LADDER[FPS_LADDER.index(fps) + 1]

    raise CannotFitSizeLimit("error.too_heavy", smallest or 0,
                             kb=MAX_BYTES // 1024, best=(smallest or 0) // 1024)


async def _run(args: list[str]) -> None:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        detail = stderr.decode(errors="replace").strip().splitlines()
        log.error("ffmpeg failed: %s", detail[-1] if detail else "no output")
        log.error("ffmpeg call was: %s", " ".join(args))
        raise EncodeFailed("error.encode")

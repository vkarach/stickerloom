import asyncio
import logging
from pathlib import Path

from convert.decode import expand_frames
from convert.errors import CannotFitSizeLimit, EncodeFailed
from convert.spec import FPS, MAX_BYTES, MAX_DURATION, STILL_DURATION, target_size
from models import ConvertResult, MediaInfo

log = logging.getLogger(__name__)

# crf 63 maxes out the quantizer and one-pass libvpx ignores -b:v, so fps is the last lever
LADDER: tuple[tuple[int, int], ...] = (
    (32, 30),
    (40, 30),
    (48, 30),
    (56, 30),
    (63, 30),
    (63, 20),
    (63, 15),
    (63, 10),
    (63, 8),
)


def output_duration(info: MediaInfo) -> float:
    if not info.is_animated:
        return STILL_DURATION
    if info.duration <= 0:
        return MAX_DURATION
    return min(info.duration, MAX_DURATION)


def build_args(src: Path, dst: Path, info: MediaInfo, crf: int, fps: int,
               sequence: tuple[str, float] | None = None) -> list[str]:
    width, height = target_size(info.width, info.height)
    duration = output_duration(info)

    if sequence is not None:
        pattern, source_fps = sequence
        source = ["-framerate", str(source_fps), "-i", pattern]
    elif info.is_animated:
        source = ["-i", str(src)]
    else:
        source = ["-loop", "1", "-framerate", str(fps), "-i", str(src)]

    chain = f"scale={width}:{height}:flags=lanczos,fps={fps},format=yuva420p"

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


async def encode(src: Path, dst: Path, info: MediaInfo, work_dir: Path | None = None) -> ConvertResult:
    """Produce the golden format, tightening quality until the result fits the size limit."""
    sequence = None
    if info.needs_frame_expansion:
        frames_dir = (work_dir or dst.parent) / "frames"
        sequence = expand_frames(src, frames_dir)

    smallest = None
    for attempt, (crf, fps) in enumerate(LADDER, start=1):
        await _run(build_args(src, dst, info, crf, fps, sequence))
        size = dst.stat().st_size
        smallest = size if smallest is None else min(smallest, size)
        log.debug("%s: attempt %d crf=%d fps=%d -> %d bytes", src.name, attempt, crf, fps, size)

        if size <= MAX_BYTES:
            width, height = target_size(info.width, info.height)
            return ConvertResult(
                path=dst, width=width, height=height,
                duration=output_duration(info), size=size, attempts=attempt,
            )

    raise CannotFitSizeLimit(
        f"Will not fit {MAX_BYTES // 1024} KB, best was {(smallest or 0) // 1024} KB. "
        "Try something shorter.",
        smallest or 0,
    )


async def _run(args: list[str]) -> None:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        detail = stderr.decode(errors="replace").strip().splitlines()
        log.error("ffmpeg failed: %s", detail[-1] if detail else "no output")
        raise EncodeFailed("Could not convert that file.")

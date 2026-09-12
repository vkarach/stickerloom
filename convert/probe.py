import asyncio
import json
import logging
from pathlib import Path

from convert.errors import ProbeFailed
from models import MediaInfo

log = logging.getLogger(__name__)

FFPROBE_ARGS = ("-v", "error", "-show_streams", "-show_format", "-print_format", "json")


def _number(raw, default: float = 0.0) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def parse_probe(payload: dict) -> MediaInfo:
    """Turn ffprobe json into MediaInfo, ignoring audio and other side streams."""
    streams = payload.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ProbeFailed("No video or image stream in this file")

    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    frames = int(_number(video.get("nb_frames"), 0))
    duration = _number(video.get("duration")) or _number(payload.get("format", {}).get("duration"))

    # ffmpeg reads animated webp as a 0x0 stream it cannot decode
    needs_expansion = width == 0 and video.get("codec_name") == "webp"

    return MediaInfo(
        width=width,
        height=height,
        duration=duration,
        frames=frames or 1,
        is_animated=frames > 1 or duration > 0,
        needs_frame_expansion=needs_expansion,
    )


async def probe(path: Path) -> MediaInfo:
    process = await asyncio.create_subprocess_exec(
        "ffprobe", *FFPROBE_ARGS, str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        log.warning("ffprobe failed on %s: %s", path.name, stderr.decode(errors="replace").strip())
        raise ProbeFailed("Could not read this file, it looks damaged or is not a media file")

    try:
        info = parse_probe(json.loads(stdout))
    except json.JSONDecodeError as exc:
        raise ProbeFailed("Could not read this file") from exc

    if info.needs_frame_expansion:
        return _inspect_with_pillow(path)
    if info.width <= 0 or info.height <= 0:
        raise ProbeFailed("Could not read the dimensions of this file")
    return info


def _inspect_with_pillow(path: Path) -> MediaInfo:
    from convert.decode import inspect_webp

    width, height, frames, duration = inspect_webp(path)
    return MediaInfo(
        width=width,
        height=height,
        duration=duration,
        frames=frames,
        is_animated=frames > 1,
        needs_frame_expansion=frames > 1,
    )

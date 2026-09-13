import asyncio
import json
import logging
from pathlib import Path

from convert.errors import ProbeFailed
from models import MediaInfo

log = logging.getLogger(__name__)

STILL_CONTAINERS = frozenset({"image2", "jpeg_pipe", "png_pipe", "webp_pipe", "bmp_pipe"})

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
        raise ProbeFailed("Could not read that file.")

    container = payload.get("format", {})
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    frames = int(_number(video.get("nb_frames"), 0))
    duration = _number(video.get("duration")) or _number(container.get("duration"))

    # ffmpeg reads animated webp as a 0x0 stream it cannot decode
    needs_expansion = width == 0 and video.get("codec_name") == "webp"
    # a jpeg is demuxed as a one frame movie, duration and all, so the container decides
    still = container.get("format_name", "") in STILL_CONTAINERS

    return MediaInfo(
        width=width,
        height=height,
        duration=duration,
        frames=frames or 1,
        is_animated=frames > 1 or (duration > 0 and not still),
        needs_frame_expansion=needs_expansion,
        codec=video.get("codec_name") or "",
        container=container.get("format_name") or "",
        fps=_rate(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        size=int(_number(container.get("size"), 0)),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
    )


def _rate(raw) -> float:
    if not raw or "/" not in str(raw):
        return _number(raw)
    top, _, bottom = str(raw).partition("/")
    divisor = _number(bottom)
    return _number(top) / divisor if divisor else 0.0


async def probe(path: Path) -> MediaInfo:
    process = await asyncio.create_subprocess_exec(
        "ffprobe", *FFPROBE_ARGS, str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        log.warning("ffprobe failed on %s: %s", path.name, stderr.decode(errors="replace").strip())
        raise ProbeFailed("Could not read that file.")

    try:
        info = parse_probe(json.loads(stdout))
    except json.JSONDecodeError as exc:
        raise ProbeFailed("Could not read that file.") from exc

    if info.needs_frame_expansion:
        return _inspect_with_pillow(path)
    if info.width <= 0 or info.height <= 0:
        raise ProbeFailed("Could not read that file.")
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

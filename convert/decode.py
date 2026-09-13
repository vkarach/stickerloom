"""Animated WebP support. ffmpeg cannot decode it, so Pillow reads it instead."""

import logging
from pathlib import Path

from PIL import Image, ImageSequence

from convert.errors import ProbeFailed
from convert.spec import DRAWN_EXTENSIONS, FPS, PIXEL_ART_COLORS

log = logging.getLogger(__name__)

FRAME_PATTERN = "frame_%05d.png"
DEFAULT_FRAME_MS = 100


def inspect_webp(path: Path) -> tuple[int, int, int, float]:
    """Return width, height, frame count and duration in seconds."""
    try:
        with Image.open(path) as image:
            frames = getattr(image, "n_frames", 1)
            duration = _total_duration(image) if frames > 1 else 0.0
            return image.width, image.height, frames, duration
    except OSError as exc:
        raise ProbeFailed("error.unreadable_image") from exc


def expand_frames(path: Path, out_dir: Path) -> tuple[str, float]:
    """Write every frame as a PNG and return the ffmpeg input pattern and its frame rate."""
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(path) as image:
            count = 0
            for index, frame in enumerate(ImageSequence.Iterator(image), start=1):
                frame.convert("RGBA").save(out_dir / (FRAME_PATTERN % index))
                count = index
            duration = _total_duration(image)
    except OSError as exc:
        raise ProbeFailed("error.unreadable_image") from exc

    fps = min(FPS, count / duration) if duration > 0 else FPS
    log.debug("expanded %s into %d frames at %.2f fps", path.name, count, fps)
    return str(out_dir / FRAME_PATTERN), fps


def _total_duration(image: Image.Image) -> float:
    total = 0
    for frame in ImageSequence.Iterator(image):
        total += frame.info.get("duration") or DEFAULT_FRAME_MS
    return total / 1000


def few_colors(path: Path) -> bool:
    """True when the first frame holds so few colors that it can only be drawn art."""
    if path.suffix.lower() not in DRAWN_EXTENSIONS:
        return False
    try:
        with Image.open(path) as image:
            frame = image.convert("RGBA")
    except OSError:
        return False
    return frame.getcolors(maxcolors=PIXEL_ART_COLORS) is not None

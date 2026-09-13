"""The one output format @Stickers accepts as a video sticker."""

LONG_SIDE = 512
MAX_DURATION = 3.0
# a still only has to be a valid clip; shorter keeps the file small
STILL_DURATION = 0.1
FPS = 30
MAX_BYTES = 256 * 1024

# a flat palette means drawn art: scaling it smoothly turns crisp pixels into mush
PIXEL_ART_COLORS = 64
DRAWN_EXTENSIONS = frozenset({".png", ".gif", ".apng", ".webp"})

# getFile refuses anything larger, so a bigger source can never be downloaded
MAX_SOURCE_BYTES = 20 * 1024 * 1024

SUPPORTED_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".apng",
    ".mp4", ".webm", ".mov", ".m4v",
})

# animated Telegram stickers already belong in a pack, converting them buys nothing
REJECTED_EXTENSIONS = frozenset({".tgs"})

OUTPUT_SUFFIX = ".webm"


def _even(value: float) -> int:
    return max(2, min(LONG_SIDE, round(value / 2) * 2))


def conforms(info) -> bool:
    """True when the source already is a valid video sticker and re-encoding would only hurt."""
    if info.codec != "vp9" or "webm" not in info.container and "matroska" not in info.container:
        return False
    if info.has_audio or info.width <= 0 or info.height <= 0:
        return False
    if max(info.width, info.height) != LONG_SIDE:
        return False
    if info.width % 2 or info.height % 2:
        return False
    if info.duration > MAX_DURATION or info.fps > FPS + 0.5:
        return False
    return 0 < info.size <= MAX_BYTES


def target_size(width: int, height: int) -> tuple[int, int]:
    """Fit the source so its long side is exactly 512, keeping the aspect ratio."""
    if width <= 0 or height <= 0:
        raise ValueError(f"bad source size {width}x{height}")
    if width >= height:
        return LONG_SIDE, _even(height * LONG_SIDE / width)
    return _even(width * LONG_SIDE / height), LONG_SIDE

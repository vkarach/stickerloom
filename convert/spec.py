"""The one output format @Stickers accepts as a video sticker."""

LONG_SIDE = 512
MAX_DURATION = 3.0
STILL_DURATION = 1.0
FPS = 30
MAX_BYTES = 256 * 1024

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


def target_size(width: int, height: int) -> tuple[int, int]:
    """Fit the source so its long side is exactly 512, keeping the aspect ratio."""
    if width <= 0 or height <= 0:
        raise ValueError(f"bad source size {width}x{height}")
    if width >= height:
        return LONG_SIDE, _even(height * LONG_SIDE / width)
    return _even(width * LONG_SIDE / height), LONG_SIDE

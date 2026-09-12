from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MediaInfo:
    width: int
    height: int
    duration: float
    frames: int
    is_animated: bool
    # ffmpeg cannot decode animated webp, such a source is expanded to PNG frames first
    needs_frame_expansion: bool = False


@dataclass(frozen=True)
class ConvertResult:
    path: Path
    width: int
    height: int
    duration: float
    size: int
    attempts: int

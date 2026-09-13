from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class Pack:
    user_id: int
    name: str
    title: str
    created_at: str


@dataclass
class Job:
    key: int
    name: str
    fetch: Callable[[Path], Awaitable[Path]]
    on_status: Callable[[str], Awaitable[None]]
    on_done: Callable[[ConvertResult], Awaitable[None]]
    on_error: Callable[[Exception], Awaitable[None]]
    cancelled: bool = field(default=False, compare=False)

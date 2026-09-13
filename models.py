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
    codec: str = ""
    container: str = ""
    fps: float = 0.0
    size: int = 0
    has_audio: bool = False


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


@dataclass(frozen=True)
class QueuedSticker:
    id: int
    user_id: int
    file_id: str
    name: str
    suggested: str | None
    emoji: str | None = None
    source_msg: int | None = None
    prompt_msg: int | None = None
    sha: str | None = None


@dataclass
class Job:
    key: int
    name: str
    fetch: Callable[[Path], Awaitable[Path]]
    on_status: Callable[[str], Awaitable[None]]
    on_done: Callable[[ConvertResult], Awaitable[None]]
    on_error: Callable[[Exception], Awaitable[None]]
    cancelled: bool = field(default=False, compare=False)

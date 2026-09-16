from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple


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


class Window(NamedTuple):
    """Which three seconds of a longer source to keep, and how fast to play them."""
    start: float = 0.0
    speed: float = 1.0


@dataclass(frozen=True)
class ConvertResult:
    path: Path
    width: int
    height: int
    duration: float
    size: int
    attempts: int


@dataclass(frozen=True)
class Session:
    state: str
    # the pack or source set the state is about, and the sticker when one was chosen
    target: str | None = None
    sticker: str | None = None


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
    # only a restored sticker knows it is not a video one
    fmt: str | None = None


@dataclass
class Job:
    key: int
    name: str
    fetch: Callable[[Path], Awaitable[Path]]
    on_status: Callable[[str], Awaitable[None]]
    on_done: Callable[[ConvertResult], Awaitable[None]]
    on_error: Callable[[Exception], Awaitable[None]]
    on_cancel: Callable[[], Awaitable[None]] | None = None
    # a source too long to take whole stops here and waits for the user to pick a window
    on_ask: Callable[[Exception, Path], Awaitable[None]] | None = None
    # set to carry on with files another job left behind, with its own way of encoding
    work_dir: Path | None = None
    process: Callable[[Path, Path], Awaitable[ConvertResult]] | None = None
    cancelled: bool = field(default=False, compare=False)


@dataclass(frozen=True)
class Overview:
    users: int
    packs: int
    owners: int
    stickers: int
    queued: int
    packs_today: int
    packs_week: int
    languages: tuple[tuple[str, int], ...]

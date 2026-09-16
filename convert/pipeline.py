import logging
from pathlib import Path

from convert.encoder import encode
from convert.errors import NeedsWindow
from convert.probe import probe
from convert.spec import MAX_DURATION, OUTPUT_SUFFIX, conforms, mismatch
from models import ConvertResult, Window

log = logging.getLogger(__name__)


async def convert_file(src: Path, work_dir: Path,
                       window: Window | None = None) -> ConvertResult:
    info = await probe(src)

    # only three seconds fit, and which three is not ours to decide quietly
    if window is None and info.is_animated and info.duration > MAX_DURATION:
        raise NeedsWindow(src, info)

    if conforms(info):
        log.info("%s is already a valid video sticker, left untouched", src.name)
        return ConvertResult(path=src, width=info.width, height=info.height,
                             duration=info.duration, size=info.size, attempts=0)

    if info.codec == "vp9":
        log.info("%s is webm already, but %s", src.name, mismatch(info))

    # a webm source would otherwise be handed to ffmpeg as its own output
    dst = work_dir / ("converted" + OUTPUT_SUFFIX)
    result = await encode(src, dst, info, work_dir=work_dir, window=window or Window())
    log.info("converted %s -> %dx%d, %d bytes, %d attempt(s)",
             src.name, result.width, result.height, result.size, result.attempts)
    return result

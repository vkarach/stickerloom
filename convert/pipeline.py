import logging
from pathlib import Path

from convert.encoder import encode
from convert.probe import probe
from convert.spec import OUTPUT_SUFFIX, conforms
from models import ConvertResult

log = logging.getLogger(__name__)


async def convert_file(src: Path, work_dir: Path) -> ConvertResult:
    info = await probe(src)

    if conforms(info):
        log.info("%s is already a valid video sticker, left untouched", src.name)
        return ConvertResult(path=src, width=info.width, height=info.height,
                             duration=info.duration, size=info.size, attempts=0)

    # a webm source would otherwise be handed to ffmpeg as its own output
    dst = work_dir / ("converted" + OUTPUT_SUFFIX)
    result = await encode(src, dst, info, work_dir=work_dir)
    log.info("converted %s -> %dx%d, %d bytes, %d attempt(s)",
             src.name, result.width, result.height, result.size, result.attempts)
    return result

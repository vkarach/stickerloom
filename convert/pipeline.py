import logging
from pathlib import Path

from convert.encoder import encode
from convert.probe import probe
from convert.spec import OUTPUT_SUFFIX
from models import ConvertResult

log = logging.getLogger(__name__)


async def convert_file(src: Path, work_dir: Path) -> ConvertResult:
    info = await probe(src)
    dst = work_dir / (src.stem + OUTPUT_SUFFIX)
    result = await encode(src, dst, info, work_dir=work_dir)
    log.info("converted %s -> %dx%d, %d bytes, %d attempt(s)",
             src.name, result.width, result.height, result.size, result.attempts)
    return result

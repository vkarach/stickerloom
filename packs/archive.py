import json
import logging
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

log = logging.getLogger(__name__)

MANIFEST = "pack.json"
# the file name only has to sort, the emoji it stands for is written down in the manifest
NAME = "{spot:03d}{suffix}"


FORMATS = {".webm": "video", ".tgs": "animated", ".webp": "static"}
MAX_ENTRIES = 200


class Backup(NamedTuple):
    path: Path
    count: int


class Restored(NamedTuple):
    title: str
    fmt: str
    entries: list


class BadBackup(Exception):
    def __init__(self, key: str, **params):
        super().__init__(key)
        self.key = key
        self.params = params


def suffix_of(sticker) -> str:
    if sticker.is_video:
        return ".webm"
    return ".tgs" if sticker.is_animated else ".webp"


def work_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="stickerloom_backup_"))


async def build(bot, pack, dest_dir: Path, on_progress=None) -> Backup:
    found = await bot.get_sticker_set(name=pack.name)
    stickers = found.stickers or []
    saved = []
    for spot, sticker in enumerate(stickers, start=1):
        name = NAME.format(spot=spot, suffix=suffix_of(sticker))
        await bot.download(sticker.file_id, destination=dest_dir / name)
        saved.append({"file": name, "emoji": sticker.emoji or ""})
        if on_progress is not None:
            await on_progress(spot, len(stickers))

    manifest = {
        "name": pack.name,
        "title": found.title,
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stickers": saved,
    }
    (dest_dir / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                     encoding="utf-8")

    archive = dest_dir / f"{pack.name}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as bundle:
        bundle.write(dest_dir / MANIFEST, MANIFEST)
        for entry in saved:
            bundle.write(dest_dir / entry["file"], entry["file"])
    log.info("packed %s stickers of %s into %s", len(saved), pack.name, archive.name)
    return Backup(archive, len(saved))


# a zip is a stranger's file: only the names the manifest lists are ever unpacked
def read(bundle: Path, dest_dir: Path) -> Restored:
    try:
        with zipfile.ZipFile(bundle) as archive:
            manifest = json.loads(archive.read(MANIFEST).decode("utf-8"))
            listed = manifest["stickers"]
            title = str(manifest.get("title") or "")
            entries = []
            for entry in listed[:MAX_ENTRIES]:
                name = _safe(entry["file"])
                target = dest_dir / name
                target.write_bytes(archive.read(name))
                entries.append((target, str(entry.get("emoji") or "")))
    except BadBackup:
        raise
    except (KeyError, ValueError, OSError, zipfile.BadZipFile) as exc:
        log.info("%s is not a backup: %s", bundle.name, exc)
        raise BadBackup("error.backup_broken") from exc

    if not entries:
        raise BadBackup("error.backup_empty")
    kinds = {FORMATS[path.suffix] for path, _ in entries}
    if len(kinds) > 1:
        raise BadBackup("error.backup_mixed")
    return Restored(title, kinds.pop(), entries)


def _safe(name: str) -> str:
    if name != Path(name).name or Path(name).suffix not in FORMATS:
        raise BadBackup("error.backup_broken")
    return name

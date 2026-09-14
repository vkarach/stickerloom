import asyncio
import ipaddress
import logging
import re
from pathlib import Path
from typing import NamedTuple
from urllib.parse import unquote, urljoin, urlparse

import aiohttp

from convert.errors import UnsupportedInput
from convert.spec import EXTENSION_BY_MIME, MAX_SOURCE_BYTES, SUPPORTED_EXTENSIONS

log = logging.getLogger(__name__)

URL = re.compile(r"https?://[^\s<>\"]+")
# a sticker pack link is not a file to convert, /import takes those
PACK_HOSTS = frozenset({"t.me", "telegram.me", "telegram.dog"})

# a bot that names itself and says where to complain gets fewer doors shut
USER_AGENT = "Stickerloom/1.0 (+https://t.me/stickerloom_bot)"
TIMEOUT = aiohttp.ClientTimeout(total=30)
MAX_PAGE_BYTES = 1024 * 1024
MAX_HOPS = 5
CHUNK = 64 * 1024

META = re.compile(r"<meta[^>]+>", re.I)
ANY_URL = re.compile(r"""https?://[^\s"'\\<>]+""")
ID = re.compile(r"[A-Za-z0-9]{8,}")
ATTRIBUTE = re.compile(r"(?:property|name|itemprop)\s*=\s*[\"']([^\"']+)[\"']", re.I)
CONTENT = re.compile(r"content\s*=\s*[\"']([^\"']+)[\"']", re.I)
CARRIES_MEDIA = frozenset({
    "og:video", "og:video:secure_url", "og:video:url",
    "twitter:player:stream", "og:image", "og:image:secure_url",
    "twitter:image", "contenturl",
})
# an animated image keeps transparency, a video never does, a still is the last resort
PREFERENCE = (".gif", ".webp", ".apng", ".png", ".mp4", ".webm", ".mov", ".m4v", ".jpg", ".jpeg")


class Target(NamedTuple):
    url: str
    name: str


class _Answer(NamedTuple):
    url: str
    content_type: str
    page: str | None
    size: int


def first_url(text: str) -> str | None:
    found = URL.search(text)
    return found.group(0).rstrip(".,);]") if found else None


# follow the link to the actual file, reading a page's meta tags when it is one
async def resolve(url: str) -> Target:
    async with aiohttp.ClientSession(headers={"User-Agent": USER_AGENT},
                                     timeout=TIMEOUT) as session:
        answer = await _open(session, url)
        if answer.page is not None:
            media = _media_url(answer.page, answer.url, url)
            if media is None:
                raise UnsupportedInput("error.link_no_media")
            answer = await _open(session, media)
            if answer.page is not None:
                raise UnsupportedInput("error.link_no_media")
        return Target(answer.url, _name(answer.url, answer.content_type))


async def download(url: str, dest: Path) -> None:
    await _guard(url)
    async with aiohttp.ClientSession(headers={"User-Agent": USER_AGENT},
                                     timeout=TIMEOUT) as session:
        async with session.get(url) as answer:
            if answer.status != 200:
                raise UnsupportedInput("error.link_unreachable")
            written = 0
            with dest.open("wb") as handle:
                async for chunk in answer.content.iter_chunked(CHUNK):
                    written += len(chunk)
                    _fits(written)
                    handle.write(chunk)


# redirects are walked by hand so every hop is checked before it is followed
async def _open(session: aiohttp.ClientSession, url: str) -> _Answer:
    for _ in range(MAX_HOPS):
        await _guard(url)
        async with session.get(url, allow_redirects=False) as answer:
            moved = answer.headers.get("location")
            if answer.status in (301, 302, 303, 307, 308) and moved:
                url = urljoin(url, moved)
                continue
            if answer.status != 200:
                log.info("%s answered %s", url, answer.status)
                raise UnsupportedInput("error.link_unreachable")
            kind = (answer.headers.get("content-type") or "").split(";")[0].strip().lower()
            size = int(answer.headers.get("content-length") or 0)
            _fits(size)
            page = None
            if kind in ("text/html", "application/xhtml+xml"):
                page = (await answer.content.read(MAX_PAGE_BYTES)).decode("utf-8", "replace")
            return _Answer(str(answer.url), kind, page, size)
    raise UnsupportedInput("error.link_unreachable")


# a link is a user's input: it may not point back inside our own network
async def _guard(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise UnsupportedInput("error.link_unreachable")
    if parsed.hostname.lower() in PACK_HOSTS:
        raise UnsupportedInput("error.link_pack")
    loop = asyncio.get_running_loop()
    try:
        found = await loop.getaddrinfo(parsed.hostname, None)
    except OSError:
        raise UnsupportedInput("error.link_unreachable")
    for entry in found:
        if not ipaddress.ip_address(entry[4][0]).is_global:
            raise UnsupportedInput("error.link_private")


def _fits(size: int) -> None:
    if size > MAX_SOURCE_BYTES:
        raise UnsupportedInput("error.too_big", mb=MAX_SOURCE_BYTES // (1024 * 1024))


def _media_url(page: str, base: str, source: str) -> str | None:
    found = {}
    for tag in META.findall(page):
        key = ATTRIBUTE.search(tag)
        value = CONTENT.search(tag)
        if not key or not value or key.group(1).lower() not in CARRIES_MEDIA:
            continue
        candidate = urljoin(base, value.group(1).strip())
        rank = _rank(candidate)
        if rank is not None:
            found.setdefault(rank, candidate)
    return found[min(found)] if found else _own_media(page, source)


# a page that hides its meta tags still spells the file out, but only its own id may be taken
def _own_media(page: str, source: str) -> str | None:
    token = _id_of(source)
    if not token:
        return None
    found = {}
    for candidate in ANY_URL.findall(page):
        rank = _rank(candidate) if token in candidate else None
        if rank is not None:
            found.setdefault(rank, candidate)
    return found[min(found)] if found else None


def _id_of(url: str) -> str | None:
    tokens = ID.findall(Path(urlparse(url).path).name)
    return max(tokens, key=len, default=None) if tokens else None


def _rank(url: str) -> int | None:
    suffix = Path(urlparse(url).path).suffix.lower()
    return PREFERENCE.index(suffix) if suffix in PREFERENCE else None


def _name(url: str, content_type: str) -> str:
    name = unquote(Path(urlparse(url).path).name) or "link"
    if Path(name).suffix.lower() in SUPPORTED_EXTENSIONS:
        return name
    known = EXTENSION_BY_MIME.get(content_type)
    return Path(name).stem + known if known else name

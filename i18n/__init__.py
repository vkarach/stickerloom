"""Every user-facing string lives in locales/<lang>.json and is looked up by key."""

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

LOCALES_DIR = Path(__file__).parent.parent / "locales"
DEFAULT_LANG = "en"

_BUNDLES: dict[str, dict] = {}


def _english_form(count: int) -> int:
    return 0 if count == 1 else 1


def _slavic_form(count: int) -> int:
    if count % 10 == 1 and count % 100 != 11:
        return 0
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return 1
    return 2


PLURAL_FORMS = {"en": _english_form, "ru": _slavic_form, "uk": _slavic_form}


def load() -> list[str]:
    """Read every locale and refuse to start when one drifts from the default."""
    _BUNDLES.clear()
    for path in sorted(LOCALES_DIR.glob("*.json")):
        _BUNDLES[path.stem] = json.loads(path.read_text(encoding="utf-8"))

    if DEFAULT_LANG not in _BUNDLES:
        raise RuntimeError(f"{LOCALES_DIR / (DEFAULT_LANG + '.json')} is missing")

    expected = set(_BUNDLES[DEFAULT_LANG])
    for lang, bundle in _BUNDLES.items():
        missing = expected - set(bundle)
        extra = set(bundle) - expected
        if missing or extra:
            raise RuntimeError(f"{lang}.json: missing {sorted(missing)}, unknown {sorted(extra)}")

    log.info("loaded locales: %s", ", ".join(sorted(_BUNDLES)))
    return sorted(_BUNDLES)


def languages() -> list[str]:
    return sorted(_BUNDLES)


def known(lang: str | None) -> str:
    """Map whatever Telegram reports to a language we actually have."""
    if not lang:
        return DEFAULT_LANG
    short = lang.split("-")[0].lower()
    return short if short in _BUNDLES else DEFAULT_LANG


class Translator:
    """Renders one key for one language, falling back to the default wording."""

    def __init__(self, lang: str = DEFAULT_LANG):
        self.lang = known(lang)

    def __call__(self, key: str, **params) -> str:
        text = self._text(key)
        if isinstance(text, list):
            form = PLURAL_FORMS.get(self.lang, _english_form)
            text = text[min(form(int(params.get("n", 0))), len(text) - 1)]
        return text.format(**params)

    def _text(self, key: str):
        for lang in (self.lang, DEFAULT_LANG):
            found = _BUNDLES.get(lang, {}).get(key)
            if found is not None:
                return found
        raise KeyError(f"no such string: {key}")

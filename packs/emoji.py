"""Telegram wants real emoji in emoji_list, so reject anything that plainly is not."""

MAX_EMOJI = 20

ZWJ = 0x200D
_ATTACHED = {ZWJ, 0xFE0F, 0xFE0E, 0x20E3}
_SKIN = range(0x1F3FB, 0x1F400)
_FLAG = range(0x1F1E6, 0x1F200)


def _is_emoji_char(char: str) -> bool:
    code = ord(char)
    if code in _ATTACHED or code in _SKIN:
        return True
    return code >= 0x1F000 or 0x2190 <= code <= 0x2BFF or 0x2600 <= code <= 0x27BF


def split_emoji(text: str) -> list[str]:
    """Cut a run of emoji into single ones; Telegram keeps only the first of a repeat."""
    parts: list[str] = []
    for char in text.strip():
        if not _is_emoji_char(char):
            return []
        code = ord(char)
        joined = code in _ATTACHED or code in _SKIN
        continues = bool(parts) and ord(parts[-1][-1]) == ZWJ
        pairs = bool(parts) and code in _FLAG and len(parts[-1]) == 1 and ord(parts[-1]) in _FLAG
        if parts and (joined or continues or pairs):
            parts[-1] += char
        else:
            parts.append(char)
    return list(dict.fromkeys(parts))


def is_emoji(text: str) -> bool:
    parts = split_emoji(text)
    return bool(parts) and len(parts) <= MAX_EMOJI

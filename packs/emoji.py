"""Telegram wants real emoji in emoji_list, so pick them out of whatever was sent."""

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
    """Pull the emoji out of a message, one entry each; Telegram drops repeats anyway."""
    parts: list[str] = []
    for char in text:
        if not _is_emoji_char(char):
            parts.append("")  # anything else ends the run it interrupts
            continue
        code = ord(char)
        last = parts[-1] if parts else ""
        joined = code in _ATTACHED or code in _SKIN
        continues = bool(last) and ord(last[-1]) == ZWJ
        pairs = len(last) == 1 and code in _FLAG and ord(last) in _FLAG
        if last and (joined or continues or pairs):
            parts[-1] += char
        else:
            parts.append(char)
    return list(dict.fromkeys(part for part in parts if part))


def is_emoji(text: str) -> bool:
    parts = split_emoji(text)
    return bool(parts) and len(parts) <= MAX_EMOJI

"""Telegram wants real emoji in emoji_list, so reject anything that plainly is not."""

MAX_EMOJI = 20

_JOINERS = {0x200D, 0xFE0F, 0xFE0E, 0x20E3}


def _is_emoji_char(char: str) -> bool:
    code = ord(char)
    if code in _JOINERS or 0x1F3FB <= code <= 0x1F3FF:
        return True
    return code >= 0x1F000 or 0x2190 <= code <= 0x2BFF or 0x2600 <= code <= 0x27BF


def is_emoji(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > MAX_EMOJI:
        return False
    return all(_is_emoji_char(char) for char in stripped)

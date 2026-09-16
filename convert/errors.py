class StickerloomError(Exception):
    """A failure the user may see: it carries the key of the text, not the text."""

    def __init__(self, key: str, **params):
        super().__init__(key)
        self.key = key
        self.params = params


class UnsupportedInput(StickerloomError):
    pass


class SourceTooLarge(StickerloomError):
    pass


class ProbeFailed(StickerloomError):
    pass


class EncodeFailed(StickerloomError):
    pass


class CannotFitSizeLimit(StickerloomError):
    def __init__(self, key: str, smallest: int, **params):
        super().__init__(key, **params)
        self.smallest = smallest


class NeedsWindow(Exception):
    """Not a failure: the source is longer than a sticker may be, so the user picks."""

    def __init__(self, source, info):
        super().__init__("too long to take whole")
        self.source = source
        self.info = info

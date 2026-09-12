class StickerloomError(Exception):
    """Base for failures whose message is safe to show the user."""


class UnsupportedInput(StickerloomError):
    pass


class SourceTooLarge(StickerloomError):
    pass


class ProbeFailed(StickerloomError):
    pass


class EncodeFailed(StickerloomError):
    pass


class CannotFitSizeLimit(StickerloomError):
    def __init__(self, message: str, smallest: int):
        super().__init__(message)
        self.smallest = smallest

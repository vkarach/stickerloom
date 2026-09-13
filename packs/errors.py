class PackError(Exception):
    """A pack failure the user may see: it carries the key of the text, not the text."""

    def __init__(self, key: str, **params):
        super().__init__(key)
        self.key = key
        self.params = params


class PackNotOurs(PackError):
    pass


class PackNotFound(PackError):
    pass


class PackFull(PackError):
    pass


class NameTaken(PackError):
    pass

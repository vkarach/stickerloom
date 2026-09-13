class PackError(Exception):
    """Base for pack failures whose message is safe to show the user."""


class PackNotOurs(PackError):
    pass


class PackNotFound(PackError):
    pass


class PackFull(PackError):
    pass


class NameTaken(PackError):
    pass

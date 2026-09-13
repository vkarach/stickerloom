import logging
import os

log = logging.getLogger(__name__)

ADMIN_ENV = "ADMIN_IDS"


def admin_ids() -> frozenset[int]:
    # an unset or unreadable list means nobody is an admin, not everybody
    found = set()
    for part in os.environ.get(ADMIN_ENV, "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            found.add(int(part))
        except ValueError:
            log.warning("%s holds %r, which is not a user id", ADMIN_ENV, part)
    return frozenset(found)

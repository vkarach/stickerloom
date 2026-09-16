"""Where a user stands right now. Exactly one of these holds at a time."""

IDLE = "idle"
NAMING = "naming"
COLLECTING = "collecting"
PREFIX = "prefix"
SOURCE = "source"
FILLING = "filling"
PICKING = "picking"
RETAGGING = "retagging"
CONFIRMING = "confirming"

ALL = frozenset({IDLE, NAMING, COLLECTING, PREFIX, SOURCE, FILLING, PICKING, RETAGGING,
                 CONFIRMING})

# files sent now belong to a pack instead of coming back as a plain conversion
PACK_MODE = frozenset({COLLECTING, FILLING})

# a sticker of the pack may be sent instead of picked
STICKER_MODE = frozenset({PICKING, RETAGGING})

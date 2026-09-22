"""Layout of the VISION four-view index record.

Each place is four quarter-turn views. Each view is a little-endian binary16
scale followed by 768 int8 values. 4 * 770 = 3080 bytes. This matches
`mma-vision index-layout` version 4. The server can check that shape. It
cannot recompute the SigLIP vector.
"""

from __future__ import annotations


VISION_FOUR_VIEW_MODEL = "vision-four-view-v4"
BYTES_PER_LOCATION = 3080
VIEWS_PER_LOCATION = 4
BYTES_PER_VIEW = 770
EMBEDDING_DIMENSION = 768
LAYOUT_VERSION = 4
SHARD_LOCATIONS = 50_000


def positive_finite_f16(raw: bytes) -> bool:
    if len(raw) != 2:
        return False
    value = raw[0] | (raw[1] << 8)
    exponent = (value >> 10) & 0x1F
    sign = value >> 15
    if exponent == 0x1F or sign != 0:
        return False
    return value != 0


def valid_four_view_record(record: bytes | bytearray | None) -> bool:
    if not isinstance(record, (bytes, bytearray)) or len(record) != BYTES_PER_LOCATION:
        return False
    for view in range(VIEWS_PER_LOCATION):
        offset = view * BYTES_PER_VIEW
        if not positive_finite_f16(record[offset : offset + 2]):
            return False
    return True

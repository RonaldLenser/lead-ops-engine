"""Time-ordered UUIDs (UUIDv7, RFC 9562).

Why v7 instead of random v4: the first 48 bits are a millisecond timestamp,
so new rows land at the end of the primary-key index instead of at random
positions. That keeps inserts cheap and makes IDs roughly sortable by
creation time. The remaining 74 bits are random, so IDs stay unguessable.

Python gains uuid.uuid7() only in 3.14 and PostgreSQL 17 has no built-in
generator, so this small implementation is used for every primary key.
"""

import os
import time
import uuid

_VERSION = 0x7
_VARIANT = 0b10  # RFC 9562 variant


def uuid7() -> uuid.UUID:
    unix_ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")  # 80 random bits, 74 used
    rand_a = rand >> 68 & 0xFFF  # 12 bits
    rand_b = rand & ((1 << 62) - 1)  # 62 bits
    value = (
        (unix_ms & ((1 << 48) - 1)) << 80 | _VERSION << 76 | rand_a << 64 | _VARIANT << 62 | rand_b
    )
    return uuid.UUID(int=value)

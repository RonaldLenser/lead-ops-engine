"""In-process token-bucket rate limiting.

Each identity (an IP, an API key, a webhook source) gets a bucket that holds
up to `capacity` tokens and refills at `capacity` tokens per minute. A
request takes one token; an empty bucket means 429 with Retry-After.

Scope, on purpose: the buckets live in this process's memory. That is
correct for v1, which runs a single uvicorn worker on one VPS. With several
workers or instances each would count separately, so the effective limit
would multiply. Distributed rate limiting (a shared store such as Redis) is
out of scope until the system actually scales horizontally (ADR-0011).

Memory is bounded: at most `max_tracked` identities are kept, and the
least recently used are evicted first.

Safe without locks: the event loop runs one coroutine at a time, and
`hit()` never awaits, so the read-modify-write cannot interleave.
"""

import math
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int


class TokenBucketLimiter:
    def __init__(
        self,
        per_minute: int,
        max_tracked: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if per_minute < 1:
            raise ValueError("per_minute must be at least 1")
        self.capacity = float(per_minute)
        self.refill_per_second = per_minute / 60.0
        self.max_tracked = max_tracked
        self._clock = clock
        self._buckets: OrderedDict[str, _Bucket] = OrderedDict()

    def hit(self, identity: str) -> RateLimitDecision:
        now = self._clock()
        bucket = self._buckets.pop(identity, None)
        if bucket is None:
            bucket = _Bucket(tokens=self.capacity, updated_at=now)
        else:
            elapsed = now - bucket.updated_at
            bucket.tokens = min(self.capacity, bucket.tokens + elapsed * self.refill_per_second)
            bucket.updated_at = now
        self._buckets[identity] = bucket  # most recently used goes last
        while len(self._buckets) > self.max_tracked:
            self._buckets.popitem(last=False)

        if bucket.tokens >= 1:
            bucket.tokens -= 1
            return RateLimitDecision(allowed=True, retry_after_seconds=0)
        missing = 1 - bucket.tokens
        return RateLimitDecision(
            allowed=False, retry_after_seconds=max(1, math.ceil(missing / self.refill_per_second))
        )

    def __len__(self) -> int:
        return len(self._buckets)

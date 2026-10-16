import pytest

from leadops.api.rate_limit import TokenBucketLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_allows_a_burst_up_to_capacity_then_blocks() -> None:
    limiter = TokenBucketLimiter(per_minute=3, clock=FakeClock())

    decisions = [limiter.hit("ip-1").allowed for _ in range(4)]

    assert decisions == [True, True, True, False]


def test_blocked_requests_get_a_retry_after() -> None:
    limiter = TokenBucketLimiter(per_minute=60, clock=FakeClock())
    for _ in range(60):
        limiter.hit("ip-1")

    decision = limiter.hit("ip-1")

    assert not decision.allowed
    assert decision.retry_after_seconds == 1


def test_tokens_refill_over_time() -> None:
    clock = FakeClock()
    limiter = TokenBucketLimiter(per_minute=60, clock=clock)
    for _ in range(60):
        limiter.hit("ip-1")

    clock.now += 2.0

    assert [limiter.hit("ip-1").allowed for _ in range(3)] == [True, True, False]


def test_identities_are_independent() -> None:
    limiter = TokenBucketLimiter(per_minute=1, clock=FakeClock())

    assert limiter.hit("a").allowed
    assert limiter.hit("b").allowed
    assert not limiter.hit("a").allowed


def test_memory_is_bounded_by_evicting_least_recently_used() -> None:
    limiter = TokenBucketLimiter(per_minute=1, max_tracked=2, clock=FakeClock())
    limiter.hit("a")
    limiter.hit("b")
    limiter.hit("c")  # evicts "a"

    assert len(limiter) == 2
    assert limiter.hit("a").allowed  # "a" starts over with a full bucket


def test_capacity_must_be_positive() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        TokenBucketLimiter(per_minute=0)

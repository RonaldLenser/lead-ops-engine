import time

from leadops.ids import uuid7


def test_uuid7_has_version_7_and_rfc_variant() -> None:
    value = uuid7()

    assert value.version == 7
    assert value.variant == "specified in RFC 4122"


def test_uuid7_embeds_the_current_millisecond_timestamp() -> None:
    before = time.time_ns() // 1_000_000
    value = uuid7()
    after = time.time_ns() // 1_000_000

    assert before <= value.int >> 80 <= after


def test_uuid7_sorts_by_creation_time_across_milliseconds() -> None:
    earlier = uuid7()
    time.sleep(0.002)
    later = uuid7()

    assert earlier < later


def test_uuid7_values_are_unique() -> None:
    assert len({uuid7() for _ in range(10_000)}) == 10_000

import pytest

from leadops.pii import mask_pii_processor, mask_text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("contact jane.prospect@example.com now", "contact j***@e***.com now"),
        ("owner@shop.co.uk", "o***@s***.uk"),
        ("call (540) 395-0123 today", "call (***23 today"),
        ("+1 540 395 0123", "***23"),
        ("5403950123", "***23"),
    ],
)
def test_emails_and_phones_are_masked(text: str, expected: str) -> None:
    assert mask_text(text) == expected


def test_api_keys_keep_only_the_public_prefix() -> None:
    key = "lok_1a2b3c4d5e_" + "S" * 43  # gitleaks:allow (fake key built for the test)

    assert mask_text(f"auth with {key}") == "auth with lok_1a2b3c4d5e_***"


@pytest.mark.parametrize(
    "text",
    [
        "2026-10-16T01:11:52Z",
        "duration 123456 ms",
        "0199f1a2-7c3e-7b4d-8a9e-123456789012",  # numeric UUID segment
        "request_completed",
        "status 404",
    ],
)
def test_non_personal_values_are_untouched(text: str) -> None:
    assert mask_text(text) == text


def test_masking_is_deterministic() -> None:
    assert mask_text("jane@example.com") == mask_text("jane@example.com")


def test_processor_masks_nested_values_but_skips_ids_and_numbers() -> None:
    event = {
        "event": "failed for jane@example.com",
        "details": {"phones": ["540-395-0123"]},
        "lead_id": "5403950123",
        "key_prefix": "1234567890",
        "count": 5403950123,
    }

    masked = mask_pii_processor(None, "info", event)

    assert masked == {
        "event": "failed for j***@e***.com",
        "details": {"phones": ["***23"]},
        "lead_id": "5403950123",
        "key_prefix": "1234567890",
        "count": 5403950123,
    }

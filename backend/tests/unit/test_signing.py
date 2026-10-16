import hashlib
import hmac

import pytest

from leadops.integrations.signing import SignatureProblem, compute_signature, verify_signature

SECRET = "s" * 32
NOW = 1_760_000_000
BODY = b'{"event_id":"evt_1","message":"hi"}'


def verify(**overrides: object) -> SignatureProblem | None:
    arguments: dict[str, object] = {
        "secrets": [SECRET],
        "timestamp_header": str(NOW),
        "signature_header": compute_signature(SECRET, NOW, BODY),
        "body": BODY,
        "now": NOW,
        "tolerance_seconds": 300,
    }
    arguments.update(overrides)
    return verify_signature(**arguments)  # type: ignore[arg-type]


def test_signature_matches_the_documented_contract() -> None:
    expected = hmac.new(SECRET.encode(), f"{NOW}.".encode() + BODY, hashlib.sha256).hexdigest()

    assert compute_signature(SECRET, NOW, BODY) == f"v1={expected}"


def test_valid_signature_passes() -> None:
    assert verify() is None


def test_any_configured_secret_is_accepted_for_rotation() -> None:
    new_secret = "n" * 32

    assert (
        verify(
            secrets=[SECRET, new_secret],
            signature_header=compute_signature(new_secret, NOW, BODY),
        )
        is None
    )


@pytest.mark.parametrize(
    ("overrides", "problem"),
    [
        ({"timestamp_header": None}, SignatureProblem.MISSING_HEADERS),
        ({"signature_header": ""}, SignatureProblem.MISSING_HEADERS),
        ({"timestamp_header": "yesterday"}, SignatureProblem.MALFORMED),
        ({"signature_header": "v2=" + "a" * 64}, SignatureProblem.MALFORMED),
        ({"now": NOW + 301}, SignatureProblem.STALE_TIMESTAMP),
        ({"now": NOW - 301}, SignatureProblem.STALE_TIMESTAMP),
        ({"body": BODY + b" "}, SignatureProblem.MISMATCH),
        ({"secrets": ["x" * 32]}, SignatureProblem.MISMATCH),
        ({"secrets": []}, SignatureProblem.MISMATCH),
    ],
)
def test_problems_are_detected(overrides: dict[str, object], problem: SignatureProblem) -> None:
    assert verify(**overrides) == problem


def test_signature_covers_the_timestamp() -> None:
    # A captured request re-sent with a fresh timestamp header no longer verifies.
    assert verify(timestamp_header=str(NOW + 10), now=NOW + 10) == SignatureProblem.MISMATCH

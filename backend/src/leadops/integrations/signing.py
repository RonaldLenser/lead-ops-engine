"""HMAC request signing (contract version v1).

A sender proves it holds a shared secret and that the body was not changed:

    X-LeadOps-Timestamp: <unix seconds>
    X-LeadOps-Signature: v1=<hex HMAC-SHA256(secret, "<timestamp>.<raw body bytes>")>

Rules enforced by verify_signature():
- The signature covers the timestamp, so an old request cannot be re-dated.
- The timestamp must be within `tolerance_seconds` of the server clock, which
  limits replays to a short window. Inside that window, the event-ID unique
  constraint rejects replays of the same event.
- Comparison is constant time (hmac.compare_digest).
- Several secrets can be valid at once, so a secret can be rotated without
  downtime: add the new one, move senders over, remove the old one.

The body is the exact bytes received, verified BEFORE any JSON parsing.
"""

import hashlib
import hmac
import re
from collections.abc import Iterable
from enum import StrEnum

SIGNATURE_VERSION = "v1"
TIMESTAMP_HEADER = "X-LeadOps-Timestamp"
SIGNATURE_HEADER = "X-LeadOps-Signature"

_SIGNATURE = re.compile(r"v1=(?P<hex>[0-9a-f]{64})")
_TIMESTAMP = re.compile(r"\d{1,12}")


class SignatureProblem(StrEnum):
    MISSING_HEADERS = "missing_headers"
    MALFORMED = "malformed"
    STALE_TIMESTAMP = "stale_timestamp"
    MISMATCH = "mismatch"


def compute_signature(secret: str, timestamp: int, body: bytes) -> str:
    message = str(timestamp).encode("ascii") + b"." + body
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_VERSION}={digest}"


def verify_signature(
    *,
    secrets: Iterable[str],
    timestamp_header: str | None,
    signature_header: str | None,
    body: bytes,
    now: int,
    tolerance_seconds: int,
) -> SignatureProblem | None:
    """None when valid, otherwise the reason it is not (for logs, never for clients)."""
    if not timestamp_header or not signature_header:
        return SignatureProblem.MISSING_HEADERS
    if not _TIMESTAMP.fullmatch(timestamp_header) or not _SIGNATURE.fullmatch(signature_header):
        return SignatureProblem.MALFORMED
    timestamp = int(timestamp_header)
    if abs(now - timestamp) > tolerance_seconds:
        return SignatureProblem.STALE_TIMESTAMP
    presented = signature_header.encode("ascii")
    # Check every secret (no early exit), so timing does not reveal which one matched.
    matched = False
    for secret in secrets:
        expected = compute_signature(secret, timestamp, body).encode("ascii")
        matched |= hmac.compare_digest(expected, presented)
    return None if matched else SignatureProblem.MISMATCH

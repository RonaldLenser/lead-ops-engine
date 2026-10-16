"""API key format, generation, and verification.

Format:  lok_<prefix>_<secret>
         lok_      fixed marker ("lead ops key"), makes leaked keys easy to grep and scan for
         prefix    10 lowercase hex chars, public, stored, used to find the key row
         secret    43 URL-safe chars = 32 random bytes from the OS CSPRNG

Storage: only the prefix and SHA-256(full key). The key itself is shown once at
creation and never stored or logged.

Why SHA-256 and not Argon2/bcrypt: slow password hashes exist because human
passwords are guessable. These keys carry 256 bits of randomness, so brute
force against a SHA-256 digest is not feasible, and a fast hash keeps every
request cheap. User passwords (M6) still use Argon2id.

Verification compares digests with hmac.compare_digest (constant time), so
response timing does not reveal how much of a guessed key was correct.
"""

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from enum import StrEnum

KEY_MARKER = "lok"
PREFIX_BYTES = 5  # 10 hex chars
SECRET_BYTES = 32  # 43 URL-safe chars

_KEY_FORMAT = re.compile(r"lok_(?P<prefix>[0-9a-f]{10})_(?P<secret>[A-Za-z0-9_-]{43})")


class Scope(StrEnum):
    LEADS_WRITE = "leads:write"
    DELIVERY_CALLBACK = "delivery:callback"


@dataclass(frozen=True)
class GeneratedKey:
    full_key: str  # show once, never store
    prefix: str
    digest: bytes


def hash_key(full_key: str) -> bytes:
    # utf-8, not ascii: a malformed presented key must hash, not crash. Real keys are ascii.
    return hashlib.sha256(full_key.encode("utf-8")).digest()


def generate_key() -> GeneratedKey:
    prefix = secrets.token_hex(PREFIX_BYTES)
    secret = secrets.token_urlsafe(SECRET_BYTES)
    full_key = f"{KEY_MARKER}_{prefix}_{secret}"
    return GeneratedKey(full_key=full_key, prefix=prefix, digest=hash_key(full_key))


def parse_prefix(presented: str) -> str | None:
    """The public prefix of a well-formed key, or None if the format is wrong."""
    match = _KEY_FORMAT.fullmatch(presented)
    return match.group("prefix") if match else None


def digest_matches(presented: str, stored_digest: bytes) -> bool:
    return hmac.compare_digest(hash_key(presented), stored_digest)

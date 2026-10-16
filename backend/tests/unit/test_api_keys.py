import hashlib
import re

from leadops.security.api_keys import digest_matches, generate_key, hash_key, parse_prefix


def test_generated_key_format() -> None:
    key = generate_key()

    assert re.fullmatch(r"lok_[0-9a-f]{10}_[A-Za-z0-9_-]{43}", key.full_key)
    assert key.full_key.startswith(f"lok_{key.prefix}_")


def test_only_the_sha256_digest_is_kept_for_storage() -> None:
    key = generate_key()

    assert key.digest == hashlib.sha256(key.full_key.encode()).digest()
    assert len(key.digest) == 32


def test_keys_are_unique() -> None:
    keys = {generate_key().full_key for _ in range(1_000)}

    assert len(keys) == 1_000


def test_parse_prefix_accepts_only_well_formed_keys() -> None:
    key = generate_key()

    assert parse_prefix(key.full_key) == key.prefix
    assert parse_prefix("lok_short_x") is None
    assert parse_prefix(key.full_key + "extra") is None
    assert parse_prefix("Bearer " + key.full_key) is None


def test_digest_matches_only_the_exact_key() -> None:
    key = generate_key()

    assert digest_matches(key.full_key, key.digest)
    assert not digest_matches(key.full_key[:-1] + "x", key.digest)


def test_malformed_unicode_input_hashes_instead_of_crashing() -> None:
    assert len(hash_key("garbage-é")) == 32

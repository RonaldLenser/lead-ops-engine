# ADR-0012: API key format and SHA-256 hashing

- **Status:** Accepted
- **Date:** 2026-10-15

## Context

Machine clients (n8n, form backends) authenticate with API keys (ADR-0008). Keys must never be recoverable from the database, must be revocable, must carry scopes, and must be cheap to verify on every request.

## Decision

**Format:** `lok_<prefix>_<secret>`

- `lok_`: fixed marker, so leaked keys are easy to recognize and scan for (the log masker redacts this shape).
- `prefix`: 10 lowercase hex characters, public, stored, used to look the key up.
- `secret`: `secrets.token_urlsafe(32)`, which is 256 bits from the OS CSPRNG (43 characters).

**Storage:** `prefix`, `key_sha256` (SHA-256 of the full key), `scopes`, `created_at`, `last_used_at`, `revoked_at`. The full key is printed once by the CLI and never stored or logged.

**Verification:**

1. Parse the prefix.
2. Load the row.
3. Compare digests with `hmac.compare_digest`. A dummy digest is compared when the prefix is unknown, so every failure takes the same path.
4. Revoked keys fail like wrong keys.
5. A missing scope returns 403.

## Alternatives Considered

| Option | Why not |
|---|---|
| Argon2id or bcrypt for keys | Slow hashes defend low-entropy human passwords. A 256-bit random secret cannot be brute-forced from its SHA-256 digest, and a slow hash would add tens of milliseconds to every request. User passwords (M6) still use Argon2id. |
| Storing keys encrypted | Encryption is reversible; anyone with the encryption key and a database dump gets every API key. |
| JWTs for machine clients | Revocation needs a denylist anyway, and long-lived signed tokens add complexity without benefit here. |
| No prefix (hash-only lookup) | Works, but the prefix makes keys identifiable in the CLI and in logs without exposing the secret. |

## Tradeoffs

- Gained: constant-time, single-query verification; nothing usable is stored.
- Lost: a lost key cannot be recovered. It must be revoked and replaced, which is the intended behavior.

## Consequences

- `leadops api-keys create|list|revoke` is the only way to manage keys in v1. Every action is written to `audit_events`.
- `last_used_at` is updated at most once a minute per key, to avoid a write on every request.

## Why This Fits This Project

It matches how major API platforms issue keys (prefixed, shown once, stored hashed). Choosing SHA-256 over Argon2 for random secrets, and explaining why, is a precise security judgment rather than a default.

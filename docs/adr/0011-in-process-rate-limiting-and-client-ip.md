# ADR-0011: In-process rate limiting and trusted-proxy client IP

- **Status:** Accepted
- **Date:** 2026-10-15

## Context

M2 opens two public write endpoints. They need protection against floods (cost, database load) and against API-key guessing. Rate limiting per client IP needs a trustworthy client IP, and behind a reverse proxy (Caddy, ADR-0010) the socket peer is the proxy, not the client.

v1 runs one uvicorn worker on one VPS. Adding Redis only for rate limiting was explicitly ruled out (ADR-0007).

## Decision

**Rate limiting:** an in-process token bucket per (limit, identity).

- Three limits, all configurable in requests per minute: per client IP on intake (checked before authentication), per API key, per webhook source.
- A blocked request gets `429` with `Retry-After`.
- Memory is bounded: at most 10,000 identities per limiter, least recently used evicted first.
- No locks: the check never awaits, so on one event loop it cannot interleave.

**Client IP:**

- Default: the socket peer. `X-Forwarded-For` is ignored.
- Only when the peer is inside `TRUSTED_PROXY_CIDRS` is the header read, right to left, skipping trusted proxy hops. The first untrusted address is the client.
- A malformed entry stops the walk and falls back to the peer.
- Uvicorn runs with `--no-proxy-headers` so it does not rewrite the peer itself.

## Alternatives Considered

| Option | Why not |
|---|---|
| Redis-backed limiter | Correct across instances, but a second stateful system for a single-instance deployment. |
| PostgreSQL counters | Shared across instances, but adds a write per request to the database the limiter is meant to protect. |
| Rate limiting only at Caddy | Caddy has no knowledge of API keys or webhook sources. Worth adding later as an outer layer. |
| Trusting the leftmost `X-Forwarded-For` entry | Any client can set it, so a spoofer gets a fresh bucket per request. |

## Tradeoffs

- Gained: no new infrastructure, microsecond checks, simple to test with a fake clock.
- Lost: limits reset on restart, and each process counts separately. With N workers the effective limit is N times the configured one.

## Consequences

- **Distributed rate limiting is out of scope until the system scales horizontally.** Moving to several workers or instances requires revisiting this ADR (shared store, or limits at the proxy).
- The production Caddy network must be listed in `TRUSTED_PROXY_CIDRS` (M9), or every client will appear as the proxy and share one bucket.
- Tests cover spoofed headers from untrusted peers, trusted proxy chains, IPv6, and malformed headers.

## Why This Fits This Project

It protects the endpoints that exist now at the scale that exists now, and it states exactly when it stops being enough.

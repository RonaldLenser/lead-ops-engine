# ADR-0008: Session authentication + scoped API keys + RBAC

- **Status:** Accepted
- **Date:** 2026-10-15

## Context

Two kinds of clients call the API:

- **Machines:** n8n posting leads and delivery callbacks, and form tools posting webhooks.
- **People:** reviewers and admins using the SPA to approve messages, triage leads, and resolve delivery problems.

Approval is the main safety control (ADR-0004), so who approved must be known and recorded. The public demo needs read-only and reviewer accounts that cannot manage keys or users.

## Decision

1. **Webhooks:** HMAC-SHA256 over `timestamp.body`, one secret per source, constant-time comparison, 5-minute window.
2. **Machine clients:** API keys, generated randomly, stored as a hash with a short prefix for lookup, shown once, revocable, with scopes:
   - `leads:write` for intake
   - `delivery:callback` for delivery results
3. **People:** email and password (argon2id), then an opaque random session token stored hashed in `sessions`, sent as a cookie with httpOnly, Secure, SameSite=Strict. Sessions expire and can be revoked server side. State-changing requests also require a custom header.
4. **RBAC:** three roles, enforced by a FastAPI dependency on every route.
   - `viewer`: read only
   - `reviewer`: viewer plus approve, reject, triage, resolve delivery, outcomes
   - `admin`: reviewer plus reprocess, dead-letter actions, and API keys
5. **Audit:** logins, failed logins, key creation and revocation, and every approval are written to `audit_events`.
6. **Bootstrap:** the operator creates users and the first API key with CLI commands on the server (`leadops users create`, `leadops api-keys create`). No user-management endpoint in v1.

API-key auth arrives in M2 with intake. User auth and RBAC arrive in M6 with approvals, so no approval can exist without a known reviewer.

## Alternatives Considered

| Option | Why not |
|---|---|
| JWT access tokens for the SPA | Hard to revoke before expiry, and token storage in the browser is a common mistake. A same-origin SPA does not need stateless tokens. |
| Hosted auth (Auth0, Clerk, Supabase Auth) | Removes work but also removes the part reviewers want to see understood. Adds an external dependency to a self-hosted system. |
| Basic auth or one shared admin key | No per-person audit trail, which breaks the approval record. |
| OAuth login with Google | Good for a real deployment, but extra setup for demo users. Can be added later on top of the same session model. |

## Tradeoffs

- Gained: per-person accountability for approvals, least privilege for n8n, revocable access everywhere.
- Lost: no SSO or MFA in v1.
- Risk: hand-rolled session auth has to be done carefully. Mitigated by using standard libraries for hashing and token generation, keeping the design minimal, and testing every route against every role.

## Consequences

- An integration test matrix checks each route with no auth, each role, and each API key scope.
- Demo accounts are `viewer` and `reviewer` only.
- Same-origin hosting of the SPA (ADR-0009) is required for SameSite=Strict cookies to work without CORS.

## Why This Fits This Project

The approval workflow only means something if the system knows who approved. This setup is small enough to explain fully in an interview and covers the standard split between machine and human authentication.

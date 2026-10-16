# Security

Status: approved design (M0). None of these controls are implemented yet. Each row names the milestone that builds it.

Source: [DESIGN.md](DESIGN.md) sections 9, 10, 11.

---

## 1. Assets

| Asset | Why it matters |
|---|---|
| Lead PII (names, emails, phones, message text) | Personal data of people who never agreed to be in a demo |
| The ability to send email as the business | Abuse would damage the sender's reputation and reach strangers |
| LLM API key and spend | Direct cost |
| Reviewer accounts | Approvers control what gets sent |
| Audit log | The record of who did what |

---

## 2. Threats and Controls

| Threat | Control | Milestone |
|---|---|---|
| Forged webhook | HMAC-SHA256 over `timestamp.body`, per-source secret, constant-time compare, 5-minute window | M2 |
| Replayed or duplicate event | UNIQUE `(source, external_event_id)`; `Idempotency-Key` required on `/v1/leads` | M2 |
| Flooding and junk submissions | Rate limit per IP and per API key; 32 KB body limit; spam leads routed to SPAM by deterministic rules | M2 (limits), M4 (routing) |
| Prompt injection in lead text | Lead text delimited as untrusted data; output is schema-only; the model has no side-effect tools; evidence verification; deterministic policy checks; human approval; injection cases in the eval set | M4, M5, M6 |
| LLM output steering actions | Model output is validated data. Routing, scoring, and approval are code and humans. See [ADR-0003](adr/0003-llm-extracts-code-decides.md). | M4 |
| Unauthorized actions | RBAC dependency on every route (`admin`, `reviewer`, `viewer`); a test matrix covering every route and role | M6 |
| Password attacks | argon2id hashes; login rate limit | M6 |
| Session theft, CSRF | Opaque random token, stored hashed, httpOnly, Secure, SameSite=Strict, same-origin SPA, custom header required on state-changing requests, server-side revocation | M6 |
| Leaked API key | Keys stored hashed, shown once, scoped, revocable, `last_used_at` tracked | M2 |
| Secrets in the repo | Secrets only in environment variables; `.env` gitignored; `.env.example` has names only; `gitleaks` in CI and pre-commit | M1 |
| App starts with missing secrets | Config validation refuses to start; error messages never echo config values | M1 |
| Outbound abuse from the public demo | `DELIVERY_MODE=sink` in the demo, so nothing is emailed; real sending is opt-in config for a private deployment | M7, M9 |
| Duplicate outbound email | Duplicate-outbound protection, see section 4 | M7 |
| LLM cost exhaustion | Daily spend cap; per-lead call limit | M4 |
| Over-privileged n8n | n8n API key scopes: `leads:write`, `delivery:callback` only | M2, M7 |
| Database exposure | Postgres on the internal Docker network only; app DB role has no DDL; migrations use a separate role | M1, M9 |
| Tampering with history | `audit_events` is append-only; no update or delete path in the application | M2 |

---

### Implemented so far (M1)

| Control | Where | Verified by |
|---|---|---|
| Required settings, no secret defaults, unsafe production database settings refused at startup (dev passwords, no password, superuser, shared app/migrator role, SQL echo) | `backend/src/leadops/config.py` | `tests/unit/test_config.py` |
| Connection strings are `SecretStr` and never echoed in validation errors | `config.py` | `test_config.py` |
| App database role cannot create, alter, or drop schema objects; migrations use a separate owner role | `infra/postgres/init/01-roles.sql` | `tests/integration/test_database_roles.py` |
| Tracebacks logged without local variables; SQL statements never logged by default; validation errors never echo submitted values | `logging_config.py`, `api/errors.py` | `test_logging.py`, `test_errors.py` |
| Client request IDs accepted only if short and safe | `api/middleware.py` | `test_request_context.py` |
| Secret scanning | `.pre-commit-config.yaml`, CI `secrets` job | gitleaks |
| Container runs as a non-root user | `backend/Dockerfile` | CI Docker job |

## 3. PII and Data Retention

### Synthetic data only

The repository, eval datasets, screenshots, demo video, and public demo contain **synthetic data only**. No real lead, client, or prospect data is ever committed or loaded into the public demo. Eval leads may be LLM-drafted for variety; their labels are set and checked by hand.

### Raw inbound payloads

`inbound_events.payload_jsonb` stores the raw, unvalidated request body. It exists for debugging and replay: when a source changes its format or validation rejects a payload, the original is available to inspect.

Because it is raw, it can contain any PII the sender included, including fields the application does not use.

**Policy:** production deployments purge raw payloads after a configurable period.

| Setting | Default | Meaning |
|---|---|---|
| `RAW_EVENT_RETENTION_DAYS` | `30` | Age after which `inbound_events.payload_jsonb` and `ai_calls.raw_output` are set to NULL |

What a purge does:

- Sets `payload_jsonb` to NULL and stamps `payload_purged_at`.
- Keeps `source`, `external_event_id`, `idempotency_key`, `payload_sha256`, timestamps, and `lead_id`. The UNIQUE constraint therefore keeps blocking duplicates after the purge.

Implementation status: the setting is defined in config in M2. **The scheduled purge job is built in M9** with backups and the production runbook. Until then, raw payloads are not purged automatically, which is acceptable only because pre-M9 environments hold synthetic data.

### Other PII locations

| Location | Policy |
|---|---|
| `leads`, `contacts`, `messages`, `lead_analyses` | Operational records. No automatic deletion in v1; the operator's own policy applies. |
| Application logs | Email and phone masked by a log processor. Message bodies and raw payloads are never logged. |
| n8n notifications | IDs and dashboard links only. |
| n8n workflow exports in the repo | Credentials and real addresses removed before commit. |
| Database backups | Contain PII. Retention is set by the operator and documented in the runbook (M9). |
| `ai_calls.raw_output` (invalid responses only) | Treated as PII. Never committed, never logged in full (length and hash only), linked to `ai_call_id` and `workflow_run_id`, purged after `RAW_EVENT_RETENTION_DAYS` by the M9 purge job. Telemetry (outcome, validation errors, model, prompt version, latency, tokens, cost) remains after purge. |

### Known v1 limitations

- No automated handling of deletion requests from leads.
- No field-level encryption. Protection relies on network isolation, access control, and disk encryption at the host.

---

## 4. Outbound Delivery: What Is and Is Not Guaranteed

The system provides **duplicate-outbound protection**. It does **not** provide exactly-once email delivery, and no documentation, README, or interview answer for this project should claim it.

Guaranteed:

1. **Duplicate internal delivery jobs are prevented.** One job per `(message_id, dispatch_attempt)` (`jobs.dedupe_key`), and a compare-and-set claim so only one worker can dispatch a message.
2. **Once a send may have reached the provider, an ambiguous or unknown result is never retried automatically.**
3. **Ambiguous delivery moves the lead to NEEDS_REVIEW** (`delivery_unknown`).
4. **A human determines the next action:** confirm it was sent, resend deliberately, or abandon.

Not guaranteed:

- That an email was delivered exactly once in every failure scenario. A human resend after an ambiguous result can still duplicate if the first send did go out; the reviewer is expected to check the Sent folder first.
- Delivery to the recipient's inbox (spam filtering is outside the system).

Automatic retry is allowed only when the failure proves the request never left the system: DNS failure, connection refused, TLS handshake failure.

The n8n delivery workflow must have "Retry On Fail" disabled on the send node. Otherwise n8n could resend without the system knowing.

Full reasoning: [ADR-0005](adr/0005-outbound-delivery-ambiguity.md).

---

## 5. Human Approval as a Security Control

In v1, **every outbound message, AI-drafted or templated, requires a reviewer's approval** before a delivery job is created. There is no code path from draft to dispatch that skips the `approvals` table. Reviewer edits are re-checked by the same deterministic policy rules as AI drafts. See [ADR-0004](adr/0004-human-approval-for-all-outbound-v1.md).

---

## 6. No Policy Override

No role, including `admin`, can bypass a deterministic policy check on a message. If a legitimate business requirement conflicts with a policy rule, the versioned policy configuration is changed deliberately in a reviewed PR with tests, never per message.

## 7. Roles

| Role | Can |
|---|---|
| `viewer` | Read leads, timelines, metrics |
| `reviewer` | Viewer, plus approve and reject messages, triage leads, resolve delivery, record outcomes |
| `admin` | Reviewer, plus reprocess leads, view and requeue dead jobs (not delivery jobs), manage API keys |

Users are created by the operator with a CLI command on the server (`leadops users create`). There is no user-management endpoint in v1.

Machine clients use API keys with scopes, not roles.

---

## 8. Reporting

This is a portfolio project. Security issues can be reported by opening a GitHub issue without sensitive details, or by contacting the owner through the GitHub profile.

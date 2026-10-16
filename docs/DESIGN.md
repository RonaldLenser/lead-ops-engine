# Lead Ops Engine: Design Document

Public title: Lead Ops Engine: AI lead qualification with human approval

| | |
|---|---|
| Status | Architecture approved (M0). Nothing below is implemented yet. |
| Owner | Ron Lenser |
| Approved | 2026-10-15 |
| Last updated | 2026-10-15 |
| Related | [architecture.md](architecture.md), [state-machine.md](state-machine.md), [security.md](security.md), [ADRs](adr/README.md) |

This document is the source of truth for the v1 design. The three companion docs expand sections of it and must not contradict it. Every feature described here is **planned** unless the milestone table in section 17 marks it done.

---

## 1. Problem

A small service business gets inbound leads from a website form, third-party form tools, and email. Each lead has to be read, sorted, judged, and answered. Doing this by hand is slow and inconsistent, and the first response often goes out hours or days late.

Handing the whole job to an LLM creates different problems: invented facts, uncalibrated scores, prompt injection through the lead's own message, emails sent with no human check, and no record of why a decision was made.

Lead Ops Engine automates the reading and drafting with an LLM, keeps every decision in deterministic code, requires a human to approve every outbound message in v1, and records every step.

**Example business:** Ron Lenser Digital, a one-person software and automation shop in Fredericksburg, VA. Its real policies drive the rules: projects are quoted at a fixed price in writing after a short call, so drafts never quote prices and always ask for a call. All data in this repository is synthetic.

---

## 2. Approved Decisions

| # | Decision | ADR |
|---|---|---|
| 1 | FastAPI + PostgreSQL own all application and workflow state. n8n is an integration edge and owns no business logic. | [0001](adr/0001-fastapi-postgres-own-workflow-state.md) |
| 2 | PostgreSQL job queue using `SELECT ... FOR UPDATE SKIP LOCKED`. No Redis, Celery, or Temporal. | [0002](adr/0002-postgres-job-queue-skip-locked.md) |
| 3 | The LLM extracts facts. Deterministic code does scoring, routing, missing-field checks, and policy decisions. | [0003](adr/0003-llm-extracts-code-decides.md) |
| 4 | 100% human approval for outbound messages in v1. | [0004](adr/0004-human-approval-for-all-outbound-v1.md) |
| 5 | Duplicate-outbound protection: no automatic retry of an ambiguous send. Not "exactly-once". | [0005](adr/0005-outbound-delivery-ambiguity.md) |
| 6 | Claude behind an AI provider Protocol, with model tiering. | [0006](adr/0006-claude-provider-protocol-model-tiering.md) |
| 7 | No agent framework, LangGraph, MCP, multi-agent design, Redis, or Kubernetes in v1. | [0007](adr/0007-no-agent-framework-v1.md) |
| 8 | Session authentication + scoped API keys + RBAC. | [0008](adr/0008-session-auth-api-keys-rbac.md) |
| 9 | Vite + React + TypeScript SPA with OpenAPI-generated types. | [0009](adr/0009-vite-react-spa-openapi-types.md) |
| 10 | VPS + Docker Compose deployment. | [0010](adr/0010-vps-docker-compose-deployment.md) |
| A | Raw inbound payloads are retained for a configurable period (`RAW_EVENT_RETENTION_DAYS`), then purged. Repo and demo contain synthetic data only. | Section 10 |
| B | Outbound guarantee is stated precisely (section 9). No exactly-once claim anywhere. | 0005 |

**Out of scope for v1:** LangGraph, MCP, multi-agent anything, Redis, Kubernetes, Next.js, SMS, multi-tenancy, a second live LLM provider, paid enrichment APIs, web scraping.

---

## 3. Design Principles

1. **One source of truth.** Every state change is a row in PostgreSQL, written in the same transaction as its audit event.
2. **LLM extracts, code decides.** Model output is data to validate, never an instruction to execute.
3. **LLM signals can only add oversight.** A model flag can send a lead to human review. It can never cause an outbound action. The two automatic closes (SPAM, DISQUALIFIED) each require a deterministic condition, and both stay reversible by a reviewer.
4. **No side effect without a human in v1.** Nothing leaves the system unless a reviewer approved that exact message.
5. **When unsure whether a send happened, stop and ask a human.** Never guess by resending.
6. **Nothing is lost.** Every failure path ends in a state a human can see: NEEDS_REVIEW or a dead-lettered job.
7. **Measure before claiming.** Metrics are reported only from reproducible runs. Unmeasured metrics are TBD.

---

## 4. Architecture

```text
 Website form ─┐                ┌──────────────── VPS (Docker Compose) ────────────────┐
 Form tools  ──┼─► n8n (edge) ──┼─► Caddy (TLS) ─► FastAPI "api" ◄── React SPA (same origin)
 Email inbox ──┘     ▲          │                     │ one transaction:
                     │          │                     │ inbound_event + contact + lead
                     │          │                     │ + audit_event + job
                     │          │                     ▼
                     │          │               PostgreSQL (all state, job queue, audit, AI telemetry)
                     │          │                     ▲ SKIP LOCKED
                     │          │                     │
                     │          │               "worker" process
                     │          │                 analyze_lead ─► Claude (structured output)
                     │          │                 draft_reply  ─► Claude (+ read-only tools)
                     │          │                 deliver_message ─► DeliveryAdapter
                     │          │                 follow-ups
                     │          └──────────────────────│─────────────────────────────────┘
                     │                                 │ signed dispatch request
                     └──── n8n sends via Gmail, signed callback to /v1/messages/{id}/delivery
```

Processes: `caddy`, `api`, `worker`, `postgres`, `n8n`. `api` and `worker` share one image with different entrypoints.

Full component responsibilities: [architecture.md](architecture.md).

| Component | Owns | Never does |
|---|---|---|
| FastAPI `api` | HTTP contract, auth, RBAC, validation, idempotency, rate limits, enqueueing jobs, approvals, metrics queries, serving the SPA | Call the LLM inside a request. Keep state in memory. |
| `worker` | Running jobs: analysis, drafting, delivery dispatch, follow-ups, retries, dead-lettering | Accept external traffic. |
| PostgreSQL | All state, the job queue, audit log, AI telemetry | Business logic beyond constraints. |
| Domain layer (pure Python) | State transitions, scoring, routing, missing-field checks, draft policy checks | Any I/O. |
| Claude | Extraction with evidence quotes, semantic classification, summarizing, drafting | Choose routes or scores, approve, or send. It has no side-effect tools. |
| n8n | Intake adapters, reviewer notifications (email or Slack), email delivery via Gmail, delivery callback | Store lead state, make decisions, hold business rules, retry sends. |
| React SPA | Reviewer UI: lead list, timeline, approval queue, review queue, metrics | Business logic. |

---

## 5. Data Model

```text
contacts 1───* leads 1───* lead_analyses *───1 ai_calls
                  │  1───* workflow_runs 1───* jobs
                  │                      1───* ai_calls
                  │  1───* messages 1───* approvals *───1 users
                  │  1───* follow_ups 0..1───1 messages
                  │  1───* audit_events
inbound_events *───0..1 leads
users 1───* sessions            api_keys (scoped, hashed)
```

| Table | Key columns | Notes |
|---|---|---|
| `inbound_events` | id, source, external_event_id, idempotency_key, payload_jsonb (nullable), payload_sha256, signature_valid, received_at, payload_purged_at, lead_id, status | UNIQUE(source, external_event_id). Payload is purged after `RAW_EVENT_RETENTION_DAYS`; the row and hash stay so dedupe keeps working. |
| `contacts` | id, email_normalized UNIQUE, name, phone_e164, company, created_at | Business dedupe point. |
| `leads` | id (UUIDv7), contact_id, source, raw_message, status, review_reason, resume_status, score, score_band, score_version, service_type, urgency, current_analysis_id, redraft_count, created_at, updated_at, version | `status` changes only through the lifecycle module. `version` for optimistic locking. |
| `lead_analyses` | id, lead_id, ai_call_id, schema_version, extracted_jsonb, evidence_ok, missing_fields[], created_at | Re-analysis adds a row. |
| `workflow_runs` | id, lead_id, trigger, status, started_at, finished_at, error | The workflow execution ID in every log line. |
| `jobs` | id, workflow_run_id, type, payload_jsonb, status (queued/running/succeeded/failed/dead), attempts, max_attempts, run_at, locked_until, last_error, dedupe_key UNIQUE | The queue. `dedupe_key` blocks duplicate enqueue. |
| `ai_calls` | id, workflow_run_id, lead_id, purpose, provider, model, prompt_name, prompt_version, prompt_hash, input_tokens, output_tokens, cost_usd (numeric), price_table_version, latency_ms, attempt, outcome (ok/invalid_output/refused/timeout/error), validation_errors_jsonb, raw_output (nullable), raw_output_purged_at, request_id | AI telemetry. `raw_output` is kept only for `invalid_output` calls, pending open question 1, and follows the raw-data retention policy. |
| `messages` | id, lead_id, kind (first_touch/info_request/follow_up), channel (email), subject, body, status, ai_call_id, policy_violations_jsonb, dispatch_attempt, dispatched_at, provider_message_id, sent_at | Status values in [state-machine.md](state-machine.md). |
| `approvals` | id, message_id, reviewer_id, decision (approved/rejected), edited_body, edit_distance, reason, decided_at | |
| `follow_ups` | id, lead_id, step, due_at, status (scheduled/paused/drafted/sent/skipped/cancelled), message_id | `skipped` = reviewer rejected that step's message. |
| `audit_events` | id, lead_id (nullable), actor_type (system/user/api_key/ai), actor_id, event_type, data_jsonb, request_id, workflow_run_id, created_at | Append-only. Lead timeline and security log. |
| `users` | id, email, password_hash (argon2id), role (admin/reviewer/viewer), is_active | |
| `sessions` | id, user_id, token_hash, expires_at, revoked_at | |
| `api_keys` | id, name, key_prefix, key_hash, scopes[], last_used_at, revoked_at | |

All timestamps are `timestamptz` in UTC. Business-hours math uses `America/New_York`.

---

## 6. API (v1, planned)

All under `/v1`. One error shape: `{"error": {"code", "message", "request_id"}}`.

| Method | Path | Auth / role | Purpose |
|---|---|---|---|
| POST | `/webhooks/leads/{source}` | HMAC signature + timestamp | Third-party intake. Dedupe on `(source, external_event_id)`. `202 {lead_id, status, duplicate}` |
| POST | `/leads` | API key `leads:write` | Direct intake. `Idempotency-Key` header required. |
| GET | `/leads` | viewer+ | Cursor-paginated list, filter by status and band |
| GET | `/leads/{id}` | viewer+ | Lead, current analysis, messages, follow-ups |
| GET | `/leads/{id}/timeline` | viewer+ | Audit events and AI calls in order |
| POST | `/leads/{id}/triage` | reviewer+ | Resolve a lead review: `qualify` / `disqualify` / `spam` / `close` + reason |
| POST | `/leads/{id}/outcome` | reviewer+ | `replied` / `won` / `lost` |
| POST | `/leads/{id}/reprocess` | admin | Start a new workflow run |
| GET | `/approvals?status=pending` | reviewer+ | Approval queue |
| POST | `/messages/{id}/approve` | reviewer+ | Optional `edited_body`. Edits re-run policy checks. |
| POST | `/messages/{id}/reject` | reviewer+ | `reason`, `redraft: bool` (max 2; `422` for follow-ups, which are templates) |
| POST | `/messages/{id}/resolve-delivery` | reviewer+ | For `delivery_unknown`: `confirmed_sent` / `resend` / `abandon`. For `failed`: `resend` / `abandon`. Reason required. |
| POST | `/messages/{id}/delivery` | API key `delivery:callback` + HMAC | n8n reports `sent` / `failed` for a specific `dispatch_attempt`. Idempotent. |
| GET | `/workflow-runs/{id}` | viewer+ | Jobs and AI calls for a run |
| GET | `/metrics/summary` | viewer+ | Aggregates from telemetry tables |
| GET | `/jobs?status=dead` | admin | Dead-letter queue |
| POST | `/jobs/{id}/retry` | admin | Requeue a dead job. Not allowed for delivery jobs (see section 9). |
| POST | `/auth/login`, `/auth/logout`; GET `/auth/me` | | Session auth |
| POST, DELETE | `/api-keys` | admin | Create (shown once), revoke |
| GET | `/healthz`, `/readyz` | public | Liveness, DB readiness |

**Endpoint rules:**

- `/leads/{id}/triage` works on leads in NEEDS_REVIEW (non-delivery reasons), SPAM, or DISQUALIFIED.
- `/leads/{id}/reprocess` works on NEEDS_REVIEW, SPAM, or DISQUALIFIED, and is refused once any message for the lead has been dispatched.
- Users and the first API key are created with CLI commands run by the operator on the server (`leadops users create`, `leadops api-keys create`). There is no user-management endpoint in v1.

**Endpoint milestones:** M1 health/ready; M2 intake and webhook (plus the CLI key command); M6 auth, lead read endpoints, approvals, triage, reprocess, workflow runs, dead-letter jobs, `/api-keys`, the users CLI; M7 resolve-delivery, delivery callback, outcome; M8 `/metrics/summary`. Before M6, leads reaching NEEDS_REVIEW wait there; this only happens with synthetic data in development.

**Outbound signed requests from the system to n8n:**

- Notifications: `lead.needs_review`, `message.pending_approval`. IDs and a dashboard link only, no lead PII.
- Delivery: `message.dispatch`, sent only by the `deliver_message` job, never by the approve endpoint directly.

---

## 7. Lead Lifecycle (summary)

Full table, guards, and per-reason actions: [state-machine.md](state-machine.md).

```text
RECEIVED ─► ANALYZING ─► SPAM | DISQUALIFIED | NEEDS_REVIEW | QUALIFIED
QUALIFIED ─► DRAFTING ─► AWAITING_APPROVAL ─► APPROVED ─► CONTACTED
CONTACTED ─► REPLIED | CLOSED_WON | CLOSED_LOST | CLOSED_NO_RESPONSE
Any failure or ambiguity ─► NEEDS_REVIEW (with review_reason) ─► human action
```

- Lead status tracks the lead. Message status tracks each message. Follow-ups change message status only; the lead stays CONTACTED.
- NEEDS_REVIEW stores `review_reason` and `resume_status`, so a human-hold always knows where it came from.
- "Missing information" is not a state. Missing fields switch the first draft to `info_request` mode.

**Routing rules** (ordered, deterministic, thresholds in versioned `config/routing.yaml`):

1. `spam_likely` signal AND no valid contact method → SPAM
2. Escalation → NEEDS_REVIEW (`escalation`) if any of: LLM flag `injection_attempt` or `complaint` (covers complaints, legal threats, refund requests); a match on the deterministic keyword list in `config/routing.yaml`; or the contact already has a CLOSED_WON lead (existing client, checked in the database)
3. Extraction invalid after one repair retry → NEEDS_REVIEW (`analysis_failed`); evidence check failed on a key field → NEEDS_REVIEW (`evidence_failed`)
4. Location evidence-verified AND outside the service area list AND every requested service is marked on-site in the service catalog → DISQUALIFIED. An unverified or missing location never disqualifies.
5. Otherwise → QUALIFIED

**Scoring:** deterministic points from extracted features (service fit, service area, timeline, budget signal, contact completeness, decision maker). 0 to 100, bands hot/warm/cold, weights in versioned `config/scoring.yaml`, `score_version` stored on the lead.

---

## 8. AI Architecture

Two LLM calls per lead in the normal path.

| Call | Model tier | Input | Output |
|---|---|---|---|
| `analyze_lead` | Haiku-tier, `ANALYSIS_MODEL` | Lead message, delimited as untrusted data | `LeadExtraction`: contact fields, business info, `service_types[]` (enum), timeline, budget signal, urgency, decision-maker, flags (`spam_likely`, `complaint`, `injection_attempt`), one evidence quote per extracted field |
| `draft_reply` | Sonnet-tier, `DRAFT_MODEL` | Validated extraction (not the raw message), mode, reviewer feedback on redraft | Subject and body |

Each call is split into separate modules: versioned prompt template → provider call (Protocol) → parse → Pydantic validation → evidence verification (each quote must appear in the source text after normalization; a failing field is nulled and flagged) → business logic.

**Failures:** invalid output gets one repair retry with the validation errors attached. Timeouts, 429, and 5xx retry through the job queue with exponential backoff and jitter. Exhausted retries end in NEEDS_REVIEW.

**Tool use (drafting only):** read-only tools, at most 3 turns.

- `get_service_details(service_type)`: from the service catalog file
- `get_open_call_slots(days)`: from business hours (Mon to Sat, 8am to 7pm ET) minus booked slots

If the eval shows the static catalog works just as well in the prompt, ADR-0006 is amended and only the dynamic slot tool stays.

**Draft policy checks** (deterministic, run on AI drafts and on reviewer edits):

- No prices or dollar amounts
- The call to action is booking a call
- No URLs outside an allowlist
- No guarantees ("guaranteed", "#1 on Google")
- No em dashes; word limit
- Greeting name matches the extracted first name

A failing AI draft is regenerated once with the violations listed. If it still fails, the violations are shown on the approval card. A reviewer edit that fails is rejected with `422` and the list of violations.

**Prompts** live in `prompts/{name}/v{n}.md`. Every `ai_calls` row stores prompt name, version, and hash.

**Cost guard:** daily LLM spend cap and a per-lead limit on LLM calls. Cost is computed with `Decimal` from a versioned price table. Exact behavior when the cap is hit is decided in M4.

---

## 9. Outbound Delivery Guarantee

The system does **not** claim exactly-once email delivery. Gmail offers no idempotency key, and a network timeout can hide whether a send happened. No system can promise exactly-once in that situation.

What the system guarantees:

1. **Duplicate internal delivery jobs are prevented.** One delivery job per `(message_id, dispatch_attempt)` via `jobs.dedupe_key`. A worker claims the message with a compare-and-set update (`approved` → `dispatching`); only one worker can win.
2. **An ambiguous or unknown delivery result is never retried automatically.** Once the dispatch request to n8n may have been received, any outcome other than a clean result is ambiguous: timeout, dropped connection, 5xx, malformed response, or no callback within `DELIVERY_CALLBACK_TIMEOUT_MINUTES`.
3. **Ambiguous delivery moves the lead to NEEDS_REVIEW** (`review_reason = delivery_unknown`, message status `delivery_unknown`).
4. **A human decides the next action:** `confirmed_sent` (checked the Gmail Sent folder), `resend` (new dispatch attempt, audited, deliberate), or `abandon`.

The only automatic retry allowed is a failure that proves the request never left: DNS failure, connection refused, or TLS handshake failure. Dead delivery jobs cannot be requeued through `/jobs/{id}/retry`; they go through `resolve-delivery`.

A late signed `sent` callback for the **current** `dispatch_attempt` of a message in `delivery_unknown` records the send and resolves the review automatically. That is reconciliation with confirmed evidence, not a retry. A callback for an older attempt, or for a message already `cancelled`, changes no state; it is written to the audit log and shown as a warning on the lead timeline.

If a delivery job exhausts its safe retries (the request never left), the message becomes `failed` and the lead moves to NEEDS_REVIEW (`delivery_failed`). No delivery job is ever left dead without a review item.

A delivery job reclaimed after a worker crash finds the message already `dispatching` and moves it to `delivery_unknown`. It never re-sends.

**n8n requirement:** the delivery workflow must have "Retry On Fail" turned off on the send node, so n8n cannot create duplicates behind the system's back.

Short form for the README and interviews: **duplicate-outbound protection, not exactly-once delivery.** Details: [ADR-0005](adr/0005-outbound-delivery-ambiguity.md).

---

## 10. PII and Data Retention

Leads are personal data: names, emails, phone numbers, and free text.

| Data | Contains PII | Policy |
|---|---|---|
| Repository, eval datasets, demo seed data | Must not | **Synthetic data only.** No real lead, client, or prospect data is ever committed or loaded into the public demo. |
| `ai_calls.raw_output` (only if open question 1 is approved) | Yes | Same retention and purge as raw inbound payloads. |
| `inbound_events.payload_jsonb` | Yes (raw, unvalidated) | Kept for debugging and replay. Production deployments purge it after `RAW_EVENT_RETENTION_DAYS` (default `30`). Purge sets the payload to NULL and stamps `payload_purged_at`; source, event ID, and `payload_sha256` stay so idempotency keeps working. |
| `leads`, `contacts`, `messages`, `lead_analyses` | Yes | Operational business records. No automatic deletion in v1. The operator's own retention policy applies. |
| Logs | Must not | Email and phone masked by a log processor. Message bodies are not logged. |
| n8n notifications | Must not | IDs and dashboard links only. |
| n8n workflow exports in the repo | Must not | Credentials and real addresses stripped before commit. |
| Database backups | Yes | Retention set by the operator, documented in the runbook (M9). |

`RAW_EVENT_RETENTION_DAYS` is defined in config from M2. The scheduled purge job (covering `inbound_events.payload_jsonb` and `ai_calls.raw_output`) is built in **M9**, alongside backups and the production runbook, using the job queue from M3. Until M9 the purge does not exist and the docs say so.

---

## 11. Security (summary)

Full threat table: [security.md](security.md).

Webhook HMAC with a timestamp window; idempotency keys; rate limits and a 32 KB body limit; prompt-injection handling through architecture rather than prompt wording; RBAC on every route; argon2id passwords; opaque revocable sessions in httpOnly SameSite=Strict cookies; hashed, scoped, revocable API keys; secrets only in environment; `gitleaks` in CI; delivery sink in the demo; daily LLM budget; append-only audit log; Postgres only on the internal network; the app's database role has no DDL rights and migrations run with a separate role.

---

## 12. Observability

- Structured JSON logs (structlog) with `request_id`, `lead_id`, `workflow_run_id`, `job_id`, `ai_call_id`.
- `X-Request-ID` accepted, propagated to n8n, returned in responses and error bodies.
- AI telemetry in `ai_calls`. Workflow telemetry in `jobs` and `workflow_runs`.
- `/metrics/summary` is SQL over those tables: intake-to-draft latency p50/p95, cost per lead, schema-valid-first-try rate, escalation rate, approval-without-edit rate, delivery outcomes, dead-letter count.
- No Prometheus, Grafana, or OpenTelemetry in v1.

---

## 13. Testing

| Layer | Covers |
|---|---|
| Unit, domain | Every legal and illegal transition, scoring, routing, missing fields, policy checks, normalization, HMAC verification, backoff math |
| Unit, AI boundary | Prompt rendering; malformed, partial, and extra-field JSON; evidence verification; repair retry |
| Integration (real PostgreSQL) | 10 concurrent identical webhooks create exactly 1 lead; 2 workers and 1 job run it once; retry to dead letter; full pipeline with a fake LLM; delivery ambiguity goes to NEEDS_REVIEW and is not retried; follow-up cancellation; RBAC matrix |
| Contract | Delivery callback, outbound signatures |
| Frontend | Typecheck, build, a few component tests |

No real LLM calls in CI. Real calls run only in `make eval`.

---

## 14. Evaluation

- Dataset: 60 to 100 synthetic leads. Leads may be LLM-drafted for variety; every label is set and checked by hand following `evals/LABELING_GUIDE.md`.
- Buckets: clean, vague, missing info, multi-service, out of area, spam, prompt injection, complaint or existing client, very long, non-English, budget mismatch.
- Metrics: field extraction accuracy, service classification accuracy and confusion matrix, end-to-end route accuracy, escalation recall (headline) and precision, injection handling, schema-valid-first-try rate, draft policy pass rate, LLM-judge draft score (judge checked against hand grades), latency p50/p95, cost per lead.
- Results committed per prompt version. Unmeasured metrics are **TBD**.

---

## 15. Deployment

One VPS (about 2 vCPU, 4 GB RAM) running Docker Compose: `caddy`, `api`, `worker`, `postgres`, `n8n`. Nightly `pg_dump` to object storage with a tested restore. CD on version tags: build, push to GHCR, SSH deploy, migrate, restart, smoke test. Public demo: synthetic data, viewer and reviewer demo accounts, `DELIVERY_MODE=sink`, nightly reset.

---

## 16. Configuration (planned)

| Variable | Purpose | Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection | none |
| `ANTHROPIC_API_KEY` | LLM provider key | none |
| `ANALYSIS_MODEL`, `DRAFT_MODEL` | Model IDs per tier | none |
| `LLM_DAILY_BUDGET_USD` | Spend cap | set per deployment |
| `DELIVERY_MODE` | `sink` or `n8n` | `sink` |
| `DELIVERY_CALLBACK_TIMEOUT_MINUTES` | After this, no callback means `delivery_unknown` | set in M7 |
| `N8N_DISPATCH_URL`, `N8N_SIGNING_SECRET` | Outbound to n8n | none |
| `WEBHOOK_SECRETS` | Per-source inbound HMAC secrets | none |
| `RAW_EVENT_RETENTION_DAYS` | Raw payload purge age | `30` |
| `SESSION_TTL_HOURS` | Session lifetime | set in M6 |

No secret has a default. The app refuses to start if a required secret is missing.

---

## 17. Milestones

Each milestone ships as one or two PRs with CI green, tests, and docs updated.

| M | Deliverable | Status |
|---|---|---|
| M0 | Design, ADRs, architecture/state-machine/security docs, early README | Done (docs only) |
| M1 | Foundation: uv project, app factory, config, structlog with request IDs, health/ready, Compose (api + postgres), Alembic baseline, CI (ruff, mypy, pytest + Postgres, gitleaks), Dockerfile, LICENSE, `.gitignore`, `.env.example` | Planned |
| M2 | Data model and intake: core tables, normalization, contact dedupe, `/leads` and signed webhook, idempotency, API-key auth, audit events, transactional enqueue, concurrency test | Planned |
| M3 | Job runner: queue, worker, backoff with jitter, dead letter, workflow runs, lifecycle state machine | Planned |
| M4 | AI analysis: provider Protocol, Claude provider, versioned prompts, extraction schema, validation and repair, evidence check, scoring, routing, telemetry, budget guard | Planned |
| M5 | Eval v1: labeled dataset, harness, metrics, committed results | Planned |
| M6 | Drafting and approvals: draft call, read-only tools, policy checks, approval endpoints, users, sessions, RBAC | Planned |
| M7 | Delivery and follow-ups: DeliveryAdapter (sink and n8n), dispatch, callback, ambiguity handling, follow-ups, n8n workflows | Planned |
| M8 | Dashboard: Vite/React/TS, generated types, login, leads, timeline, approval and review queues, metrics | Planned |
| M9 | Deploy and ops: production Compose, Caddy, backups, raw-payload purge job, CD, seeded demo | Planned |
| M10 | Measure and ship: eval v2, real latency and cost numbers, README, demo video, case study, `v1.0.0` | Planned |

---

## 18. Later (not v1)

In priority order: earned autonomy (auto-send for one category behind eval thresholds), inbound reply detection, MCP server for reviewer actions, OpenTelemetry, second provider with comparison eval, website enrichment with SSRF protection, CRM sync.

---

## 19. Open Questions

| # | Question | Default if no answer |
|---|---|---|
| 1 | Store raw LLM output for `invalid_output` calls, for debugging? | Yes, in `ai_calls.raw_output`, purged on the same schedule as raw events (`RAW_EVENT_RETENTION_DAYS`). Decide by M4. |
| 2 | Can an admin override a policy-check failure on a reviewer edit? | No override in v1. |
| 3 | Follow-up cadence (days between steps, number of steps) | 2 steps, at 2 and 5 business days. Decide in M7. |

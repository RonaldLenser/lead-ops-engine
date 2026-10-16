# Architecture

Status: approved design (M0). M1 implemented the foundation (app factory, config, logging, health probes, database roles); the rest is planned.

Source: [DESIGN.md](DESIGN.md). Decisions: [ADRs](adr/README.md).

---

## 1. System Context

```text
              ┌───────────────────────────── Lead Ops Engine ─────────────────────────────┐
 Lead ──form──► n8n ──API key──► api ──► PostgreSQL ◄── worker ──► Claude API           │
              │  ▲                 ▲                      │                              │
              │  │                 │ session cookie       │ signed dispatch              │
              │  │              Reviewer (SPA)            ▼                              │
              │  └──────── signed callback ◄──── n8n ──► Gmail ──► Lead's inbox         │
              └───────────────────────────────────────────────────────────────────────────┘
```

External parties:

| Party | Talks to | How |
|---|---|---|
| Lead (prospect) | Website form, form tools, email | Never talks to the API directly |
| n8n | `api` | Intake: scoped API key. Callback: scoped API key + HMAC. System to n8n: HMAC. |
| Reviewer | SPA, served by `api` | Session cookie, role `reviewer` or `admin` |
| Claude API | Called by `worker` only | Provider SDK over HTTPS |
| Gmail | Called by n8n only | n8n Gmail credentials, held in n8n, never in this repo |

---

## 2. Processes

| Process | Role | Scales by | State |
|---|---|---|---|
| `caddy` | TLS termination, reverse proxy | n/a | none |
| `api` | HTTP API, auth, validation, enqueue, serves SPA | more replicas (stateless) | none in memory |
| `worker` | Runs jobs from the queue | more replicas (SKIP LOCKED makes this safe) | none in memory |
| `postgres` | All state, queue, audit, telemetry | vertical | yes |
| `n8n` | Integration edge | n/a | its own workflow config and execution logs only |

`api` and `worker` are built from one image with different entrypoints.

---

## 3. Responsibility Boundaries

| Concern | Owner | Not owned by |
|---|---|---|
| Lead and message status | PostgreSQL via domain lifecycle module | n8n, LLM, SPA |
| What happens next for a lead | Deterministic routing rules | LLM, n8n |
| Qualification score | Deterministic scoring function | LLM |
| Missing-field detection | Deterministic rules per service type | LLM |
| Reading free text, classifying, drafting | Claude | Business rules |
| Whether a message may be sent | Human approval, recorded in `approvals` | LLM, n8n, any automatic path |
| Talking to Gmail, Slack (notifications), form tools | n8n | API, worker |
| Retrying work | Job queue in PostgreSQL | n8n (send-node retries must be off) |

---

## 4. Main Data Flow (happy path)

```text
 1. n8n receives a form submission
 2. n8n ─POST /v1/leads (API key, Idempotency-Key)─► api
 3. api: validate, normalize, then ONE transaction:
        insert inbound_event (dedupe on key) ─► upsert contact ─► insert lead (RECEIVED)
        ─► insert audit_event ─► insert job analyze_lead
 4. api ─202 {lead_id}─► n8n                       (milliseconds, no LLM call)
 5. worker claims analyze_lead (SKIP LOCKED), lead ─► ANALYZING
 6. worker ─► Claude analyze_lead ─► parse ─► validate ─► verify evidence
        ─► store ai_call + lead_analysis
 7. domain: missing fields, score, routing rules ─► lead QUALIFIED; enqueue draft_reply
 8. worker ─► Claude draft_reply (read-only tools) ─► policy checks
        ─► message pending_approval, lead AWAITING_APPROVAL
 9. worker ─signed message.pending_approval (IDs only)─► n8n ─► reviewer notified
10. Reviewer approves in SPA ─POST /v1/messages/{id}/approve─► api
        ─► approval row, message approved, lead APPROVED, enqueue deliver_message
11. worker claims deliver_message, compare-and-set message approved ─► dispatching
12. worker ─signed message.dispatch─► n8n ─► Gmail send
13. n8n ─signed POST /v1/messages/{id}/delivery {sent}─► api
        ─► message sent, lead CONTACTED, follow-ups scheduled
```

With `DELIVERY_MODE=sink` (demo and local), step 12 writes to a sink instead of calling n8n, and step 13 is replaced by an immediate confirmed result. No email leaves the system.

---

## 5. Failure Paths

| Failure | Where | Handling | Ends in |
|---|---|---|---|
| Duplicate webhook or retried form post | Step 3 | UNIQUE constraint on inbound event; return the original `lead_id` with `duplicate: true` | No new lead |
| Same person submits again | Step 3 | Contact matched by normalized email; a new lead row is created for the new inquiry | New lead, same contact |
| Claude timeout, 429, 5xx | Steps 6, 8 | Job retry with exponential backoff and jitter | Success, or NEEDS_REVIEW after max attempts |
| Invalid structured output | Steps 6, 8 | One repair retry with validation errors | Success, or NEEDS_REVIEW |
| Evidence quote not in source | Step 6 | Field nulled and flagged | NEEDS_REVIEW if it is a key field |
| Draft breaks policy | Step 8 | One regeneration with violations listed | Violations shown on approval card |
| Worker crashes mid-job | Analysis, drafting, follow-up jobs | Lock expires (`locked_until`), another worker reclaims | Job re-runs; handlers are idempotent |
| Worker crashes during delivery | `deliver_message` | Reclaiming worker sees message already `dispatching` | NEEDS_REVIEW (`delivery_unknown`), never re-sent |
| Dispatch never left (DNS, refused, TLS) | Step 12 | Automatic retry, same dispatch attempt | Sent, or `failed` and NEEDS_REVIEW (`delivery_failed`) when retries run out |
| Dispatch outcome unclear | Steps 12, 13 | **No automatic retry** | NEEDS_REVIEW (`delivery_unknown`) |
| Provider reports failure | Step 13 | No automatic retry in v1 | NEEDS_REVIEW (`delivery_failed`) |
| Job exceeds max attempts | Any | Status `dead`, visible to admin | Dead-letter queue |

Details on delivery: [DESIGN.md section 9](DESIGN.md#9-outbound-delivery-guarantee) and [ADR-0005](adr/0005-outbound-delivery-ambiguity.md).

---

## 6. Trust Boundaries

Every arrow that crosses a boundary is authenticated and its payload is schema-validated.

| Boundary | Authentication | Validation |
|---|---|---|
| n8n → api (intake) | Scoped API key `leads:write` | Pydantic request model, body size limit |
| Form tool → api (webhook) | HMAC-SHA256 over `timestamp.body`, 5-minute window | Pydantic model per source |
| worker → n8n | HMAC signature | n8n checks signature before acting |
| n8n → api (callback) | API key `delivery:callback` + HMAC | Pydantic model; message must be in an expected status |
| SPA → api | Session cookie + role check | Pydantic models |
| worker → Claude | Provider API key from env | Response parsed and validated before use |
| Lead text → Claude | Untrusted data, delimited | Output schema-only; no side-effect tools |

---

## 7. Planned Code Layout

Created milestone by milestone. A folder appears only when real code goes in it.

```text
lead-ops-engine/
├── backend/
│   ├── pyproject.toml, uv.lock, alembic.ini, Dockerfile, .env.example
│   ├── migrations/
│   ├── config/            routing.yaml, scoring.yaml, services.yaml, prices.yaml
│   ├── src/leadops/
│   │   ├── main.py, config.py, logging_config.py, errors.py
│   │   ├── api/           routes/, deps.py, auth.py, middleware.py, rate_limit.py
│   │   ├── domain/        lifecycle.py, scoring.py, routing.py, policies.py, normalization.py  (no I/O)
│   │   ├── services/      intake.py, analysis.py, drafting.py, approvals.py, delivery.py, followups.py
│   │   ├── ai/            provider.py, anthropic_provider.py, schemas.py, evidence.py, tools.py, pricing.py
│   │   │   └── prompts/   analyze_lead/v1.md, draft_reply/v1.md
│   │   ├── jobs/          queue.py, worker.py, handlers.py, retry.py
│   │   ├── integrations/  signing.py, n8n.py
│   │   ├── db/            models.py, session.py, repositories/
│   │   └── schemas/       API request and response models
│   └── tests/             unit/, integration/, fakes.py, conftest.py
├── frontend/              Vite + React + TypeScript, src/api/schema.d.ts (generated)
├── evals/                 datasets/, LABELING_GUIDE.md, run.py, metrics.py, judge.py, results/
├── n8n/                   workflows/*.json (credential-free), README.md
├── infra/                 docker-compose.yml, postgres/init/01-roles.sql, docker-compose.prod.yml, Caddyfile, backup.sh
└── docs/                  DESIGN.md, architecture.md, state-machine.md, security.md, adr/
```

Layering rule: `api` and `jobs` call `services`; `services` call `domain`, `ai`, `db`, and `integrations`; `domain` imports nothing from the other layers.

---

## 8. Deployment Topology

```text
Internet ─► VPS :443 ─► caddy ─► api:8000
                                  │
              worker ─────────────┤
              n8n:5678 (behind caddy, auth required)
              postgres:5432 (internal network only, never exposed)
```

Nightly `pg_dump` to object storage. Releases deploy on version tags through GitHub Actions. See [ADR-0010](adr/0010-vps-docker-compose-deployment.md).

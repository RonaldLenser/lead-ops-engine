# Lead Ops Engine

**AI lead qualification with human approval.**

Lead Ops Engine takes inbound business leads from intake to a human-approved first reply: an LLM reads and drafts, deterministic code makes every decision, and nothing is sent without a reviewer's approval.

> **Status: M1 (foundation) complete.** The service runs, connects to PostgreSQL, checks its own readiness, and is covered by CI.
> Lead intake, AI analysis, approvals, and delivery are **not built yet**. Everything outside the "Done" rows of the roadmap describes the planned v1.

---

## The Problem

Small service businesses get leads from website forms, form tools, and email. Someone has to read each one, figure out what the person wants, decide whether it is a fit, and write back. By hand this is slow and inconsistent, and replies often go out hours or days late.

Handing it all to an LLM creates new problems: invented details, scores that mean nothing, prompt injection through the lead's own message, emails sent with no human check, and no record of why anything happened.

This project automates the reading and drafting while keeping decisions testable, every outbound message approved by a person, and every step recorded.

The example business is Ron Lenser Digital, a one-person software and automation shop. Its real policies drive the rules (for example: prices are quoted only after a call, so drafts never include prices). **All data in this repository is synthetic.**

---

## How It Will Work

```text
 Form / email ─► n8n ─► FastAPI ─► PostgreSQL (all state + job queue)
                                        ▲
                                     worker ─► Claude: extract facts with evidence
                                        │      code: verify, score, route
                                        │      Claude: draft reply
                                        │      code: policy checks
                                        ▼
                              Reviewer approves in dashboard
                                        │
                                worker ─► n8n ─► Gmail
```

Core ideas:

1. **The LLM extracts, code decides.** Claude turns free text into validated, evidence-backed fields. Scoring, routing, missing-information checks, and draft policy checks are deterministic code.
2. **100% human approval for outbound messages in v1.** No email leaves without a reviewer.
3. **FastAPI and PostgreSQL own all state.** n8n only connects to outside apps.
4. **Duplicate-outbound protection, not exactly-once.** Duplicate delivery jobs are prevented, and an unclear send result is never retried automatically; it goes to a human.
5. **Nothing gets lost.** Every failure ends in a review queue or a dead-letter queue a person can see.

Details: [Design](docs/DESIGN.md) · [Architecture](docs/architecture.md) · [State machines](docs/state-machine.md) · [Security](docs/security.md) · [Decision records](docs/adr/README.md)

---

## What Exists Today (M1)

- FastAPI app factory with typed settings that refuse to start on missing or unsafe configuration
- Structured JSON logging (app and library logs) with a request ID on every line and response
- `/healthz` (liveness) and `/readyz` (database reachable and migrations current)
- Two PostgreSQL roles: the app can read and write rows but cannot change the schema; migrations run as a separate owner role
- Alembic baseline migration, Dockerfile (non-root), Docker Compose stack
- CI: ruff, mypy (strict), pytest against a real PostgreSQL, gitleaks, Docker build and Compose smoke test

---

## Run It Locally

Requirements: Docker, and [uv](https://docs.astral.sh/uv/) for running tests outside Docker.

```bash
# Whole stack: database, migrations, API on http://localhost:8000
docker compose -f infra/docker-compose.yml up --build

curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
```

Tests (unit tests need nothing; integration tests use the Compose database):

```bash
docker compose -f infra/docker-compose.yml up -d db
cd backend
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests migrations
```

Git hooks (gitleaks, ruff, whitespace checks), from the repository root:

```bash
uv run --project backend pre-commit install
```

---

## Planned Stack

| Layer | Choice |
|---|---|
| API | Python 3.12, FastAPI, Pydantic v2 |
| Database | PostgreSQL, SQLAlchemy 2.0, Alembic |
| Background work | PostgreSQL job queue (`SKIP LOCKED`) |
| AI | Claude (Haiku-tier for extraction, Sonnet-tier for drafting) behind a provider Protocol |
| Integrations | n8n (intake, notifications, Gmail delivery) |
| Dashboard | Vite, React, TypeScript, types generated from OpenAPI |
| Infrastructure | Docker Compose on a VPS, Caddy, GitHub Actions |
| Quality | pytest, ruff, mypy, gitleaks, an evaluation suite |

---

## Roadmap

| Milestone | Scope | Status |
|---|---|---|
| M0 | Architecture, decision records, design docs | Done |
| M1 | Project foundation, CI, Docker, health checks, database roles | Done |
| M2 | Data model, lead intake, webhook signatures, idempotency | Planned |
| M3 | Job queue, worker, retries, lifecycle state machine | Planned |
| M4 | LLM extraction, evidence checks, scoring, routing, AI telemetry | Planned |
| M5 | Evaluation suite v1 | Planned |
| M6 | Drafting, policy checks, approvals, user auth and roles | Planned |
| M7 | Delivery, follow-ups, n8n workflows | Planned |
| M8 | Reviewer dashboard | Planned |
| M9 | Deployment, backups, data retention job | Planned |
| M10 | Measurements, documentation, demo | Planned |

---

## Metrics

**All performance and evaluation metrics are TBD until measured.** They will be produced by a reproducible evaluation run and published with the command that produced them.

| Metric | Value |
|---|---|
| Field extraction accuracy | TBD |
| Service classification accuracy | TBD |
| Escalation recall | TBD |
| Draft policy pass rate | TBD |
| Intake to draft-ready latency (p50 / p95) | TBD |
| Cost per lead | TBD |

---

## License

[MIT](LICENSE)

# Lead Ops Engine

**AI lead qualification with human approval.**

Lead Ops Engine takes inbound business leads from intake to a human-approved first reply: an LLM reads and drafts, deterministic code makes every decision, and nothing is sent without a reviewer's approval.

> **Status: Phase 0. Architecture approved, no application code yet.**
> Everything below describes the planned v1. Nothing here is implemented until the roadmap marks it done.

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
| M1 | Project foundation, CI, Docker, health checks | Planned |
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

To be added in M1 (MIT).

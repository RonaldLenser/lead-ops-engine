# ADR-0001: FastAPI + PostgreSQL own workflow state; n8n is the integration edge

- **Status:** Accepted
- **Date:** 2026-10-15

## Context

The system runs a multi-step workflow per lead: intake, analysis, routing, drafting, approval, delivery, follow-up. Something has to own the state of that workflow: which step a lead is on, what was decided, and why.

Two tools could own it. n8n is built for multi-step workflows and has a visual editor and hundreds of integrations. FastAPI with PostgreSQL is ordinary application code.

The project also has to work as a portfolio piece. Reviewers read code on GitHub, run tests, and ask how failures are handled.

## Decision

FastAPI and PostgreSQL own all application and workflow state. Every status change is a row in PostgreSQL, made through one lifecycle module, in the same transaction as its audit event.

n8n is an integration edge only. It:

- receives submissions from form tools and email and forwards them to `/v1/leads`
- sends reviewer notifications (IDs and links only)
- sends approved emails through Gmail when asked by a signed `message.dispatch` request, then reports the result to a signed callback

n8n stores no lead state, makes no decisions, holds no business rules, and does not retry sends. The system runs end to end without n8n (`DELIVERY_MODE=sink`).

## Alternatives Considered

| Option | Why not |
|---|---|
| n8n owns the workflow, FastAPI is a thin data API | Business logic would live in exported JSON. It cannot be unit tested in CI, is hard to review in a diff, and splits state between n8n's execution store and PostgreSQL. |
| No n8n at all, call Gmail and form APIs directly from Python | Works, but loses a skill the target roles ask for, and every new channel becomes custom integration code. |
| Temporal or another workflow engine as owner | Strong guarantees, but a heavy extra system for one workflow and one operator. |

## Tradeoffs

- Gained: one source of truth, testable logic, readable diffs, transactional consistency between status and audit trail.
- Lost: n8n's visual view of the business flow. The state machine doc replaces it.
- Cost: every n8n interaction is a signed HTTP call that must be designed, documented, and tested as a contract.

## Consequences

- `domain/lifecycle.py` is the only place lead status can change.
- n8n workflows in the repo are small and credential-free, and are adapters, not logic.
- The n8n send node must have "Retry On Fail" disabled (see ADR-0005).
- Adding a new intake channel means an n8n workflow that posts to the existing API, with no backend change.

## Why This Fits This Project

The target roles (AI workflow and automation engineer, solutions and forward deployed engineer) use tools like n8n daily. What separates a strong candidate is knowing where low-code belongs and where it does not. This design shows that judgment directly: n8n connects to the outside world, the code owns correctness.

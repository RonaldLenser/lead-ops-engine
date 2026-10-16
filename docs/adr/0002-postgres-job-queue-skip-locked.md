# ADR-0002: PostgreSQL job queue using SKIP LOCKED

- **Status:** Accepted
- **Date:** 2026-10-15

## Context

LLM calls take seconds and fail sometimes. Webhook senders expect a fast response and retry when they do not get one. So analysis, drafting, and delivery must run in the background, with retries, backoff, and a place for jobs that keep failing.

A lead insert and its first job must be created together. If the lead is saved but the job is lost, the lead is stuck. If the job exists but the lead insert rolled back, the job points at nothing.

## Decision

Use a `jobs` table in PostgreSQL as the queue.

- Enqueue happens in the **same transaction** as the business write (lead insert, approval). Both commit or neither does.
- Workers claim work with `SELECT ... FOR UPDATE SKIP LOCKED`, set `locked_until`, and run the handler.
- Failures are retried with exponential backoff and jitter by setting `run_at` in the future.
- After `max_attempts`, the job becomes `dead` and appears in the admin dead-letter view.
- A UNIQUE `dedupe_key` prevents the same job from being enqueued twice.
- A crashed worker's lock expires and another worker reclaims the job, so handlers must be idempotent.

The queue is expected to be a small module (a few hundred lines at most) that we own and can explain.

## Alternatives Considered

| Option | Why not |
|---|---|
| Redis + Celery or RQ | A second stateful system to run and back up. Enqueue cannot share a transaction with the Postgres write, which creates the dual-write problem described above. |
| Temporal | Excellent durability, but a large system to operate for one workflow and one operator. |
| A Postgres queue library (for example procrastinate) | Reasonable. Rejected because the queue mechanics are a core interview topic for this project and should be visible code. Revisit if the hand-written queue grows past its scope. |
| FastAPI `BackgroundTasks` | Runs in the API process, is lost on restart, and has no retries or visibility. |

## Tradeoffs

- Gained: transactional enqueue, one database to run and back up, full visibility with SQL.
- Lost: raw throughput. A polled Postgres table is not a high-throughput message bus. The expected load (a small business's inbound leads) is far below where that matters; this is an expectation, not a measurement.
- Cost: we own the correctness of locking, retries, and lock expiry, so those need integration tests against a real Postgres.

## Consequences

- Integration tests must prove: two workers never run the same job at once; a crashed job is reclaimed; retries back off; exhausted jobs become `dead`.
- Delivery jobs are special: their retry rules follow ADR-0005, and dead delivery jobs cannot be requeued through the generic retry endpoint.
- If volume ever outgrows Postgres polling, `LISTEN/NOTIFY` is the first step before any new system.

## Why This Fits This Project

The workflow volume is small and correctness matters more than throughput. Showing that a second piece of infrastructure was not needed, and being able to explain SKIP LOCKED and the dual-write problem, is a stronger signal than adding Redis.

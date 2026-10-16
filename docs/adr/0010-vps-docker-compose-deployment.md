# ADR-0010: VPS + Docker Compose deployment

- **Status:** Accepted
- **Date:** 2026-10-15

## Context

The production system has five processes: `caddy`, `api`, `worker`, `postgres`, `n8n`.

- The `worker` polls the job queue and must stay running.
- `n8n` runs webhook triggers and polling triggers (for example the email inbox intake) and must stay running.
- The deployment should be cheap enough to keep online for months as a public demo, and simple enough for one person to operate.

The earlier portfolio project (Grounded) deploys to Google Cloud Run with a managed Postgres, a good fit for a stateless request/response app.

## Decision

Deploy to **one VPS (about 2 vCPU, 4 GB RAM) using Docker Compose**.

- `infra/docker-compose.prod.yml` runs all five services.
- **Caddy** terminates TLS with automatic certificates and proxies to `api` and the n8n editor (behind auth).
- **PostgreSQL** is reachable only on the internal Docker network.
- **Backups:** nightly `pg_dump` to object storage, with a restore tested at least once and written up in the runbook.
- **CD:** pushing a `v*` tag runs GitHub Actions: build images, push to GHCR, SSH to the VPS, run migrations, `docker compose up -d`, smoke test. The production environment is protected.
- The raw-payload purge job (DESIGN.md section 10) is added in the same milestone (M9).

## Alternatives Considered

| Option | Why not |
|---|---|
| Cloud Run (as in Grounded) | Scale-to-zero stops a polling worker and n8n's scheduler. Keeping instances always on removes the cost advantage and adds a managed database bill. |
| Railway, Render, or Fly.io | Workable, but costs grow per service and Postgres plus n8n plus worker adds up. Less transferable than plain Docker and Linux skills. |
| Kubernetes | Large operational overhead for five containers on one machine. No benefit at this scale. |
| n8n Cloud plus a managed backend | Splits the system across vendors and adds a monthly subscription. |

## Tradeoffs

- Gained: low fixed cost, all services in one place, a deployment anyone can reproduce from the repo, and a different deployment skill from Grounded.
- Lost: no automatic failover. One machine is a single point of failure.
- Cost: we own OS updates, disk space, backups, and monitoring. Documented in the runbook.

## Consequences

- The runbook (M9) covers deploy, rollback, restore, secret rotation, and disk checks.
- Health and readiness endpoints are used by the deploy smoke test.
- If the system ever needs high availability, the first step is moving Postgres to a managed service; the Compose layout makes that a config change.

## Why This Fits This Project

A small business would realistically run this on one server. Showing a clean Compose setup with TLS, backups, migrations in CD, and a tested restore is more credible than a complex platform the project does not need.

# ADR-0009: Vite React SPA with OpenAPI-generated TypeScript types

- **Status:** Accepted
- **Date:** 2026-10-15

## Context

Reviewers need a UI for the lead list, lead timeline, approval queue, review queue, and metrics. It sits behind a login, is used by a handful of people, and does not need search engine indexing.

The backend is Python. The frontend is TypeScript. Request and response shapes must stay in sync between them, or the UI breaks silently when the API changes.

## Decision

- **Vite + React + TypeScript**, built to static files.
- **Served by FastAPI from the same origin** in production. No separate frontend host.
- **Types generated from the API's OpenAPI schema** (for example with `openapi-typescript`) into `frontend/src/api/schema.d.ts`. The frontend imports only generated types for API data.
- CI regenerates the types and fails if the committed file differs from the generated one, so backend changes cannot silently break the UI contract.
- The UI holds no business logic. It shows state and calls endpoints.

## Alternatives Considered

| Option | Why not |
|---|---|
| Next.js | Server rendering, routing conventions, and a server runtime that duplicate what FastAPI already does. An internal admin tool behind login gains nothing from SSR. |
| Plain HTML and JavaScript (as in Grounded) | Simple, but would not show TypeScript, which the target roles ask for, and gives no type safety across the API boundary. |
| Hand-written TypeScript types | They drift from the backend over time. Generation removes that class of bug. |
| Separate frontend hosting (Vercel) | Requires CORS and cross-site cookies, which weakens the SameSite=Strict session design in ADR-0008. |

## Tradeoffs

- Gained: one deploy, one origin, simple cookie auth, an enforced contract between backend and frontend.
- Lost: no SSR or static marketing pages, which this tool does not need.
- Cost: a Node build step in the Docker image (multi-stage build).

## Consequences

- The Dockerfile gains a frontend build stage in M8.
- API changes that alter the schema show up as a diff in `schema.d.ts` in the same PR.
- Dashboard work waits until the pipeline works (M8), so UI polish cannot crowd out core functionality.

## Why This Fits This Project

It adds TypeScript to the portfolio in the place where it matters most: a typed contract with a Python backend. It avoids adding a framework whose main features this tool would not use.

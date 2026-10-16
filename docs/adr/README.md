# Architecture Decision Records

Each ADR records one significant decision: the context, the choice, the alternatives, and the tradeoffs. ADRs are not edited after acceptance except to change status. A changed decision gets a new ADR that supersedes the old one.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-fastapi-postgres-own-workflow-state.md) | FastAPI + PostgreSQL own workflow state; n8n is the integration edge | Accepted |
| [0002](0002-postgres-job-queue-skip-locked.md) | PostgreSQL job queue using SKIP LOCKED | Accepted |
| [0003](0003-llm-extracts-code-decides.md) | LLM extracts facts; deterministic code decides | Accepted |
| [0004](0004-human-approval-for-all-outbound-v1.md) | 100% human approval for outbound messages in v1 | Accepted |
| [0005](0005-outbound-delivery-ambiguity.md) | Outbound delivery ambiguity and duplicate-prevention strategy | Accepted |
| [0006](0006-claude-provider-protocol-model-tiering.md) | Claude through an AI provider Protocol with model tiering | Accepted |
| [0007](0007-no-agent-framework-v1.md) | No agent framework, LangGraph, MCP, or multi-agent design in v1 | Accepted |
| [0008](0008-session-auth-api-keys-rbac.md) | Session authentication + scoped API keys + RBAC | Accepted |
| [0009](0009-vite-react-spa-openapi-types.md) | Vite React SPA with OpenAPI-generated TypeScript types | Accepted |
| [0010](0010-vps-docker-compose-deployment.md) | VPS + Docker Compose deployment | Accepted |
| [0011](0011-in-process-rate-limiting-and-client-ip.md) | In-process rate limiting and trusted-proxy client IP | Accepted |
| [0012](0012-api-key-format-and-hashing.md) | API key format and SHA-256 hashing | Accepted |

Template: Status, Date, Context, Decision, Alternatives Considered, Tradeoffs, Consequences, Why This Fits This Project.

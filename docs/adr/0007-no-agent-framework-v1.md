# ADR-0007: No agent framework, LangGraph, MCP, or multi-agent design in v1

- **Status:** Accepted
- **Date:** 2026-10-15

## Context

Agent frameworks, LangGraph, MCP, and multi-agent architectures are popular, and job posts mention them. It is tempting to add them so the project matches more keywords.

This system's workflow is fixed and known in advance: intake, analyze, route, draft, approve, deliver, follow up. The order does not change based on what the model decides. Every step has a defined input, output, and failure path.

## Decision

v1 uses none of the following:

- **Agent frameworks or LangGraph.** The workflow is an explicit state machine (`domain/lifecycle.py`) driven by a job queue (ADR-0002).
- **MCP.** No external tool ecosystem needs to plug in. The two drafting tools are plain read-only functions called through the provider's tool-use API.
- **Multi-agent design.** Two LLM calls with clear contracts. No agents passing work to each other.
- **Redis or Kubernetes.** See ADR-0002 and ADR-0010.

The only model-driven control flow is the bounded tool-use loop in drafting (read-only tools, at most 3 turns).

## Alternatives Considered

| Option | Why not |
|---|---|
| LangGraph for the lead pipeline | Models the same fixed sequence as a graph, adds a dependency and its own state store, and hides the transitions that reviewers want to read. |
| An autonomous agent that decides each step | Turns a predictable business process into an unpredictable one. Contradicts ADR-0003 and ADR-0004. |
| MCP server for the drafting tools | MCP helps when many clients need the same tools. Here one internal caller uses two functions. |
| Multi-agent (analyst agent, writer agent, reviewer agent) | Adds LLM calls, cost, and failure points with no measured benefit. The "reviewer" role belongs to a human in v1. |

## Tradeoffs

- Gained: a system that is predictable, testable, and explainable line by line.
- Lost: keyword coverage for "agents" and "MCP" in this repository. Those belong in a separate project built for agentic work.

## Consequences

- If a later feature needs open-ended, multi-step model reasoning, a new ADR must show why the state machine cannot handle it.
- **Later, not v1:** an MCP server exposing reviewer actions (list leads, approve, reject) to MCP clients, reusing the same services. It would add a new interface, not change who owns decisions.

## Why This Fits This Project

Knowing when not to use an agent is a senior-level signal. A reviewer who sees a fixed workflow wrapped in an agent framework will question the judgment behind the rest of the repository.

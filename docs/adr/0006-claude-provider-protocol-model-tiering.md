# ADR-0006: Claude through an AI provider Protocol with model tiering

- **Status:** Accepted
- **Date:** 2026-10-15

## Context

The system makes two kinds of LLM calls with different needs:

- `analyze_lead`: runs on every lead, including spam. Structured extraction into a fixed schema. Volume-sensitive and cost-sensitive.
- `draft_reply`: runs only on leads that pass routing. Writing quality matters, read-only tool use is allowed.

Tests must run in CI with no network calls and no API cost. Business logic must not depend on one vendor's SDK types.

## Decision

1. **Provider Protocol.** `ai/provider.py` defines a small Python `Protocol` covering what the services need: a structured-output call (prompt + JSON schema in, validated object plus usage out) and a bounded tool-use call. Services depend on the Protocol, never on the SDK.
2. **One real implementation:** `ai/anthropic_provider.py` using Claude with native structured output (JSON schema). **One fake** in tests that returns scripted outputs, including malformed ones.
3. **Model tiering by config:**
   - `ANALYSIS_MODEL`: a Haiku-tier Claude model for extraction
   - `DRAFT_MODEL`: a Sonnet-tier Claude model for drafting
   Exact model IDs live in environment config, not code.
4. **Every call is recorded** in `ai_calls`: provider, model, prompt name, version, hash, tokens, cost (`Decimal`, from a versioned price table), latency, attempt, outcome.
5. **Prompt, call, parse, validate, and business logic are separate modules.**
6. **Tool use in drafting** is limited to read-only tools (`get_service_details`, `get_open_call_slots`) with at most 3 turns. If the eval shows the static catalog performs the same when placed in the prompt, this ADR is amended and only the dynamic slot tool stays.

## Alternatives Considered

| Option | Why not |
|---|---|
| Call the Anthropic SDK directly from services | Ties business code to one SDK, makes testing harder, and spreads usage tracking across call sites. |
| LiteLLM or a LangChain chat-model wrapper | Adds a dependency and hides the request and response shapes that interviewers ask about. One small Protocol does the job. |
| OpenAI models | Comparable capability. Claude is chosen for consistency with the earlier portfolio project (Grounded) and its native structured-output support. Whether extraction quality is good enough is measured in M5, not assumed. A second provider is a later addition, justified only by a comparison eval. |
| One model for both calls | The larger model on every lead, including spam, costs more for a task a smaller model handles. The eval decides whether the tiering holds. |

## Tradeoffs

- Gained: testable services, vendor isolation, per-call cost and latency data, cheaper analysis.
- Lost: nothing material at this scale. The Protocol is small on purpose; it is not a general multi-vendor framework.
- Risk: a Haiku-tier model may extract less accurately. Measured in M5. If accuracy is not good enough, `ANALYSIS_MODEL` moves up a tier with no code change.

## Consequences

- CI makes zero real LLM calls. Real calls happen only in `make eval`.
- Changing a prompt means a new version file, and eval results are recorded per prompt version.
- Cost per lead is computed from stored rows, not estimated.

## Why This Fits This Project

It shows the standard production pattern for LLM integration (an interface, a fake for tests, telemetry on every call, model choice by task) without building a framework nobody needs.

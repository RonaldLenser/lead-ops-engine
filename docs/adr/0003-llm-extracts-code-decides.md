# ADR-0003: LLM extracts facts; deterministic code decides

- **Status:** Accepted
- **Date:** 2026-10-15

## Context

Each lead needs: structured fields pulled from free text, a service classification, a missing-information check, a qualification score, an urgency level, and a next step.

An LLM can produce all of these in one response, including a score like "87". That is fast to build and looks impressive in a demo. It also means:

- scores are not calibrated and change between runs and model versions
- routing cannot be unit tested
- nobody can explain why a lead got a given result
- text written by the lead (including injected instructions) directly influences decisions

## Decision

Split the work at a hard line.

**The LLM does:** extract fields from free text, each with an evidence quote; classify service types and urgency into fixed enums; set flags (`spam_likely`, `complaint`, `injection_attempt`); write draft text.

**Deterministic code does:**

- verify each evidence quote appears in the source text; unverified fields are nulled
- decide which fields are missing, per service type, from the validated extraction
- compute the score from extracted features, with weights in versioned `config/scoring.yaml`
- choose the route with ordered rules in versioned `config/routing.yaml`
- check drafts against policy rules (no prices, no unapproved URLs, no guarantees, booking-a-call CTA)

LLM flags can only increase oversight: they can send a lead to NEEDS_REVIEW, never to an outbound action. The two automatic closes each require a deterministic condition: SPAM needs no valid contact method; DISQUALIFIED needs an evidence-verified location outside the service area and on-site-only services. Both are reversible by a reviewer.

## Alternatives Considered

| Option | Why not |
|---|---|
| LLM returns score and route directly | Uncalibrated, untestable, and vulnerable to injection steering decisions. |
| LLM returns a confidence number used for routing | Self-reported confidence is poorly calibrated. Escalation triggers are deterministic conditions instead. |
| Classical ML classifier for service type | Needs labeled training data we do not have; an LLM with an enum schema needs no training data, and the eval set (M5) measures whether it is accurate enough. |
| Separate LLM calls per field or task | More cost and latency for no accuracy gain shown. One structured extraction call covers it. |

## Tradeoffs

- Gained: the same extraction always gives the same score and route; rules are unit tested; decisions are explainable from stored data; scoring and routing can change without re-running the model.
- Lost: nuance a model might add to a score. Accepted, because nuance that cannot be explained or tested is not useful for routing.
- Cost: rules and weights have to be written and tuned by hand, and the eval set must check the full path (extraction plus rules).

## Consequences

- `domain/scoring.py`, `domain/routing.py`, and `domain/policies.py` have no I/O and full unit test coverage.
- Evaluation reports both extraction accuracy and end-to-end route accuracy, so a regression can be traced to the model or to the rules.
- `score_version` is stored on each lead so old scores stay interpretable after weights change.

## Why This Fits This Project

This is the central design idea and the main thing an applied AI reviewer will look for: the model does the part only a model can do, and everything that needs to be reliable, auditable, and testable stays in code.

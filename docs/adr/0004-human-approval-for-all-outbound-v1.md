# ADR-0004: 100% human approval for outbound messages in v1

- **Status:** Accepted
- **Date:** 2026-10-15

## Context

The system drafts emails to real prospects on behalf of a business. A bad email (wrong name, an invented price, a promise the business cannot keep, or text shaped by an injection attempt) reaches a stranger and cannot be recalled.

There is no measured evidence yet that drafts are reliable. The eval set that would provide it is built in M5, and draft quality evaluation comes later.

## Decision

In v1, **every outbound message requires a reviewer's approval** before a delivery job is created. This covers AI-drafted first-touch messages, info-request messages, and templated follow-ups.

- Only human actions create delivery jobs: the approve endpoint, and a reviewer's `resend` on resolve-delivery. The one automatic path (retrying a dispatch that provably never left) reuses an already-approved dispatch attempt and creates nothing new.
- Approval records reviewer, decision, timestamp, edited body, edit distance, and reason.
- Reviewer edits pass the same deterministic policy checks as AI drafts; failures return `422`.
- Rejection can request a redraft (up to 2) with the reviewer's reason passed to the model.

## Alternatives Considered

| Option | Why not |
|---|---|
| Auto-send when the model is confident | Self-reported confidence is not reliable (ADR-0003), and no eval evidence exists yet. |
| Auto-send templated follow-ups only | Lower risk, but follow-ups still go to real people and the lead may have replied through a channel the system cannot see. Kept simple: approve everything in v1. |
| Approve only flagged drafts | Requires a trusted flagging signal, which again needs eval evidence first. |

## Tradeoffs

- Gained: no message reaches a prospect without a human check; rejection reasons and edits become labeled data for improving prompts.
- Lost: full automation. Every message costs reviewer time.
- Cost: the reviewer UI must make approval fast, or the human step becomes the bottleneck.

## Consequences

- The approval queue is a core screen in the dashboard (M8), not an afterthought.
- Approval-without-edit rate and edit distance are tracked as metrics. They are the evidence for any future autonomy.
- **Planned for later, not v1:** "earned autonomy", where auto-send is allowed for one message category only after eval results meet thresholds set in advance. That requires its own ADR.

## Why This Fits This Project

For a small business, one embarrassing email costs more than the minutes saved by skipping review. Starting at 100% approval and defining how autonomy would be earned with evidence is the realistic path, and it is a clear story for interviews.

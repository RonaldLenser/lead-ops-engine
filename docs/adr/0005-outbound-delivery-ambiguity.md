# ADR-0005: Outbound delivery ambiguity and duplicate-prevention strategy

- **Status:** Accepted
- **Date:** 2026-10-15

## Context

Approved messages are sent by n8n through Gmail. The worker sends a signed `message.dispatch` request to n8n, n8n sends the email, then calls back with the result.

Several failures leave the system unsure whether an email went out:

- the dispatch request times out after n8n received it
- the connection drops mid-response
- n8n returns a 5xx after the Gmail node already ran
- the callback never arrives

Gmail does not offer an idempotency key, so a second send cannot be deduplicated by the provider. Retrying on every error, the usual reflex, would email the same prospect two or three times.

**Exactly-once delivery is not achievable here.** The system must not claim it.

## Decision

The system provides **duplicate-outbound protection**, defined precisely:

1. **Duplicate internal delivery jobs are prevented.** One job per `(message_id, dispatch_attempt)` via a UNIQUE `jobs.dedupe_key`. The worker claims the message with a compare-and-set update (`approved` → `dispatching`). Only one worker can win.
2. **Once an external send may have been attempted, an ambiguous or unknown result is never retried automatically.** Ambiguous means: timeout, dropped connection, 5xx, malformed response, or no callback within `DELIVERY_CALLBACK_TIMEOUT_MINUTES`.
3. **Ambiguous delivery moves the lead to NEEDS_REVIEW** with `review_reason = delivery_unknown`. The message status becomes `delivery_unknown`.
4. **A human determines the next action** through `POST /v1/messages/{id}/resolve-delivery`: `confirmed_sent` (after checking the Sent folder), `resend` (new dispatch attempt, audited), or `abandon`.

Additional rules:

- **Safe automatic retry** is allowed only when the failure proves the request never left: DNS failure, connection refused, TLS handshake failure.
- A definite provider failure reported by a signed callback goes to NEEDS_REVIEW (`delivery_failed`), not to automatic retry, in v1.
- Callbacks carry `dispatch_attempt`. A late signed `sent` callback for the current attempt of a `delivery_unknown` message resolves it automatically. That is confirmed evidence, not a retry. A callback for an older attempt or a `cancelled` message changes no state; it is audited and shown as a timeline warning.
- If safe retries run out, the message becomes `failed` and the lead goes to NEEDS_REVIEW (`delivery_failed`). No dead delivery job is left without a review item.
- **Crash recovery is treated as ambiguous.** If a worker dies after claiming a message, the job lock expires and another worker reclaims the job. That worker finds the message already in `dispatching`, so the compare-and-set fails and the message goes to `delivery_unknown`. A reclaimed delivery job never re-sends.
- Dead delivery jobs cannot be requeued through the generic `/v1/jobs/{id}/retry` endpoint.
- The n8n send node must have "Retry On Fail" disabled.

## Alternatives Considered

| Option | Why not |
|---|---|
| At-least-once: retry until success | Guarantees duplicates in the ambiguous cases. A duplicate sales email to a prospect is worse than a delayed one a human sees. |
| Claim exactly-once using an outbox | The outbox prevents duplicate *jobs*, not duplicate *sends* when the provider result is unknown. Claiming more would be false. |
| Query the provider to check whether the send happened, then retry | Possible later by searching Sent mail for a message ID header. Adds Gmail read access and complexity; deferred. |
| Let n8n handle retries | Moves a correctness decision into a tool that cannot see message state (contradicts ADR-0001). |

## Tradeoffs

- Gained: no automatic path can email a prospect twice. Every ambiguous case is visible and has an owner.
- Lost: some sends need a human click that a retry might have handled. Expected to be rare.
- Remaining risk: a human `resend` after an ambiguous result can still duplicate if the first send did go out. The UI must prompt the reviewer to check the Sent folder first.

## Consequences

- Message statuses include `dispatching`, `delivery_unknown`, and `failed`, documented in [state-machine.md](../state-machine.md).
- Integration tests must cover: timeout leads to `delivery_unknown` with no retry; connection refused leads to retry; duplicate callbacks are idempotent; a late `sent` callback resolves the hold.
- README and interview wording: "duplicate-outbound protection", never "exactly-once".

## Why This Fits This Project

This is the difference between saying "we retry on failure" and understanding what a retry does to a real person's inbox. Being exact about what is and is not guaranteed is the strongest signal this project can send about production thinking.

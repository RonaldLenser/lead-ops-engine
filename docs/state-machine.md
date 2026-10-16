# State Machines

Status: approved design (M0). Not implemented yet. Implementation lands in M3 (lifecycle module) and is extended in M6 and M7.

Source: [DESIGN.md](DESIGN.md) sections 7 and 9.

The system has two state machines:

1. **Lead status:** where a lead is in the business process.
2. **Message status:** where one outbound email is in drafting, approval, and delivery.

Processing details (job attempts, retries, locks) live in the `jobs` and `workflow_runs` tables, not in either state machine.

---

## Rules That Apply to Every Transition

1. Lead status changes **only** through `domain/lifecycle.py`, which holds an explicit transition table. A transition not in the table raises an error. There is no "set status" shortcut anywhere else.
2. Every transition writes an `audit_events` row **in the same database transaction** as the status change. If one fails, both roll back.
3. Transitions use optimistic locking (`leads.version`). Two concurrent actions on the same lead cannot both succeed.
4. Actors are recorded: `system` (worker), `user` (reviewer/admin), `api_key` (n8n callback), `ai` is never an actor for a transition. AI output only feeds rules that the system applies.

---

## Lead Status

### States

| State | Meaning | Closed? |
|---|---|---|
| `RECEIVED` | Stored, analysis job enqueued | No |
| `ANALYZING` | Analysis job running | No |
| `QUALIFIED` | Rules passed, ready for drafting | No |
| `NEEDS_REVIEW` | Held for a human. Always has a `review_reason` and `resume_status`. | No |
| `DISQUALIFIED` | Rules failed (for example out of area) | Yes, reversible by a reviewer |
| `SPAM` | Spam signal plus no valid contact method | Yes, reversible by a reviewer, never deleted |
| `DRAFTING` | First-touch draft job running | No |
| `AWAITING_APPROVAL` | First-touch draft waiting for a reviewer | No |
| `APPROVED` | First-touch message approved, delivery in progress | No |
| `CONTACTED` | First-touch message confirmed sent | No |
| `REPLIED` | Reviewer marked that the lead replied | No |
| `CLOSED_WON` | Became a client | Yes |
| `CLOSED_LOST` | Rejected, abandoned, or lost | Yes |
| `CLOSED_NO_RESPONSE` | Follow-ups finished with no reply | Yes |

"Reversible by a reviewer" means a closed state that a reviewer can move with an audited triage action. Nothing reopens automatically.

### Diagram

```text
                    ┌──────────────► SPAM ◄───────────────┐
                    │                                      │ triage
RECEIVED ─► ANALYZING ─► DISQUALIFIED ◄────────────────────┤
                    │                                      │
                    ├──────────────► NEEDS_REVIEW ─────────┤
                    │                     │ triage qualify │
                    └──► QUALIFIED ◄──────┘◄───────────────┘
                             │
                             ▼
                         DRAFTING ◄──── reject + redraft (count < 2)
                             │                    │
                             ▼                    │
                    AWAITING_APPROVAL ────────────┘
                      │      │      └── reject, no redraft ─► CLOSED_LOST
                      │      └── reject + redraft, count = 2 ─► NEEDS_REVIEW
                      ▼ approve (human)
                   APPROVED ── ambiguous or failed delivery ─► NEEDS_REVIEW
                      │ sent confirmed
                      ▼
                  CONTACTED ── follow-up delivery ambiguous/failed ─► NEEDS_REVIEW
                   │   │   └── follow-ups finished ─► CLOSED_NO_RESPONSE
                   │   └── outcome ─► CLOSED_WON | CLOSED_LOST
                   ▼ outcome
                REPLIED ─► CLOSED_WON | CLOSED_LOST
```

The diagram shows the main paths. The transition table below is authoritative; rows 9, 21, 22, and 23 are omitted from the diagram for readability.

### Transition Table

| # | From | To | Trigger | Actor |
|---|---|---|---|---|
| 1 | RECEIVED | ANALYZING | Worker claims `analyze_lead` job | system |
| 2 | ANALYZING | SPAM | Routing rule 1 | system |
| 3 | ANALYZING | NEEDS_REVIEW (`escalation`) | Routing rule 2 | system |
| 4 | ANALYZING | NEEDS_REVIEW (`analysis_failed` or `evidence_failed`) | Routing rule 3, or analysis retries exhausted | system |
| 5 | ANALYZING | DISQUALIFIED | Routing rule 4 | system |
| 6 | ANALYZING | QUALIFIED | Routing rule 5 | system |
| 7 | QUALIFIED | DRAFTING | Worker claims `draft_reply` job | system |
| 8 | DRAFTING | AWAITING_APPROVAL | Draft stored, message `pending_approval` | system |
| 9 | DRAFTING | NEEDS_REVIEW (`draft_failed`) | Drafting retries exhausted | system |
| 10 | AWAITING_APPROVAL | APPROVED | `POST /messages/{id}/approve` | reviewer |
| 11 | AWAITING_APPROVAL | DRAFTING | Reject with `redraft: true` and `redraft_count < 2` | reviewer |
| 12 | AWAITING_APPROVAL | NEEDS_REVIEW (`redraft_limit`) | Reject with `redraft: true` and `redraft_count = 2` | reviewer |
| 13 | AWAITING_APPROVAL | CLOSED_LOST | Reject with `redraft: false` | reviewer |
| 14 | APPROVED | CONTACTED | Signed `sent` callback, or sink delivery success | api_key / system |
| 15 | APPROVED | NEEDS_REVIEW (`delivery_unknown`) | Ambiguous dispatch result or callback timeout | system |
| 16 | APPROVED | NEEDS_REVIEW (`delivery_failed`) | Signed `failed` callback | api_key |
| 17 | CONTACTED | NEEDS_REVIEW (`delivery_unknown` or `delivery_failed`) | Same as 15/16 for a follow-up message | system / api_key |
| 18 | CONTACTED | REPLIED, CLOSED_WON, CLOSED_LOST | `POST /leads/{id}/outcome` | reviewer |
| 19 | REPLIED | CLOSED_WON, CLOSED_LOST | `POST /leads/{id}/outcome` | reviewer |
| 20 | CONTACTED | CLOSED_NO_RESPONSE | Every follow-up step is finished (`sent` or `skipped`) and the wait period passed with no outcome | system |
| 21 | NEEDS_REVIEW | per reason (below) | Triage or resolve-delivery | reviewer |
| 22 | SPAM, DISQUALIFIED | QUALIFIED, SPAM, DISQUALIFIED, CLOSED_LOST | `POST /leads/{id}/triage` | reviewer |
| 23 | NEEDS_REVIEW, SPAM, DISQUALIFIED | RECEIVED | `POST /leads/{id}/reprocess` (new workflow run) | admin |

Reprocessing is not allowed once any message has been dispatched for the lead.

### NEEDS_REVIEW Actions by Reason

`NEEDS_REVIEW` is a human-hold state. It stores why it was entered (`review_reason`) and what state the lead was in before (`resume_status`).

| `review_reason` | Entered from | Allowed actions | Result |
|---|---|---|---|
| `escalation` | ANALYZING | triage `qualify` / `disqualify` / `spam` / `close` | QUALIFIED / DISQUALIFIED / SPAM / CLOSED_LOST |
| `analysis_failed` | ANALYZING | same as above | same as above |
| `evidence_failed` | ANALYZING | same as above | same as above |
| `draft_failed` | DRAFTING | same as above (`qualify` retries drafting) | same as above |
| `redraft_limit` | AWAITING_APPROVAL | same as above (`qualify` starts a fresh draft cycle) | same as above |
| `delivery_unknown` | APPROVED or CONTACTED | resolve-delivery `confirmed_sent` / `resend` / `abandon` | CONTACTED / `resume_status` plus a new dispatch attempt / first-touch: CLOSED_LOST, follow-up: message `cancelled`, lead back to CONTACTED |
| `delivery_failed` | APPROVED or CONTACTED | resolve-delivery `resend` / `abandon` | `resume_status` plus a new dispatch attempt / same as above |

Every resolve-delivery action records reviewer, action, reason, timestamp, original delivery state, and resulting message and lead status, and `resend` always creates a new delivery attempt (DESIGN.md section 9.1).

A late signed `sent` callback for the current `dispatch_attempt` of a message in `delivery_unknown` resolves the hold to CONTACTED with no human action. That is confirmed evidence, not a retry. A callback for an older attempt, or for a `cancelled` message, changes no state; it is audited and shown as a warning on the timeline.

---

## Message Status

```text
 (created) ─► pending_approval ─► approved ─► dispatching ─► sent
                  │                  ▲              │
                  ▼                  │              ├─► delivery_unknown ─► sent (confirmed or late callback)
               rejected              │              │          │
                                     │              │          ├─► approved (human resend, attempt + 1)
                                     │              │          └─► cancelled (human abandon)
                                     │              └─► failed ─► approved (human resend) | cancelled
                                     ├──────── human resend (from delivery_unknown or failed)
                                     └──────── automatic, only when the request provably never left
 pending_approval or approved ─► cancelled (follow-up cancelled because the lead replied or closed)
```

| Status | Meaning |
|---|---|
| `pending_approval` | Waiting for a reviewer. Policy violations, if any, are attached. |
| `approved` | Reviewer approved. A `deliver_message` job is enqueued with `dedupe_key = deliver:{message_id}:{dispatch_attempt}`. |
| `rejected` | Reviewer rejected. Reason stored in `approvals`. |
| `dispatching` | A worker won the compare-and-set claim (`approved` → `dispatching`) and is sending the dispatch request. |
| `sent` | Confirmed by signed callback or by the sink. |
| `delivery_unknown` | The request may have been received, but the outcome is not confirmed. Never retried automatically. |
| `failed` | Definite failure: a signed `failed` callback, or safe retries exhausted. Not retried automatically in v1. |
| `cancelled` | Abandoned by a reviewer, or a follow-up that is no longer needed. |

**Automatic retry rule:** a dispatch is retried automatically **only** when the failure proves the request never left the system (DNS failure, connection refused, TLS handshake failure). The message stays `dispatching` → back to `approved` with the same `dispatch_attempt`, and the job retries with backoff. Every other failure goes to `delivery_unknown`. If the safe retries run out, the message becomes `failed` and the lead goes to NEEDS_REVIEW (`delivery_failed`). A delivery job reclaimed after a worker crash finds the message already in `dispatching` and also moves it to `delivery_unknown`; it never re-sends.

---

## Follow-ups

- When a lead reaches CONTACTED, follow-up rows are scheduled (cadence decided in M7, see DESIGN.md open question 3).
- At `due_at`, a job creates a **templated** message (no AI) in `pending_approval`. It needs reviewer approval like any other message.
- Follow-up messages change **message** status only. The lead stays CONTACTED unless delivery becomes ambiguous or fails (transition 17).
- When the lead moves to REPLIED or any closed state, scheduled follow-ups and their unsent messages are set to `cancelled` in the same transaction.
- Follow-ups cannot be redrafted (they are templates); `redraft: true` on a follow-up returns `422`.
- Rejecting a follow-up message sets it to `rejected` and its follow-up step to `skipped`. The lead stays CONTACTED and later steps continue.
- While the lead is in NEEDS_REVIEW, scheduled follow-ups are set to `paused`. The exact rule for rescheduling them is decided in M7.

---

## What the LLM Can and Cannot Affect

| LLM output | Can lead to | Cannot lead to |
|---|---|---|
| `spam_likely` flag | SPAM, only if no valid contact method is also true (deterministic check) | Any outbound message |
| Extracted location | DISQUALIFIED, only if its evidence quote is verified and the deterministic service-area and catalog checks fail | Disqualifying on a missing or unverified location |
| `injection_attempt`, `complaint` flags | NEEDS_REVIEW (more oversight) | Any outbound message |
| Extracted fields | Inputs to the deterministic score and routing rules | Choosing a state directly |
| Draft text | A message in `pending_approval` | `approved` or `sent` without a human |

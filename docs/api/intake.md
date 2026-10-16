# Intake API

Status: implemented in M2.

Two ways to submit a lead. Both end in the same transaction (see [DESIGN.md](../DESIGN.md) and `backend/src/leadops/services/intake.py`).

| Endpoint | Caller | Authentication | Dedupe key |
|---|---|---|---|
| `POST /v1/leads` | Trusted machine clients (n8n, a form backend) | API key with scope `leads:write` | `(API key, Idempotency-Key)` |
| `POST /v1/webhooks/leads/{source}` | Webhook senders | HMAC signature with the source's shared secret | `(source, event_id)` |

Both return `202 Accepted`:

```json
{"lead_id": "01a14257-0f72-7376-90ee-68de885af2c4", "status": "RECEIVED", "duplicate": false}
```

`duplicate: true` means this request repeated an earlier one and the original lead is returned. Nothing new was written.

---

## Lead Fields

| Field | Type | Rules |
|---|---|---|
| `message` | string | required, 1 to 10,000 characters |
| `name` | string | optional, up to 200 |
| `email` | string | optional, up to 320 |
| `phone` | string | optional, up to 40 |

Unknown fields are rejected (`422`). Strings are trimmed.

Email and phone are **not** rejected for being unusable. They are normalized (lowercased email; phone to E.164 using `DEFAULT_PHONE_REGION`). Values that fail normalization are kept on the lead as submitted and listed in `contact_issues` (`email_invalid`, `phone_invalid`). A lead with no usable email or phone is still accepted, without a contact.

---

## Direct Intake: `POST /v1/leads`

```http
POST /v1/leads
Authorization: Bearer lok_<prefix>_<secret>
Idempotency-Key: form-submission-8841
Content-Type: application/json

{"source": "website_form", "message": "Need a new site", "name": "Jane", "email": "jane@example.com"}
```

- `source`: lowercase letters, digits, `_` or `-`, up to 64 characters.
- `Idempotency-Key`: required, 1 to 128 characters of `A-Z a-z 0-9 _ . : -`. Use one per logical submission, and resend the same key on retry.

### API keys

Created on the server with the CLI. The full key prints once and is never stored:

```bash
leadops api-keys create --name n8n-intake --scope leads:write
leadops api-keys list
leadops api-keys revoke --name n8n-intake
```

Format and storage: [ADR-0012](../adr/0012-api-key-format-and-hashing.md).

---

## Webhook Intake: `POST /v1/webhooks/leads/{source}`

`{source}` must be configured in `WEBHOOK_SECRETS`. Body: the lead fields plus `event_id` (the sender's unique ID for this event, 1 to 200 characters of `A-Z a-z 0-9 _ . : -`).

### Signing contract (v1)

```text
X-LeadOps-Timestamp: <unix time in seconds>
X-LeadOps-Signature: v1=<hex HMAC-SHA256(secret, "<timestamp>.<raw request body>")>
```

- The signature is computed over the exact bytes sent, joined to the timestamp with a `.`.
- The server rejects timestamps more than `WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS` (default 300) from its clock.
- Any secret in the source's list is accepted, so secrets can be rotated without downtime.
- Verification happens before the body is parsed. Unsigned, wrongly signed, or stale requests are rejected with `401` and nothing is stored.

Example signer (Python):

```python
import hashlib, hmac, json, time

body = json.dumps({"event_id": "evt_123", "message": "Need a website"}).encode()
timestamp = int(time.time())
digest = hmac.new(
    SECRET.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
).hexdigest()
headers = {
    "Content-Type": "application/json",
    "X-LeadOps-Timestamp": str(timestamp),
    "X-LeadOps-Signature": f"v1={digest}",
}
```

---

## Idempotency

| Situation | Result |
|---|---|
| New key or event ID | `202`, `duplicate: false`, lead created |
| Same key or event ID, same content | `202`, `duplicate: true`, original `lead_id`, nothing written |
| Same key or event ID, different content | `409 idempotency_conflict`, nothing written |
| Request failed with `5xx` | Nothing was committed; retrying with the same key is safe |

"Same content" is compared on the **validated** payload as canonical JSON (sorted keys, trimmed strings), hashed with SHA-256. Key order and whitespace do not matter.

Concurrent duplicates are safe: the database makes the second insert wait for the first transaction, then returns the first result. Tested with 10 simultaneous identical requests (exactly one lead).

Transport dedupe is separate from contact dedupe. A new submission from a known email creates a **new lead** on the **existing contact**.

---

## Errors

All errors use one shape: `{"error": {"code", "message", "request_id"}}`.

| Status | Code | When |
|---|---|---|
| 400 | `bad_request` | Missing or malformed `Idempotency-Key`; body is not a JSON object |
| 401 | `unauthorized` | Missing, unknown, wrong, or revoked API key (one message for all) |
| 401 | `invalid_signature` | Missing, malformed, stale, or incorrect webhook signature |
| 403 | `forbidden` | API key lacks `leads:write` |
| 404 | `not_found` | Webhook source not configured |
| 409 | `idempotency_conflict` | Key or event ID reused with different content |
| 413 | `payload_too_large` | Body over `MAX_REQUEST_BODY_BYTES` (32 KB) |
| 422 | `validation_error` | Schema errors; `details` lists location and reason, never the submitted value |
| 429 | `rate_limited` | Per-IP, per-key, or per-source limit hit; see `Retry-After` |

Rate limiting and client IP rules: [ADR-0011](../adr/0011-in-process-rate-limiting-and-client-ip.md).

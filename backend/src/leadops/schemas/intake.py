"""Intake request/response models and the canonical payload hash.

Contact fields are validated for TYPE and SIZE only. Whether an email or
phone number is usable is decided later by normalization, which records a
contact issue instead of rejecting the lead (see domain/normalization.py).
"""

import hashlib
import json
import uuid

from pydantic import BaseModel, ConfigDict, Field

SOURCE_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
EVENT_ID_PATTERN = r"^[A-Za-z0-9_.:-]{1,200}$"
IDEMPOTENCY_KEY_PATTERN = r"^[A-Za-z0-9_.:-]{1,128}$"
MAX_MESSAGE_LENGTH = 10_000


class LeadFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)
    name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)


class DirectLeadRequest(LeadFields):
    """POST /v1/leads body. `source` names where the lead came from (for example website_form)."""

    source: str = Field(pattern=SOURCE_PATTERN)


class WebhookLeadPayload(LeadFields):
    """POST /v1/webhooks/leads/{source} body. `event_id`: the sender's unique ID for the event."""

    event_id: str = Field(pattern=EVENT_ID_PATTERN)


class LeadAccepted(BaseModel):
    lead_id: uuid.UUID
    status: str
    duplicate: bool = Field(
        description="True when this request repeats an earlier one; the original lead is returned."
    )


def canonical_sha256(payload: BaseModel) -> bytes:
    """SHA-256 of the validated payload as canonical JSON.

    Canonical = sorted keys, no extra whitespace, after validation (so trimmed
    strings and omitted vs null optional fields compare equal). Two requests
    with the same meaning get the same hash; any change in content does not.
    """
    canonical = json.dumps(
        payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).digest()

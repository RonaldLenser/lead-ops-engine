"""POST /v1/webhooks/leads/{source}: signed webhook intake.

Order of checks:
    IP rate limit -> known source -> body (32 KB cap) -> HMAC signature
    -> per-source rate limit -> JSON -> schema -> transaction

The signature is verified on the raw bytes BEFORE parsing, and nothing from
an unsigned or wrongly signed request is stored. Contract: see
integrations/signing.py and docs/api/intake.md.

Dedupe: (source, event_id). A redelivered event with the same content
returns the original lead; the same event ID with different content is a 409.
"""

import time

import structlog
from fastapi import APIRouter, Depends, Path, Request, status

from leadops.api.deps import SessionFactoryDep, SettingsDep, enforce_rate_limit, limit_intake_by_ip
from leadops.api.request_body import openapi_json_body, parse_json_object, validate_body
from leadops.errors import InvalidSignatureError, NotFoundError
from leadops.integrations.signing import SIGNATURE_HEADER, TIMESTAMP_HEADER, verify_signature
from leadops.schemas.intake import (
    SOURCE_PATTERN,
    LeadAccepted,
    WebhookLeadPayload,
    canonical_sha256,
)
from leadops.services.intake import IntakeCommand, accept_lead

router = APIRouter(prefix="/v1/webhooks", tags=["intake"])
logger = structlog.get_logger(__name__)


@router.post(
    "/leads/{source}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=LeadAccepted,
    dependencies=[Depends(limit_intake_by_ip)],
    openapi_extra=openapi_json_body(WebhookLeadPayload),
    summary="Submit a lead from a signed webhook",
)
async def receive_lead_webhook(
    request: Request,
    settings: SettingsDep,
    session_factory: SessionFactoryDep,
    source: str = Path(pattern=SOURCE_PATTERN),
) -> LeadAccepted:
    secrets = settings.webhook_secrets.get(source)
    if not secrets:
        raise NotFoundError("Unknown webhook source")

    body = await request.body()
    problem = verify_signature(
        secrets=[secret.get_secret_value() for secret in secrets],
        timestamp_header=request.headers.get(TIMESTAMP_HEADER),
        signature_header=request.headers.get(SIGNATURE_HEADER),
        body=body,
        now=int(time.time()),
        tolerance_seconds=settings.webhook_timestamp_tolerance_seconds,
    )
    if problem is not None:
        logger.warning("webhook_signature_rejected", source=source, reason=problem.value)
        raise InvalidSignatureError()

    enforce_rate_limit(request, "webhook_source", source)
    raw_payload = parse_json_object(body)
    payload = validate_body(WebhookLeadPayload, raw_payload)

    result = await accept_lead(
        session_factory,
        IntakeCommand(
            kind="webhook",
            source=source,
            fields=payload,
            raw_payload=raw_payload,
            payload_sha256=canonical_sha256(payload),
            actor_type="webhook",
            actor_id=source,
            request_id=structlog.contextvars.get_contextvars().get("request_id"),
            external_event_id=payload.event_id,
        ),
        default_phone_region=settings.default_phone_region,
    )
    return LeadAccepted(lead_id=result.lead_id, status=result.status, duplicate=result.duplicate)

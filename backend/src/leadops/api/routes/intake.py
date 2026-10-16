"""POST /v1/leads: direct intake for trusted machine clients (n8n, a form backend).

Order of checks, cheapest and least trusting first:
    IP rate limit -> API key (leads:write) -> per-key rate limit
    -> Idempotency-Key header -> body (32 KB cap) -> JSON -> schema -> transaction

Idempotency: a client retry with the same Idempotency-Key and the same
content returns the original lead (duplicate: true) and writes nothing. The
same key with different content is a 409. Keys are scoped to the API key, so
two clients cannot collide.
"""

import re
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, Request, status

from leadops.api.auth import AuthenticatedKey, require_api_key
from leadops.api.deps import SessionFactoryDep, SettingsDep, enforce_rate_limit, limit_intake_by_ip
from leadops.api.request_body import openapi_json_body, parse_json_object, validate_body
from leadops.errors import BadRequestError
from leadops.schemas.intake import (
    IDEMPOTENCY_KEY_PATTERN,
    DirectLeadRequest,
    LeadAccepted,
    canonical_sha256,
)
from leadops.security.api_keys import Scope
from leadops.services.intake import IntakeCommand, accept_lead

router = APIRouter(prefix="/v1", tags=["intake"])

_IDEMPOTENCY_KEY = re.compile(IDEMPOTENCY_KEY_PATTERN)
LeadsWriteKey = Annotated[AuthenticatedKey, Depends(require_api_key(Scope.LEADS_WRITE))]


@router.post(
    "/leads",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=LeadAccepted,
    dependencies=[Depends(limit_intake_by_ip)],
    openapi_extra=openapi_json_body(DirectLeadRequest),
    summary="Submit a lead (API key, idempotent)",
)
async def submit_lead(
    request: Request,
    api_key: LeadsWriteKey,
    settings: SettingsDep,
    session_factory: SessionFactoryDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> LeadAccepted:
    enforce_rate_limit(request, "intake_api_key", str(api_key.id))
    if idempotency_key is None or not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
        raise BadRequestError(
            "Idempotency-Key header is required: 1-128 characters of A-Z a-z 0-9 _ . : -"
        )

    raw_payload = parse_json_object(await request.body())
    lead_request = validate_body(DirectLeadRequest, raw_payload)

    result = await accept_lead(
        session_factory,
        IntakeCommand(
            kind="direct",
            source=lead_request.source,
            fields=lead_request,
            raw_payload=raw_payload,
            payload_sha256=canonical_sha256(lead_request),
            actor_type="api_key",
            actor_id=api_key.prefix,
            request_id=structlog.contextvars.get_contextvars().get("request_id"),
            idempotency_key=idempotency_key,
            api_key_id=api_key.id,
        ),
        default_phone_region=settings.default_phone_region,
    )
    return LeadAccepted(lead_id=result.lead_id, status=result.status, duplicate=result.duplicate)

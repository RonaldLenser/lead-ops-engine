"""Lead intake: one transaction from accepted request to queued work.

Everything below happens in ONE database transaction. Either all of it is
committed, or none of it is:

    1. inbound_events  insert, deduped on the idempotency key / event ID
    2. contacts        upsert (only when an email or phone normalizes)
    3. leads           insert, status RECEIVED
    4. workflow_runs   insert, status pending
    5. jobs            insert analyze_lead, status queued (run by the M3 worker)
    6. audit_events    insert lead.received (IDs and flags only, no personal data)

Two kinds of "duplicate" are handled separately on purpose:
- Transport duplicate: the same request delivered twice (client retry,
  webhook redelivery). Detected at step 1. Returns the ORIGINAL lead and
  writes nothing else. Same key but different content is a 409.
- Business duplicate: the same person writing in again. Detected at step 2.
  Creates a NEW lead attached to the existing contact. A second inquiry is
  real information and must not be dropped.
"""

import uuid
from dataclasses import dataclass
from typing import Any, Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from leadops.db import repositories as repo
from leadops.domain.normalization import normalize_contact
from leadops.errors import IdempotencyConflictError
from leadops.schemas.intake import LeadFields

logger = structlog.get_logger(__name__)

ANALYZE_LEAD_JOB = "analyze_lead"


@dataclass(frozen=True)
class IntakeCommand:
    kind: Literal["direct", "webhook"]
    source: str
    fields: LeadFields
    raw_payload: dict[str, Any]
    payload_sha256: bytes
    actor_type: Literal["api_key", "webhook"]
    actor_id: str
    request_id: str | None
    idempotency_key: str | None = None
    api_key_id: uuid.UUID | None = None
    external_event_id: str | None = None


@dataclass(frozen=True)
class IntakeResult:
    lead_id: uuid.UUID
    status: str
    duplicate: bool


async def _existing_result(session: AsyncSession, command: IntakeCommand) -> IntakeResult:
    """The request's dedupe key is taken: replay the original or reject the mismatch."""
    if command.api_key_id is not None and command.idempotency_key is not None:
        existing = await repo.find_direct_event(
            session, api_key_id=command.api_key_id, idempotency_key=command.idempotency_key
        )
    elif command.external_event_id is not None:
        existing = await repo.find_webhook_event(
            session, source=command.source, external_event_id=command.external_event_id
        )
    else:  # unreachable: the CHECK constraint on inbound_events requires one of the two
        raise ValueError("intake command has no dedupe key")
    if existing.payload_sha256 != command.payload_sha256:
        raise IdempotencyConflictError(
            "This idempotency key or event ID was already used with different content"
        )
    lead_id, status = await repo.lead_for_event(session, existing.id)
    return IntakeResult(lead_id=lead_id, status=status, duplicate=True)


async def accept_lead(
    session_factory: async_sessionmaker[AsyncSession],
    command: IntakeCommand,
    *,
    default_phone_region: str,
) -> IntakeResult:
    async with session_factory() as session, session.begin():
        event_id = await repo.insert_inbound_event(
            session,
            kind=command.kind,
            source=command.source,
            payload=command.raw_payload,
            payload_sha256=command.payload_sha256,
            request_id=command.request_id,
            idempotency_key=command.idempotency_key,
            api_key_id=command.api_key_id,
            external_event_id=command.external_event_id,
        )
        if event_id is None:
            result = await _existing_result(session, command)
            logger.info("lead_intake_duplicate", lead_id=str(result.lead_id), source=command.source)
            return result

        fields = command.fields
        contact = normalize_contact(
            email=fields.email,
            phone=fields.phone,
            name=fields.name,
            default_region=default_phone_region,
        )
        contact_id: uuid.UUID | None = None
        contact_created = False
        if contact.identifiable:
            contact_id, contact_created = await repo.upsert_contact(
                session, email=contact.email, phone=contact.phone, name=contact.name
            )

        lead_id = await repo.insert_lead(
            session,
            inbound_event_id=event_id,
            contact_id=contact_id,
            source=command.source,
            raw_message=fields.message,
            submitted_contact={"name": fields.name, "email": fields.email, "phone": fields.phone},
            contact_issues=list(contact.issues),
        )
        run_id = await repo.insert_workflow_run(session, lead_id=lead_id, trigger="intake")
        await repo.enqueue_job(
            session,
            workflow_run_id=run_id,
            job_type=ANALYZE_LEAD_JOB,
            dedupe_key=f"{ANALYZE_LEAD_JOB}:{lead_id}",
            payload={"lead_id": str(lead_id)},
        )
        await repo.insert_audit_event(
            session,
            event_type="lead.received",
            actor_type=command.actor_type,
            actor_id=command.actor_id,
            lead_id=lead_id,
            workflow_run_id=run_id,
            request_id=command.request_id,
            data={
                "kind": command.kind,
                "source": command.source,
                "inbound_event_id": str(event_id),
                "contact_id": str(contact_id) if contact_id else None,
                "contact_created": contact_created,
                "contact_issues": list(contact.issues),
            },
        )

    logger.info(
        "lead_received",
        lead_id=str(lead_id),
        workflow_run_id=str(run_id),
        source=command.source,
        contact_created=contact_created,
        contact_issues=list(contact.issues),
    )
    return IntakeResult(lead_id=lead_id, status="RECEIVED", duplicate=False)

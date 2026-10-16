"""SQL for intake and API keys. Every function takes the caller's session and
never commits: the service decides the transaction boundary.

Plain SQLAlchemy Core statements against the ORM tables, so the SQL that
runs is easy to read (and to explain) line by line.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, func, literal_column, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from leadops.db.models import ApiKey, AuditEvent, Contact, InboundEvent, Job, Lead, WorkflowRun
from leadops.ids import uuid7

# ----- inbound events (transport-level dedupe) -----


@dataclass(frozen=True)
class ExistingEvent:
    id: uuid.UUID
    payload_sha256: bytes


async def insert_inbound_event(
    session: AsyncSession,
    *,
    kind: str,
    source: str,
    payload: dict[str, Any],
    payload_sha256: bytes,
    request_id: str | None,
    idempotency_key: str | None = None,
    api_key_id: uuid.UUID | None = None,
    external_event_id: str | None = None,
) -> uuid.UUID | None:
    """Insert the event. Returns None if an event with the same dedupe key exists.

    ON CONFLICT DO NOTHING on the dedupe index has the property that makes
    concurrent duplicates safe: if another transaction has inserted the same
    key but not committed yet, this statement WAITS for it. If that one
    commits, this returns no row; if it rolls back, this insert succeeds.
    """
    statement = insert(InboundEvent).values(
        id=uuid7(),
        kind=kind,
        source=source,
        idempotency_key=idempotency_key,
        api_key_id=api_key_id,
        external_event_id=external_event_id,
        payload_jsonb=payload,
        payload_sha256=payload_sha256,
        request_id=request_id,
    )
    if kind == "direct":
        statement = statement.on_conflict_do_nothing(
            index_elements=["api_key_id", "idempotency_key"],
            index_where=text("idempotency_key IS NOT NULL"),
        )
    else:
        statement = statement.on_conflict_do_nothing(index_elements=["source", "external_event_id"])
    result = await session.execute(statement.returning(InboundEvent.id))
    return result.scalar_one_or_none()


async def find_direct_event(
    session: AsyncSession, *, api_key_id: uuid.UUID, idempotency_key: str
) -> ExistingEvent:
    row = (
        await session.execute(
            select(InboundEvent.id, InboundEvent.payload_sha256).where(
                InboundEvent.api_key_id == api_key_id,
                InboundEvent.idempotency_key == idempotency_key,
            )
        )
    ).one()
    return ExistingEvent(id=row.id, payload_sha256=row.payload_sha256)


async def find_webhook_event(
    session: AsyncSession, *, source: str, external_event_id: str
) -> ExistingEvent:
    row = (
        await session.execute(
            select(InboundEvent.id, InboundEvent.payload_sha256).where(
                InboundEvent.source == source,
                InboundEvent.external_event_id == external_event_id,
            )
        )
    ).one()
    return ExistingEvent(id=row.id, payload_sha256=row.payload_sha256)


async def lead_for_event(session: AsyncSession, event_id: uuid.UUID) -> tuple[uuid.UUID, str]:
    row = (
        await session.execute(select(Lead.id, Lead.status).where(Lead.inbound_event_id == event_id))
    ).one()
    return row.id, row.status


# ----- contacts (business-level dedupe) -----


async def upsert_contact(
    session: AsyncSession, *, email: str | None, phone: str | None, name: str | None
) -> tuple[uuid.UUID, bool]:
    """Find or create the contact. Returns (contact_id, created).

    Email contacts are matched on email; phone-only contacts on phone.
    Existing values are never overwritten, only missing ones filled in.
    `xmax = 0` is true only for a freshly inserted row, which tells us
    whether this was a new contact without a second query.
    """
    if email is None and phone is None:
        raise ValueError("a contact needs an email or a phone number")
    statement = insert(Contact).values(
        id=uuid7(), email_normalized=email, phone_e164=phone, name=name
    )
    excluded = statement.excluded
    fill_missing = {
        "name": func.coalesce(Contact.name, excluded.name),
        "updated_at": func.now(),
    }
    if email is not None:
        statement = statement.on_conflict_do_update(
            index_elements=["email_normalized"],
            set_={
                **fill_missing,
                "phone_e164": func.coalesce(Contact.phone_e164, excluded.phone_e164),
            },
        )
    else:
        statement = statement.on_conflict_do_update(
            index_elements=["phone_e164"],
            index_where=text("email_normalized IS NULL"),
            set_=fill_missing,
        )
    created = literal_column("xmax = 0", Boolean).label("created")
    contact_id, was_created = (
        await session.execute(statement.returning(Contact.id, created))
    ).one()
    return contact_id, bool(was_created)


# ----- lead, workflow run, job, audit -----


async def insert_lead(
    session: AsyncSession,
    *,
    inbound_event_id: uuid.UUID,
    contact_id: uuid.UUID | None,
    source: str,
    raw_message: str,
    submitted_contact: dict[str, str | None],
    contact_issues: list[str],
) -> uuid.UUID:
    lead_id = uuid7()
    await session.execute(
        insert(Lead).values(
            id=lead_id,
            inbound_event_id=inbound_event_id,
            contact_id=contact_id,
            source=source,
            raw_message=raw_message,
            submitted_contact=submitted_contact,
            contact_issues=contact_issues,
        )
    )
    return lead_id


async def insert_workflow_run(
    session: AsyncSession, *, lead_id: uuid.UUID, trigger: str
) -> uuid.UUID:
    run_id = uuid7()
    await session.execute(insert(WorkflowRun).values(id=run_id, lead_id=lead_id, trigger=trigger))
    return run_id


async def enqueue_job(
    session: AsyncSession,
    *,
    workflow_run_id: uuid.UUID,
    job_type: str,
    dedupe_key: str,
    payload: dict[str, Any],
) -> uuid.UUID:
    """Persist a queued job. Nothing executes it until the M3 worker exists."""
    job_id = uuid7()
    await session.execute(
        insert(Job).values(
            id=job_id,
            workflow_run_id=workflow_run_id,
            type=job_type,
            dedupe_key=dedupe_key,
            payload=payload,
        )
    )
    return job_id


async def insert_audit_event(
    session: AsyncSession,
    *,
    event_type: str,
    actor_type: str,
    actor_id: str | None,
    data: dict[str, Any],
    request_id: str | None,
    lead_id: uuid.UUID | None = None,
    workflow_run_id: uuid.UUID | None = None,
) -> None:
    await session.execute(
        insert(AuditEvent).values(
            id=uuid7(),
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            data=data,
            request_id=request_id,
            lead_id=lead_id,
            workflow_run_id=workflow_run_id,
        )
    )


# ----- API keys -----


@dataclass(frozen=True)
class StoredApiKey:
    id: uuid.UUID
    name: str
    prefix: str
    key_sha256: bytes
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


def _stored_key(row: Any) -> StoredApiKey:
    return StoredApiKey(
        id=row.id,
        name=row.name,
        prefix=row.prefix,
        key_sha256=row.key_sha256,
        scopes=list(row.scopes),
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
    )


_KEY_COLUMNS = (
    ApiKey.id,
    ApiKey.name,
    ApiKey.prefix,
    ApiKey.key_sha256,
    ApiKey.scopes,
    ApiKey.created_at,
    ApiKey.last_used_at,
    ApiKey.revoked_at,
)


async def find_api_key_by_prefix(session: AsyncSession, prefix: str) -> StoredApiKey | None:
    row = (await session.execute(select(*_KEY_COLUMNS).where(ApiKey.prefix == prefix))).first()
    return _stored_key(row) if row else None


async def list_api_keys(session: AsyncSession) -> list[StoredApiKey]:
    rows = (await session.execute(select(*_KEY_COLUMNS).order_by(ApiKey.created_at))).all()
    return [_stored_key(row) for row in rows]


async def insert_api_key(
    session: AsyncSession, *, name: str, prefix: str, key_sha256: bytes, scopes: list[str]
) -> uuid.UUID:
    key_id = uuid7()
    await session.execute(
        insert(ApiKey).values(
            id=key_id, name=name, prefix=prefix, key_sha256=key_sha256, scopes=scopes
        )
    )
    return key_id


async def revoke_api_key(session: AsyncSession, name: str) -> StoredApiKey | None:
    row = (
        await session.execute(
            update(ApiKey)
            .where(ApiKey.name == name, ApiKey.revoked_at.is_(None))
            .values(revoked_at=func.now())
            .returning(*_KEY_COLUMNS)
        )
    ).first()
    return _stored_key(row) if row else None


async def touch_api_key(session: AsyncSession, key_id: uuid.UUID) -> None:
    """Record use, at most once a minute per key, to avoid a write per request."""
    await session.execute(
        update(ApiKey)
        .where(
            ApiKey.id == key_id,
            (ApiKey.last_used_at.is_(None))
            | (ApiKey.last_used_at < func.now() - text("interval '1 minute'")),
        )
        .values(last_used_at=func.now())
    )

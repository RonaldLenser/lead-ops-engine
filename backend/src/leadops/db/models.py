"""ORM table definitions (M2: intake).

These classes and migrations/versions/0002_intake_tables.py describe the same
schema. An integration test runs Alembic's autogenerate comparison and fails
if they drift apart.

Constraint names come from the naming convention in db/base.py.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from leadops.db.base import Base
from leadops.ids import uuid7

# Every lead status in docs/state-machine.md. Only RECEIVED is written in M2;
# the full set is constrained now so later milestones do not need a migration
# just to widen this list.
LEAD_STATUSES = (
    "RECEIVED",
    "ANALYZING",
    "QUALIFIED",
    "NEEDS_REVIEW",
    "DISQUALIFIED",
    "SPAM",
    "DRAFTING",
    "AWAITING_APPROVAL",
    "APPROVED",
    "CONTACTED",
    "REPLIED",
    "CLOSED_WON",
    "CLOSED_LOST",
    "CLOSED_NO_RESPONSE",
)
API_KEY_SCOPES = ("leads:write", "delivery:callback")
JOB_STATUSES = ("queued", "running", "succeeded", "failed", "dead")
WORKFLOW_RUN_STATUSES = ("pending", "running", "succeeded", "failed")
ACTOR_TYPES = ("system", "user", "api_key", "webhook", "ai")


def _in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Contact(Base):
    """A person. Several leads (inquiries) can belong to one contact."""

    __tablename__ = "contacts"
    __table_args__ = (
        CheckConstraint(
            "email_normalized IS NOT NULL OR phone_e164 IS NOT NULL", name="has_identifier"
        ),
        # Contacts with an email are deduped by email. Phone-only contacts are
        # deduped by phone. (Email contacts may share a phone number.)
        Index(
            "uq_contacts_phone_e164_without_email",
            "phone_e164",
            unique=True,
            postgresql_where=text("email_normalized IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    email_normalized: Mapped[str | None] = mapped_column(String(254), unique=True)
    phone_e164: Mapped[str | None] = mapped_column(String(16))
    name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _created_at()


class ApiKey(Base):
    """Machine credential. Only the prefix and SHA-256 digest are stored."""

    __tablename__ = "api_keys"
    __table_args__ = (
        CheckConstraint(
            f"scopes <@ ARRAY[{', '.join(repr(s) for s in API_KEY_SCOPES)}]::text[]",
            name="known_scopes",
        ),
        CheckConstraint("cardinality(scopes) > 0", name="has_scopes"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(100), unique=True)
    prefix: Mapped[str] = mapped_column(String(10), unique=True)
    key_sha256: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InboundEvent(Base):
    """One accepted intake request: the transport-level dedupe record.

    Only authenticated, schema-valid requests are stored. payload_jsonb is the
    raw request (may contain personal data) and is purged after
    RAW_EVENT_RETENTION_DAYS; the hash and IDs stay so dedupe keeps working.
    """

    __tablename__ = "inbound_events"
    __table_args__ = (
        UniqueConstraint("source", "external_event_id"),
        Index(
            "uq_inbound_events_api_key_id_idempotency_key",
            "api_key_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        CheckConstraint(
            "(kind = 'direct' AND idempotency_key IS NOT NULL AND api_key_id IS NOT NULL"
            " AND external_event_id IS NULL)"
            " OR (kind = 'webhook' AND external_event_id IS NOT NULL AND idempotency_key IS NULL)",
            name="dedupe_key_matches_kind",
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    kind: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(64))
    external_event_id: Mapped[str | None] = mapped_column(String(200))
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_keys.id")
    )
    payload_jsonb: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    payload_sha256: Mapped[bytes] = mapped_column(LargeBinary(32))
    request_id: Mapped[str | None] = mapped_column(String(64))
    received_at: Mapped[datetime] = _created_at()
    payload_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Lead(Base):
    """One inquiry. Status changes only through the lifecycle module (M3)."""

    __tablename__ = "leads"
    __table_args__ = (CheckConstraint(_in("status", LEAD_STATUSES), name="known_status"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    inbound_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inbound_events.id"), unique=True
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id"), index=True
    )
    source: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), server_default="RECEIVED")
    raw_message: Mapped[str] = mapped_column(Text)
    # Contact fields exactly as submitted (trimmed), including ones that
    # failed normalization, so nothing the lead typed is lost.
    submitted_contact: Mapped[dict[str, Any]] = mapped_column(JSONB)
    contact_issues: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _created_at()


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (CheckConstraint(_in("status", WORKFLOW_RUN_STATUSES), name="known_status"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id"), index=True
    )
    trigger: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    created_at: Mapped[datetime] = _created_at()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class Job(Base):
    """Queued work. M2 only inserts rows; the worker that runs them is M3."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(_in("status", JOB_STATUSES), name="known_status"),
        CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="attempt_bounds"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id"), index=True
    )
    type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(String(16), server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, server_default="5")
    run_at: Mapped[datetime] = _created_at()
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _created_at()


class AuditEvent(Base):
    """Append-only record of what happened and who did it.

    The migration revokes UPDATE, DELETE, and TRUNCATE from the application
    role, so the app cannot rewrite history even if its code tried.
    """

    __tablename__ = "audit_events"
    __table_args__ = (CheckConstraint(_in("actor_type", ACTOR_TYPES), name="known_actor_type"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id"), index=True
    )
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id")
    )
    actor_type: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[str | None] = mapped_column(String(100))
    event_type: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created_at()

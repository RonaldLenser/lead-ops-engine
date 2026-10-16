"""Intake tables: contacts, api_keys, inbound_events, leads, workflow_runs, jobs, audit_events.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15

Design: docs/DESIGN.md section 5. Matches src/leadops/db/models.py; an
integration test fails if the two drift apart.

Beyond the tables, this migration makes audit_events append-only for the
application role (no UPDATE, DELETE, or TRUNCATE). The role is looked up by
name, so the step is skipped on a database that has no leadops_app role.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_REVOKE_AUDIT_WRITES = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'leadops_app') THEN
        REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM leadops_app;
    END IF;
END
$$;
"""


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("prefix", sa.String(length=10), nullable=False),
        sa.Column("key_sha256", sa.LargeBinary(length=32), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "scopes <@ ARRAY['leads:write', 'delivery:callback']::text[]",
            name=op.f("ck_api_keys_known_scopes"),
        ),
        sa.CheckConstraint("cardinality(scopes) > 0", name=op.f("ck_api_keys_has_scopes")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_keys")),
        sa.UniqueConstraint("key_sha256", name=op.f("uq_api_keys_key_sha256")),
        sa.UniqueConstraint("name", name=op.f("uq_api_keys_name")),
        sa.UniqueConstraint("prefix", name=op.f("uq_api_keys_prefix")),
    )
    op.create_table(
        "contacts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email_normalized", sa.String(length=254), nullable=True),
        sa.Column("phone_e164", sa.String(length=16), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "email_normalized IS NOT NULL OR phone_e164 IS NOT NULL",
            name=op.f("ck_contacts_has_identifier"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contacts")),
        sa.UniqueConstraint("email_normalized", name=op.f("uq_contacts_email_normalized")),
    )
    op.create_index(
        "uq_contacts_phone_e164_without_email",
        "contacts",
        ["phone_e164"],
        unique=True,
        postgresql_where=sa.text("email_normalized IS NULL"),
    )
    op.create_table(
        "inbound_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("external_event_id", sa.String(length=200), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("api_key_id", sa.UUID(), nullable=True),
        sa.Column("payload_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("payload_sha256", sa.LargeBinary(length=32), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("payload_purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(kind = 'direct' AND idempotency_key IS NOT NULL AND api_key_id IS NOT NULL"
            " AND external_event_id IS NULL)"
            " OR (kind = 'webhook' AND external_event_id IS NOT NULL AND idempotency_key IS NULL)",
            name=op.f("ck_inbound_events_dedupe_key_matches_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["api_key_id"], ["api_keys.id"], name=op.f("fk_inbound_events_api_key_id_api_keys")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inbound_events")),
        sa.UniqueConstraint(
            "source", "external_event_id", name=op.f("uq_inbound_events_source_external_event_id")
        ),
    )
    op.create_index(
        "uq_inbound_events_api_key_id_idempotency_key",
        "inbound_events",
        ["api_key_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_table(
        "leads",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("inbound_event_id", sa.UUID(), nullable=False),
        sa.Column("contact_id", sa.UUID(), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="RECEIVED", nullable=False),
        sa.Column("raw_message", sa.Text(), nullable=False),
        sa.Column("submitted_contact", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "contact_issues",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('RECEIVED', 'ANALYZING', 'QUALIFIED', 'NEEDS_REVIEW', 'DISQUALIFIED',"
            " 'SPAM', 'DRAFTING', 'AWAITING_APPROVAL', 'APPROVED', 'CONTACTED', 'REPLIED',"
            " 'CLOSED_WON', 'CLOSED_LOST', 'CLOSED_NO_RESPONSE')",
            name=op.f("ck_leads_known_status"),
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], name=op.f("fk_leads_contact_id_contacts")
        ),
        sa.ForeignKeyConstraint(
            ["inbound_event_id"],
            ["inbound_events.id"],
            name=op.f("fk_leads_inbound_event_id_inbound_events"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_leads")),
        sa.UniqueConstraint("inbound_event_id", name=op.f("uq_leads_inbound_event_id")),
    )
    op.create_index(op.f("ix_leads_contact_id"), "leads", ["contact_id"], unique=False)
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("lead_id", sa.UUID(), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name=op.f("ck_workflow_runs_known_status"),
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["leads.id"], name=op.f("fk_workflow_runs_lead_id_leads")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_runs")),
    )
    op.create_index(op.f("ix_workflow_runs_lead_id"), "workflow_runs", ["lead_id"], unique=False)
    op.create_table(
        "audit_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("lead_id", sa.UUID(), nullable=True),
        sa.Column("workflow_run_id", sa.UUID(), nullable=True),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "actor_type IN ('system', 'user', 'api_key', 'webhook', 'ai')",
            name=op.f("ck_audit_events_known_actor_type"),
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["leads.id"], name=op.f("fk_audit_events_lead_id_leads")
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["workflow_runs.id"],
            name=op.f("fk_audit_events_workflow_run_id_workflow_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(op.f("ix_audit_events_lead_id"), "audit_events", ["lead_id"], unique=False)
    op.create_table(
        "jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workflow_run_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
        sa.Column(
            "run_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'dead')",
            name=op.f("ck_jobs_known_status"),
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND max_attempts >= 1", name=op.f("ck_jobs_attempt_bounds")
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["workflow_runs.id"],
            name=op.f("fk_jobs_workflow_run_id_workflow_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.UniqueConstraint("dedupe_key", name=op.f("uq_jobs_dedupe_key")),
    )
    op.create_index(op.f("ix_jobs_workflow_run_id"), "jobs", ["workflow_run_id"], unique=False)

    # History cannot be rewritten by the application, even by a bug or a
    # compromised process: it may only INSERT and SELECT audit rows.
    op.execute(_REVOKE_AUDIT_WRITES)


def downgrade() -> None:
    op.drop_index(op.f("ix_jobs_workflow_run_id"), table_name="jobs")
    op.drop_table("jobs")
    op.drop_index(op.f("ix_audit_events_lead_id"), table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index(op.f("ix_workflow_runs_lead_id"), table_name="workflow_runs")
    op.drop_table("workflow_runs")
    op.drop_index(op.f("ix_leads_contact_id"), table_name="leads")
    op.drop_table("leads")
    op.drop_index(
        "uq_inbound_events_api_key_id_idempotency_key",
        table_name="inbound_events",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.drop_table("inbound_events")
    op.drop_index(
        "uq_contacts_phone_e164_without_email",
        table_name="contacts",
        postgresql_where=sa.text("email_normalized IS NULL"),
    )
    op.drop_table("contacts")
    op.drop_table("api_keys")

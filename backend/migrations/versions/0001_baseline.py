"""Baseline: an empty schema under version control.

Revision ID: 0001
Revises:
Create Date: 2026-10-15

Creates no tables. It exists so that:
- every environment has an alembic_version row from day one
- /readyz can verify the applied revision before any domain table exists
- the first real migration (M2) has a parent revision to build on

Domain tables arrive in M2.
"""

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

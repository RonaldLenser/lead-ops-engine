"""Which database schema revision this code expects, and how to check it.

SCHEMA_REVISION must equal the newest Alembic revision in migrations/versions.
A unit test (tests/unit/test_schema_revision.py) fails the build if a
migration is added without updating it, so the two cannot drift apart.

Why a constant instead of reading the migrations folder at runtime: the
installed package does not ship the migrations folder, and readiness must
work the same in a container, in CI, and on a laptop.
"""

import asyncio
from dataclasses import dataclass
from typing import Literal

import structlog
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

SCHEMA_REVISION = "0001"

MigrationState = Literal["current", "outdated", "unknown"]

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class DatabaseCheck:
    reachable: bool
    migrations: MigrationState


async def check_database(engine: AsyncEngine, timeout_seconds: float) -> DatabaseCheck:
    """Connect, read the applied Alembic revision, compare it with SCHEMA_REVISION."""
    try:
        async with asyncio.timeout(timeout_seconds), engine.connect() as connection:
            applied = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    except ProgrammingError:
        # Connected, but alembic_version does not exist: migrations never ran.
        logger.warning("readiness_migrations_missing")
        return DatabaseCheck(reachable=True, migrations="outdated")
    except (TimeoutError, SQLAlchemyError, OSError) as exc:
        # Log the error type only: driver messages can contain hostnames or usernames.
        logger.warning("readiness_database_unreachable", error_type=type(exc).__name__)
        return DatabaseCheck(reachable=False, migrations="unknown")

    if applied != SCHEMA_REVISION:
        logger.warning("readiness_migrations_mismatch", applied=applied, expected=SCHEMA_REVISION)
        return DatabaseCheck(reachable=True, migrations="outdated")
    return DatabaseCheck(reachable=True, migrations="current")

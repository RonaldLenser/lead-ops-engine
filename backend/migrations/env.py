"""Alembic environment: how migrations connect to the database.

Migrations run as the schema-owner role (MIGRATION_DATABASE_URL), not as the
application role, which has no permission to create or alter tables. If
MIGRATION_DATABASE_URL is unset, DATABASE_URL is used (only sensible locally).

Runs on the async engine, then hands Alembic a synchronous view of the
connection, because Alembic's migration API is synchronous.
"""

import asyncio

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from leadops.config import get_settings
from leadops.db.base import Base
from leadops.logging_config import configure_logging

config = context.config
# Same structured logging as the app (JSON outside local). Tests that run
# migrations in-process set configure_logger=False to keep their own setup.
if config.attributes.get("configure_logger", True):
    _settings = get_settings()
    configure_logging(_settings.log_level, json_logs=_settings.json_logs)

target_metadata = Base.metadata


def _migration_url() -> str:
    return get_settings().effective_migration_url.get_secret_value()


def _run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    engine = create_async_engine(_migration_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run_migrations)
    await engine.dispose()


def run_migrations_offline() -> None:
    """Generate SQL without connecting (`alembic upgrade head --sql`)."""
    context.configure(url=_migration_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(_run_async_migrations())

"""Fixtures for integration tests: everything in this folder needs PostgreSQL."""

import asyncio
import os
import socket
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from leadops.config import Settings
from leadops.main import create_app
from tests.conftest import make_settings
from tests.db_guard import UnsafeTestDatabaseError, check_destructive_target, check_server_database
from tests.integration.helpers import ApiKeyFactory, make_api_key_factory

BACKEND_DIR = Path(__file__).resolve().parents[2]
WEBHOOK_SECRET = "test-webhook-secret-0123456789abcdef"  # 32+ chars
ROTATED_WEBHOOK_SECRET = "test-webhook-secret-rotated-0123456789"
TABLES = (
    "audit_events",
    "jobs",
    "workflow_runs",
    "leads",
    "inbound_events",
    "contacts",
    "api_keys",
)


def alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    # Keep the test run's logging setup; don't let env.py reconfigure it.
    config.attributes["configure_logger"] = False
    return config


def _database_reachable(database_url: str) -> bool:
    parts = urlsplit(database_url)
    try:
        with socket.create_connection((parts.hostname or "localhost", parts.port or 5432), 1):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session", autouse=True)
def require_database() -> None:
    """Skip this folder locally when Postgres is down; FAIL it in CI (REQUIRE_DB=1)."""
    url = os.environ["DATABASE_URL"]
    if _database_reachable(url):
        return
    parts = urlsplit(url)
    message = f"PostgreSQL not reachable at {parts.hostname}:{parts.port}"
    if os.environ.get("REQUIRE_DB") == "1":
        pytest.fail(message)
    pytest.skip(f"{message} (start it: docker compose -f infra/docker-compose.yml up -d db)")


@pytest.fixture(scope="session", autouse=True)
def destructive_guard(require_database: None) -> None:
    """Hard stop before any reset unless every guard condition holds (tests/db_guard.py)."""
    try:
        for name in ("DATABASE_URL", "MIGRATION_DATABASE_URL"):
            check_destructive_target(os.environ[name], os.environ)
        asyncio.run(check_server_database(os.environ["MIGRATION_DATABASE_URL"]))
    except UnsafeTestDatabaseError as exc:
        pytest.fail(str(exc), pytrace=False)


@pytest.fixture(scope="session", autouse=True)
def migrated(destructive_guard: None) -> None:
    """Rebuild the schema from zero once per run: downgrade to base, upgrade to head.

    Doubles as a round-trip test: both directions of every migration run.
    """
    config = alembic_config()
    command.downgrade(config, "base")
    command.upgrade(config, "head")


async def _truncate_all() -> None:
    # The migrator owns the tables; the app role cannot TRUNCATE (by design).
    engine = create_async_engine(os.environ["MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f"TRUNCATE {', '.join(TABLES)} CASCADE"))
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables(migrated: None) -> None:
    """Every test starts with empty tables, so tests cannot affect each other."""
    asyncio.run(_truncate_all())


@pytest.fixture
def api_settings() -> Settings:
    return make_settings(
        webhook_secrets={"website_form": [WEBHOOK_SECRET, ROTATED_WEBHOOK_SECRET]},
    )


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(api_settings)) as test_client:
        yield test_client


@pytest.fixture
def api_keys() -> ApiKeyFactory:
    return make_api_key_factory(os.environ["DATABASE_URL"])

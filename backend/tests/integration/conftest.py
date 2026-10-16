"""Fixtures for integration tests: everything in this folder needs PostgreSQL."""

import os
import socket
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parents[2]


def alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    # Keep the test run's logging setup; don't let alembic.ini reconfigure it.
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
def migrated(require_database: None) -> None:
    """Rebuild the schema from zero once per run: downgrade to base, upgrade to head.

    Doubles as a round-trip test: both directions of every migration run.
    """
    config = alembic_config()
    command.downgrade(config, "base")
    command.upgrade(config, "head")

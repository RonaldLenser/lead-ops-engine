"""Shared test fixtures.

Unit tests (tests/unit) never need a database.

Integration tests (tests/integration, auto-marked `integration`) need the
PostgreSQL from infra/docker-compose.yml, with its two roles:
  - Locally: `docker compose -f infra/docker-compose.yml up -d db`, then `uv run pytest`.
    If the database is not running, integration tests are SKIPPED.
  - In CI: REQUIRE_DB=1, so a missing database FAILS the run instead of
    silently skipping it.
"""

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from leadops.config import Settings, get_settings
from leadops.main import create_app

LOCAL_APP_DATABASE_URL = "postgresql+asyncpg://leadops_app:leadops_app_dev@localhost:5434/leadops"
LOCAL_MIGRATION_DATABASE_URL = (
    "postgresql+asyncpg://leadops_migrator:leadops_migrator_dev@localhost:5434/leadops"
)

# Alembic's env.py reads Settings from the environment, so these must be set.
os.environ.setdefault("DATABASE_URL", LOCAL_APP_DATABASE_URL)
os.environ.setdefault("MIGRATION_DATABASE_URL", LOCAL_MIGRATION_DATABASE_URL)


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Settings are cached per process; reset between tests so env changes apply."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def make_settings(**overrides: object) -> Settings:
    """Settings for tests: never reads a developer's local .env file."""
    values: dict[str, object] = {
        "app_env": "test",
        "database_url": os.environ["DATABASE_URL"],
        "migration_database_url": os.environ["MIGRATION_DATABASE_URL"],
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg, arg-type]


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    # `with` runs the app's lifespan (startup and shutdown), like a real server.
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test under tests/integration/ so `pytest -m "not integration"` works."""
    for item in items:
        if "integration" in item.path.parts:
            item.add_marker(pytest.mark.integration)

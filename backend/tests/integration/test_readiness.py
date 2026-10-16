from collections.abc import Iterator

import pytest
from alembic import command
from fastapi.testclient import TestClient

from tests.integration.conftest import alembic_config


def test_readyz_is_ready_when_database_is_up_and_migrated(client: TestClient) -> None:
    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok", "migrations": "current"}


@pytest.fixture
def unmigrated_database() -> Iterator[None]:
    """Roll the schema back to nothing for one test, then restore it."""
    config = alembic_config()
    command.downgrade(config, "base")
    try:
        yield
    finally:
        command.upgrade(config, "head")


@pytest.mark.usefixtures("unmigrated_database")
def test_readyz_is_unavailable_when_migrations_have_not_run(client: TestClient) -> None:
    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "database": "ok",
        "migrations": "outdated",
    }

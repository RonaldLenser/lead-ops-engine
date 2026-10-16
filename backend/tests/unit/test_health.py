from fastapi.testclient import TestClient

from leadops import __version__
from leadops.main import create_app
from tests.conftest import make_settings

# Port 1 on localhost: nothing listens there, so connecting fails immediately.
UNREACHABLE_DATABASE_URL = "postgresql+asyncpg://leadops_app:x@127.0.0.1:1/leadops"


def test_healthz_is_ok_without_touching_the_database() -> None:
    settings = make_settings(database_url=UNREACHABLE_DATABASE_URL)

    with TestClient(create_app(settings)) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_readyz_returns_503_when_the_database_is_unreachable() -> None:
    settings = make_settings(database_url=UNREACHABLE_DATABASE_URL)

    with TestClient(create_app(settings)) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "database": "unreachable",
        "migrations": "unknown",
    }
    assert "127.0.0.1" not in response.text

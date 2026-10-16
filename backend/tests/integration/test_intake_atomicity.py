"""The intake transaction is all or nothing."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from leadops.config import Settings
from leadops.db import repositories as repo
from leadops.main import create_app
from tests.integration.helpers import ApiKeyFactory, bearer, counts

LEAD = {"source": "website_form", "message": "Need a website", "email": "jane@example.com"}


class SimulatedCrashError(RuntimeError):
    pass


@pytest.fixture
def crashing_api(api_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Fail at the LAST step of the transaction (the audit insert)."""

    async def explode(*_: Any, **__: Any) -> None:
        raise SimulatedCrashError("database went away mid-transaction")

    monkeypatch.setattr(repo, "insert_audit_event", explode)
    with TestClient(create_app(api_settings), raise_server_exceptions=False) as client:
        yield client


def test_failure_on_the_last_step_leaves_no_partial_rows(
    crashing_api: TestClient, api_keys: ApiKeyFactory
) -> None:
    key = api_keys()

    response = crashing_api.post("/v1/leads", json=LEAD, headers=bearer(key, "atomic"))

    assert response.status_code == 500
    assert counts() == {
        "inbound_events": 0,
        "contacts": 0,
        "leads": 0,
        "workflow_runs": 0,
        "jobs": 0,
        "audit_events": 0,
    }


def test_a_failed_attempt_does_not_burn_the_idempotency_key(
    crashing_api: TestClient, api_keys: ApiKeyFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = api_keys()
    crashing_api.post("/v1/leads", json=LEAD, headers=bearer(key, "retry-after-crash"))

    monkeypatch.undo()  # the "database" recovers
    retry = crashing_api.post("/v1/leads", json=LEAD, headers=bearer(key, "retry-after-crash"))

    assert retry.status_code == 202
    assert retry.json()["duplicate"] is False
    assert counts()["leads"] == 1

"""`leadops api-keys ...` against the real database."""

import pytest
from fastapi.testclient import TestClient

from leadops.cli import main
from tests.integration.helpers import bearer, query

LEAD = {"source": "website_form", "message": "Need a website"}


@pytest.fixture(autouse=True)
def _keep_test_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() configures logging for a real terminal; keep the test's own setup."""
    monkeypatch.setattr("leadops.cli.configure_logging", lambda *_, **__: None)


def _create(capsys: pytest.CaptureFixture[str], name: str = "n8n-intake") -> str:
    assert main(["api-keys", "create", "--name", name, "--scope", "leads:write"]) == 0
    return capsys.readouterr().out.strip().splitlines()[-1]


def test_created_key_is_printed_once_stored_hashed_and_works(
    api: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    full_key = _create(capsys)

    [row] = query("SELECT name, prefix, scopes, key_sha256 FROM api_keys")
    assert row.name == "n8n-intake"
    assert full_key.startswith(f"lok_{row.prefix}_")
    assert full_key.encode() not in bytes(row.key_sha256)
    assert api.post("/v1/leads", json=LEAD, headers=bearer(full_key)).status_code == 202


def test_list_never_shows_the_secret(capsys: pytest.CaptureFixture[str]) -> None:
    full_key = _create(capsys)

    assert main(["api-keys", "list"]) == 0
    listing = capsys.readouterr().out

    assert "n8n-intake" in listing
    assert full_key.split("_", 2)[2] not in listing


def test_revoked_key_stops_working_and_both_actions_are_audited(
    api: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    full_key = _create(capsys)

    assert main(["api-keys", "revoke", "--name", "n8n-intake"]) == 0

    assert api.post("/v1/leads", json=LEAD, headers=bearer(full_key)).status_code == 401
    events = [row.event_type for row in query("SELECT event_type FROM audit_events ORDER BY id")]
    assert sorted(events) == ["api_key.created", "api_key.revoked"]


def test_duplicate_names_and_unknown_revokes_fail_cleanly(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _create(capsys)

    duplicate = main(["api-keys", "create", "--name", "n8n-intake", "--scope", "leads:write"])
    unknown = main(["api-keys", "revoke", "--name", "nope"])

    assert (duplicate, unknown) == (1, 1)
    assert len(query("SELECT id FROM api_keys")) == 1

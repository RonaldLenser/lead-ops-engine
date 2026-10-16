"""POST /v1/webhooks/leads/{source}: signature checks and event dedupe."""

import time

from fastapi.testclient import TestClient

from leadops.integrations.signing import SIGNATURE_HEADER
from tests.integration.conftest import ROTATED_WEBHOOK_SECRET, WEBHOOK_SECRET
from tests.integration.helpers import counts, query, signed

URL = "/v1/webhooks/leads/website_form"
EVENT = {
    "event_id": "evt_001",
    "message": "Looking for an AI receptionist for my HVAC company",
    "email": "owner@hvac-example.com",
}


def test_signed_event_is_accepted(api: TestClient) -> None:
    body, headers = signed(EVENT, WEBHOOK_SECRET)

    response = api.post(URL, content=body, headers=headers)

    assert response.status_code == 202
    assert response.json()["duplicate"] is False
    [event] = query("SELECT kind, source, external_event_id, idempotency_key FROM inbound_events")
    assert tuple(event) == ("webhook", "website_form", "evt_001", None)
    [audit] = query("SELECT actor_type, actor_id FROM audit_events")
    assert tuple(audit) == ("webhook", "website_form")


def test_rotated_secret_is_also_accepted(api: TestClient) -> None:
    body, headers = signed(EVENT, ROTATED_WEBHOOK_SECRET)

    assert api.post(URL, content=body, headers=headers).status_code == 202


def test_redelivered_event_returns_the_original_lead(api: TestClient) -> None:
    body, headers = signed(EVENT, WEBHOOK_SECRET)
    first = api.post(URL, content=body, headers=headers)

    body, headers = signed(EVENT, WEBHOOK_SECRET)  # fresh timestamp, same event
    second = api.post(URL, content=body, headers=headers)

    assert second.status_code == 202
    assert second.json() == {**first.json(), "duplicate": True}
    assert counts()["leads"] == 1


def test_same_event_id_with_different_content_is_a_conflict(api: TestClient) -> None:
    body, headers = signed(EVENT, WEBHOOK_SECRET)
    api.post(URL, content=body, headers=headers)

    body, headers = signed({**EVENT, "message": "changed"}, WEBHOOK_SECRET)
    response = api.post(URL, content=body, headers=headers)

    assert response.status_code == 409
    assert counts()["leads"] == 1


def test_wrong_secret_is_rejected_and_nothing_is_stored(api: TestClient) -> None:
    body, headers = signed(EVENT, "some-other-secret-of-sufficient-length")

    response = api.post(URL, content=body, headers=headers)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_signature"
    assert counts()["inbound_events"] == 0


def test_body_changed_after_signing_is_rejected(api: TestClient) -> None:
    body, headers = signed(EVENT, WEBHOOK_SECRET)
    tampered = body.replace(b"HVAC", b"hvac")

    assert api.post(URL, content=tampered, headers=headers).status_code == 401


def test_stale_timestamp_is_rejected_even_with_a_valid_signature(api: TestClient) -> None:
    body, headers = signed(EVENT, WEBHOOK_SECRET, timestamp=int(time.time()) - 301)

    assert api.post(URL, content=body, headers=headers).status_code == 401


def test_missing_signature_headers_are_rejected(api: TestClient) -> None:
    response = api.post(URL, json=EVENT)

    assert response.status_code == 401
    assert counts()["inbound_events"] == 0


def test_malformed_signature_is_rejected(api: TestClient) -> None:
    body, headers = signed(EVENT, WEBHOOK_SECRET)
    headers[SIGNATURE_HEADER] = "sha256=abc"

    assert api.post(URL, content=body, headers=headers).status_code == 401


def test_unknown_source_is_404(api: TestClient) -> None:
    body, headers = signed(EVENT, WEBHOOK_SECRET)

    response = api.post("/v1/webhooks/leads/not_configured", content=body, headers=headers)

    assert response.status_code == 404


def test_signed_but_invalid_payload_is_422(api: TestClient) -> None:
    body, headers = signed({"message": "no event id"}, WEBHOOK_SECRET)

    assert api.post(URL, content=body, headers=headers).status_code == 422

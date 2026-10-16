"""POST /v1/leads end to end against PostgreSQL."""

import json
import uuid

from fastapi.testclient import TestClient

from tests.integration.helpers import ApiKeyFactory, bearer, counts, query

LEAD = {
    "source": "website_form",
    "message": "Need a new site for my plumbing business in Stafford, ASAP.",
    "name": "Jane Prospect",
    "email": "Jane.Prospect@Example.com ",
    "phone": "(540) 395-0123",
}


def test_accepts_a_lead_and_writes_every_row_in_one_go(
    api: TestClient, api_keys: ApiKeyFactory
) -> None:
    key = api_keys()

    response = api.post("/v1/leads", json=LEAD, headers=bearer(key))

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "RECEIVED"
    assert body["duplicate"] is False
    lead_id = uuid.UUID(body["lead_id"])
    assert lead_id.version == 7
    assert counts() == {
        "inbound_events": 1,
        "contacts": 1,
        "leads": 1,
        "workflow_runs": 1,
        "jobs": 1,
        "audit_events": 1,
    }
    [contact] = query("SELECT email_normalized, phone_e164, name FROM contacts")
    assert tuple(contact) == ("jane.prospect@example.com", "+15403950123", "Jane Prospect")
    [job] = query("SELECT type, status, dedupe_key, payload FROM jobs")
    assert tuple(job) == (
        "analyze_lead",
        "queued",
        f"analyze_lead:{lead_id}",
        {"lead_id": str(lead_id)},
    )
    [run] = query("SELECT trigger, status FROM workflow_runs")
    assert tuple(run) == ("intake", "pending")


def test_audit_event_records_ids_and_flags_but_no_personal_data(
    api: TestClient, api_keys: ApiKeyFactory
) -> None:
    key = api_keys()

    api.post("/v1/leads", json=LEAD, headers=bearer(key))

    [audit] = query("SELECT event_type, actor_type, actor_id, data FROM audit_events")
    event_type, actor_type, actor_id, data = audit
    assert (event_type, actor_type) == ("lead.received", "api_key")
    assert actor_id == key.split("_")[1]  # the public prefix, never the key
    assert data["contact_created"] is True
    serialized = json.dumps(data).lower()
    assert "jane" not in serialized
    assert "395" not in serialized


def test_retry_with_same_key_and_content_returns_the_original_lead(
    api: TestClient, api_keys: ApiKeyFactory
) -> None:
    key = api_keys()
    first = api.post("/v1/leads", json=LEAD, headers=bearer(key, "retry-me"))

    # Same meaning, different formatting: key order and whitespace do not matter.
    reordered = {"phone": " (540) 395-0123", **{k: v for k, v in LEAD.items() if k != "phone"}}
    second = api.post("/v1/leads", json=reordered, headers=bearer(key, "retry-me"))

    assert second.status_code == 202
    assert second.json() == {**first.json(), "duplicate": True}
    assert counts()["leads"] == 1
    assert counts()["audit_events"] == 1


def test_same_idempotency_key_with_different_content_is_a_conflict(
    api: TestClient, api_keys: ApiKeyFactory
) -> None:
    key = api_keys()
    api.post("/v1/leads", json=LEAD, headers=bearer(key, "k1"))

    response = api.post(
        "/v1/leads", json={**LEAD, "message": "Something else"}, headers=bearer(key, "k1")
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_conflict"
    assert counts()["leads"] == 1


def test_idempotency_keys_are_scoped_per_api_key(api: TestClient, api_keys: ApiKeyFactory) -> None:
    first_key = api_keys("client-a")
    second_key = api_keys("client-b")

    one = api.post("/v1/leads", json=LEAD, headers=bearer(first_key, "shared"))
    two = api.post("/v1/leads", json=LEAD, headers=bearer(second_key, "shared"))

    assert one.json()["lead_id"] != two.json()["lead_id"]
    assert two.json()["duplicate"] is False


def test_same_person_again_is_a_new_lead_on_the_same_contact(
    api: TestClient, api_keys: ApiKeyFactory
) -> None:
    key = api_keys()

    api.post("/v1/leads", json=LEAD, headers=bearer(key, "first"))
    api.post(
        "/v1/leads",
        json={**LEAD, "email": "jane.prospect@example.com", "message": "Also need a logo"},
        headers=bearer(key, "second"),
    )

    assert counts()["contacts"] == 1
    assert counts()["leads"] == 2
    [[created_flags]] = query(
        "SELECT array_agg((data->>'contact_created')::bool) FROM audit_events"
    )
    assert sorted(created_flags) == [False, True]


def test_unusable_contact_details_are_kept_on_the_lead_not_rejected(
    api: TestClient, api_keys: ApiKeyFactory
) -> None:
    key = api_keys()

    response = api.post(
        "/v1/leads",
        json={
            "source": "website_form",
            "message": "call me",
            "email": "not-an-email",
            "phone": "12",
        },
        headers=bearer(key),
    )

    assert response.status_code == 202
    [lead] = query("SELECT contact_id, contact_issues, submitted_contact FROM leads")
    assert lead.contact_id is None
    assert lead.contact_issues == ["email_invalid", "phone_invalid"]
    assert lead.submitted_contact == {"name": None, "email": "not-an-email", "phone": "12"}
    assert counts()["contacts"] == 0


def test_phone_only_leads_dedupe_on_phone(api: TestClient, api_keys: ApiKeyFactory) -> None:
    key = api_keys()
    lead = {"source": "website_form", "message": "call me back", "phone": "540-395-0123"}

    api.post("/v1/leads", json=lead, headers=bearer(key, "a"))
    api.post("/v1/leads", json={**lead, "phone": "+1 540 395 0123"}, headers=bearer(key, "b"))

    assert counts()["contacts"] == 1
    assert counts()["leads"] == 2


# ----- request validation -----


def test_missing_or_malformed_idempotency_key_is_rejected(
    api: TestClient, api_keys: ApiKeyFactory
) -> None:
    key = api_keys()

    missing = api.post("/v1/leads", json=LEAD, headers=bearer(key, None))
    malformed = api.post("/v1/leads", json=LEAD, headers=bearer(key, "has spaces"))

    assert missing.status_code == malformed.status_code == 400
    assert counts()["inbound_events"] == 0


def test_invalid_json_and_non_objects_are_400(api: TestClient, api_keys: ApiKeyFactory) -> None:
    key = api_keys()

    bad_json = api.post("/v1/leads", content=b"{not json", headers=bearer(key))
    array = api.post("/v1/leads", json=[LEAD], headers=bearer(key))

    assert bad_json.status_code == array.status_code == 400


def test_schema_errors_are_422_without_echoing_input(
    api: TestClient, api_keys: ApiKeyFactory
) -> None:
    key = api_keys()

    response = api.post(
        "/v1/leads",
        json={**LEAD, "source": "Bad Source!", "unexpected": "jane@example.com"},
        headers=bearer(key),
    )

    assert response.status_code == 422
    locations = {tuple(detail["loc"]) for detail in response.json()["error"]["details"]}
    assert locations == {("body", "source"), ("body", "unexpected")}
    assert "jane@example.com" not in response.text
    assert counts()["inbound_events"] == 0


def test_body_over_32kb_is_rejected_before_parsing(
    api: TestClient, api_keys: ApiKeyFactory
) -> None:
    key = api_keys()

    response = api.post("/v1/leads", json={**LEAD, "message": "x" * 40_000}, headers=bearer(key))

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert response.headers["X-Request-ID"] == response.json()["error"]["request_id"]
    assert counts()["inbound_events"] == 0


# ----- authentication -----


def test_missing_credentials_are_401_with_bearer_challenge(api: TestClient) -> None:
    response = api.post("/v1/leads", json=LEAD, headers={"Idempotency-Key": "k"})

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_wrong_secret_unknown_prefix_garbage_and_revoked_keys_all_look_the_same(
    api: TestClient, api_keys: ApiKeyFactory
) -> None:
    good = api_keys("good")
    revoked = api_keys("old", revoked=True)
    wrong_secret = good[:-4] + ("AAAA" if not good.endswith("AAAA") else "BBBB")
    unknown_prefix = "lok_0000000000_" + good.split("_", 2)[2]

    responses = [
        api.post("/v1/leads", json=LEAD, headers=bearer(candidate))
        for candidate in (wrong_secret, unknown_prefix, "not-a-lok-key", revoked)
    ]

    assert {r.status_code for r in responses} == {401}
    assert len({r.json()["error"]["message"] for r in responses}) == 1
    assert counts()["inbound_events"] == 0


def test_key_without_the_leads_write_scope_is_403(api: TestClient, api_keys: ApiKeyFactory) -> None:
    key = api_keys("callback-only", scopes=("delivery:callback",))

    response = api.post("/v1/leads", json=LEAD, headers=bearer(key))

    assert response.status_code == 403
    assert counts()["inbound_events"] == 0


def test_successful_use_records_last_used_at(api: TestClient, api_keys: ApiKeyFactory) -> None:
    key = api_keys()

    api.post("/v1/leads", json=LEAD, headers=bearer(key))

    [[last_used]] = query("SELECT last_used_at FROM api_keys")
    assert last_used is not None

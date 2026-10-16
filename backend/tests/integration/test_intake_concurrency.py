"""Concurrent duplicate requests against the real database.

These run many requests at the same moment through one app (one event loop,
separate database connections), which is how retries and webhook
redeliveries actually collide in production.
"""

import asyncio
from collections import Counter

import httpx2

from leadops.config import Settings
from leadops.main import create_app
from tests.integration.helpers import ApiKeyFactory, bearer, counts, query, signed

CONCURRENCY = 10
LEAD = {"source": "website_form", "message": "Need a website", "email": "same@example.com"}


async def _fire(settings: Settings, requests: list[dict[str, object]]) -> list[httpx2.Response]:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
            return list(
                await asyncio.gather(
                    *(client.post(**request) for request in requests)  # type: ignore[arg-type]
                )
            )


def test_ten_identical_direct_requests_create_exactly_one_lead(
    api_settings: Settings, api_keys: ApiKeyFactory
) -> None:
    key = api_keys()
    request: dict[str, object] = {
        "url": "/v1/leads",
        "json": LEAD,
        "headers": bearer(key, "same-key"),
    }

    responses = asyncio.run(_fire(api_settings, [request] * CONCURRENCY))

    assert {r.status_code for r in responses} == {202}
    assert len({r.json()["lead_id"] for r in responses}) == 1
    assert Counter(r.json()["duplicate"] for r in responses) == {
        False: 1,
        True: CONCURRENCY - 1,
    }
    assert counts() == {
        "inbound_events": 1,
        "contacts": 1,
        "leads": 1,
        "workflow_runs": 1,
        "jobs": 1,
        "audit_events": 1,
    }


def test_ten_identical_webhook_deliveries_create_exactly_one_lead(
    api_settings: Settings,
) -> None:
    from tests.integration.conftest import WEBHOOK_SECRET

    event = {"event_id": "evt_burst", "message": "Need a website", "email": "same@example.com"}
    body, headers = signed(event, WEBHOOK_SECRET)
    request: dict[str, object] = {
        "url": "/v1/webhooks/leads/website_form",
        "content": body,
        "headers": headers,
    }

    responses = asyncio.run(_fire(api_settings, [request] * CONCURRENCY))

    assert {r.status_code for r in responses} == {202}
    assert len({r.json()["lead_id"] for r in responses}) == 1
    assert counts()["leads"] == 1
    assert counts()["jobs"] == 1


def test_same_key_with_different_payloads_lets_exactly_one_win(
    api_settings: Settings, api_keys: ApiKeyFactory
) -> None:
    key = api_keys()
    requests: list[dict[str, object]] = [
        {
            "url": "/v1/leads",
            "json": {**LEAD, "message": f"version {n}"},
            "headers": bearer(key, "contested"),
        }
        for n in range(CONCURRENCY)
    ]

    responses = asyncio.run(_fire(api_settings, requests))

    assert Counter(r.status_code for r in responses) == {202: 1, 409: CONCURRENCY - 1}
    assert counts()["leads"] == 1


def test_ten_different_inquiries_from_one_person_share_one_contact(
    api_settings: Settings, api_keys: ApiKeyFactory
) -> None:
    key = api_keys()
    requests: list[dict[str, object]] = [
        {"url": "/v1/leads", "json": LEAD, "headers": bearer(key, f"inquiry-{n}")}
        for n in range(CONCURRENCY)
    ]

    responses = asyncio.run(_fire(api_settings, requests))

    assert {r.status_code for r in responses} == {202}
    assert counts()["leads"] == CONCURRENCY
    assert counts()["contacts"] == 1
    [[created]] = query("SELECT count(*) FROM audit_events WHERE (data->>'contact_created')::bool")
    assert created == 1

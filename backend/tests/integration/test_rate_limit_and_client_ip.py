"""Rate limits through the real app, including spoofed X-Forwarded-For."""

from fastapi.testclient import TestClient

from leadops.main import create_app
from tests.conftest import make_settings
from tests.integration.conftest import WEBHOOK_SECRET
from tests.integration.helpers import ApiKeyFactory, bearer, signed

LEAD = {"source": "website_form", "message": "Need a website", "email": "jane@example.com"}


def _client(peer: str, **settings: object) -> TestClient:
    app = create_app(make_settings(**settings))
    return TestClient(app, client=(peer, 40000))


def test_ip_limit_returns_429_with_retry_after(api_keys: ApiKeyFactory) -> None:
    key = api_keys()
    with _client("203.0.113.7", rate_limit_intake_per_ip=2) as client:
        statuses = [
            client.post("/v1/leads", json=LEAD, headers=bearer(key, f"k{n}")).status_code
            for n in range(3)
        ]
        blocked = client.post("/v1/leads", json=LEAD, headers=bearer(key, "k9"))

    assert statuses == [202, 202, 429]
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1
    assert blocked.json()["error"]["code"] == "rate_limited"


def test_spoofed_forwarded_for_from_an_untrusted_peer_does_not_bypass_the_limit(
    api_keys: ApiKeyFactory,
) -> None:
    key = api_keys()
    with _client("203.0.113.7", rate_limit_intake_per_ip=2) as client:
        statuses = [
            client.post(
                "/v1/leads",
                json=LEAD,
                headers={**bearer(key, f"k{n}"), "X-Forwarded-For": f"198.51.100.{n}"},
            ).status_code
            for n in range(3)
        ]

    # Every request counted against the real peer, whatever the header claimed.
    assert statuses == [202, 202, 429]


def test_forwarded_for_from_a_trusted_proxy_identifies_each_client(
    api_keys: ApiKeyFactory,
) -> None:
    key = api_keys()
    with _client(
        "172.18.0.5", rate_limit_intake_per_ip=2, trusted_proxy_cidrs=["172.18.0.0/16"]
    ) as client:
        statuses = [
            client.post(
                "/v1/leads",
                json=LEAD,
                headers={**bearer(key, f"k{n}"), "X-Forwarded-For": f"198.51.100.{n}"},
            ).status_code
            for n in range(3)
        ]

    # Three different real clients behind one proxy: none is limited.
    assert statuses == [202, 202, 202]


def test_ip_limit_runs_before_authentication() -> None:
    with _client("203.0.113.9", rate_limit_intake_per_ip=1) as client:
        first = client.post("/v1/leads", json=LEAD, headers=bearer("lok_bad"))
        second = client.post("/v1/leads", json=LEAD, headers=bearer("lok_bad"))

    assert (first.status_code, second.status_code) == (401, 429)


def test_per_api_key_limit(api_keys: ApiKeyFactory) -> None:
    key = api_keys()
    with _client("203.0.113.7", rate_limit_intake_per_api_key=1) as client:
        first = client.post("/v1/leads", json=LEAD, headers=bearer(key, "a"))
        second = client.post("/v1/leads", json=LEAD, headers=bearer(key, "b"))

    assert (first.status_code, second.status_code) == (202, 429)


def test_per_webhook_source_limit() -> None:
    with _client(
        "203.0.113.7",
        rate_limit_webhook_per_source=1,
        webhook_secrets={"website_form": [WEBHOOK_SECRET]},
    ) as client:
        codes = []
        for n in range(2):
            body, headers = signed({"event_id": f"evt_{n}", "message": "hi"}, WEBHOOK_SECRET)
            codes.append(
                client.post(
                    "/v1/webhooks/leads/website_form", content=body, headers=headers
                ).status_code
            )

    assert codes == [202, 429]

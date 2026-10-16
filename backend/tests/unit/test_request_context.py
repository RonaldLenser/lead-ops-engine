import json

import pytest
from fastapi.testclient import TestClient

from leadops.api.middleware import REQUEST_ID_HEADER, resolve_request_id


def test_generates_a_request_id_when_none_is_sent(client: TestClient) -> None:
    response = client.get("/healthz")

    request_id = response.headers[REQUEST_ID_HEADER]
    assert len(request_id) == 32
    assert request_id.isalnum()


def test_keeps_a_safe_client_request_id(client: TestClient) -> None:
    response = client.get("/healthz", headers={REQUEST_ID_HEADER: "n8n-exec_42"})

    assert response.headers[REQUEST_ID_HEADER] == "n8n-exec_42"


@pytest.mark.parametrize(
    "unsafe",
    ["has spaces", "x" * 65, "line\nbreak", "trailing-newline\n", "semi;colon", "<script>", ""],
)
def test_replaces_unsafe_client_request_ids(unsafe: str) -> None:
    assert resolve_request_id(unsafe) != unsafe


def test_every_response_gets_a_distinct_id(client: TestClient) -> None:
    first = client.get("/healthz").headers[REQUEST_ID_HEADER]
    second = client.get("/healthz").headers[REQUEST_ID_HEADER]

    assert first != second


def test_access_log_line_carries_the_request_id(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()  # drop startup logs

    response = client.get("/does-not-exist", headers={REQUEST_ID_HEADER: "trace-me"})

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]
    access = [line for line in lines if line["event"] == "request_completed"]
    assert response.status_code == 404
    assert access == [
        {
            "event": "request_completed",
            "method": "GET",
            "path": "/does-not-exist",
            "status": 404,
            "duration_ms": access[0]["duration_ms"],
            "request_id": "trace-me",
            "level": "info",
            "timestamp": access[0]["timestamp"],
        }
    ]

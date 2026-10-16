from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from leadops.config import Settings
from leadops.main import create_app

LIMIT = 32_768


@pytest.fixture
def echo_client(settings: Settings) -> Iterator[TestClient]:
    app: FastAPI = create_app(settings)

    @app.post("/echo-size")
    async def echo_size(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    with TestClient(app) as client:
        yield client


def test_body_at_the_limit_is_accepted(echo_client: TestClient) -> None:
    response = echo_client.post("/echo-size", content=b"x" * LIMIT)

    assert response.json() == {"size": LIMIT}


def test_declared_oversized_body_is_rejected_with_413(echo_client: TestClient) -> None:
    response = echo_client.post("/echo-size", content=b"x" * (LIMIT + 1))

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


def test_streamed_body_without_content_length_is_cut_off(echo_client: TestClient) -> None:
    def chunks() -> Iterator[bytes]:
        for _ in range(10):
            yield b"x" * 10_000  # 100 KB total, sent chunked with no Content-Length

    response = echo_client.post("/echo-size", content=chunks())

    assert response.status_code == 413

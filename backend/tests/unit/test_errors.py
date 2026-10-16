from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from leadops.api.middleware import REQUEST_ID_HEADER
from leadops.config import Settings
from leadops.errors import AppError
from leadops.main import create_app


class TeapotError(AppError):
    status_code = 418
    code = "teapot"


class Payload(BaseModel):
    email: str
    count: int


def app_with_failing_routes(settings: Settings) -> FastAPI:
    app = create_app(settings)

    @app.get("/boom")
    def boom() -> None:
        secret_value = "sk-should-never-leak"
        raise RuntimeError(f"internal detail {secret_value}")

    @app.get("/teapot")
    def teapot() -> None:
        raise TeapotError("I am a teapot")

    @app.post("/payload")
    def payload(body: Payload) -> Payload:
        return body

    return app


@pytest.fixture
def failing_client(settings: Settings) -> Iterator[TestClient]:
    # raise_server_exceptions=False: return the 500 like a real server would.
    with TestClient(app_with_failing_routes(settings), raise_server_exceptions=False) as client:
        yield client


def test_unknown_route_uses_the_standard_error_shape(failing_client: TestClient) -> None:
    response = failing_client.get("/nope")

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "http_error"
    assert error["request_id"] == response.headers[REQUEST_ID_HEADER]


def test_app_errors_map_to_their_status_and_code(failing_client: TestClient) -> None:
    response = failing_client.get("/teapot")

    assert response.status_code == 418
    assert response.json()["error"]["code"] == "teapot"
    assert response.json()["error"]["message"] == "I am a teapot"


def test_unexpected_errors_return_a_generic_500_with_request_id(
    failing_client: TestClient,
) -> None:
    response = failing_client.get("/boom", headers={REQUEST_ID_HEADER: "boom-1"})

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "Internal server error",
            "request_id": "boom-1",
        }
    }
    assert response.headers[REQUEST_ID_HEADER] == "boom-1"
    assert "sk-should-never-leak" not in response.text


def test_validation_errors_do_not_echo_submitted_values(failing_client: TestClient) -> None:
    response = failing_client.post(
        "/payload", json={"email": "jane.prospect@example.com", "count": "not-a-number"}
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"] == [
        {
            "type": "int_parsing",
            "loc": ["body", "count"],
            "msg": "Input should be a valid integer, unable to parse string as an integer",
        }
    ]
    assert "jane.prospect@example.com" not in response.text
    assert "not-a-number" not in response.text

import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
import structlog

from leadops.logging_config import configure_logging


@pytest.fixture(autouse=True)
def _reset_context() -> Iterator[None]:
    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()


def json_lines(output: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def test_json_logs_include_level_timestamp_and_bound_context(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", json_logs=True)
    structlog.contextvars.bind_contextvars(request_id="req-123")

    structlog.get_logger("test").info("something_happened", lead_count=3)

    [line] = json_lines(capsys.readouterr().out)
    assert line["event"] == "something_happened"
    assert line["lead_count"] == 3
    assert line["request_id"] == "req-123"
    assert line["level"] == "info"
    assert line["timestamp"].endswith("Z")


def test_log_level_filters_lower_levels(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("WARNING", json_logs=True)

    structlog.get_logger("test").info("too_quiet")
    structlog.get_logger("test").warning("loud_enough")

    events = [line["event"] for line in json_lines(capsys.readouterr().out)]
    assert events == ["loud_enough"]


def test_standard_library_logs_are_rendered_as_json_too(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", json_logs=True)
    structlog.contextvars.bind_contextvars(request_id="req-456")

    logging.getLogger("uvicorn.error").warning("library message")

    [line] = json_lines(capsys.readouterr().out)
    assert line["event"] == "library message"
    assert line["logger"] == "uvicorn.error"
    assert line["request_id"] == "req-456"


def test_tracebacks_never_include_local_variables(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_logs=True)

    def handle_lead() -> None:
        lead_email = "jane.prospect@example.com"  # would leak if locals were rendered
        raise RuntimeError(f"failed after {len(lead_email)} chars")

    try:
        handle_lead()
    except RuntimeError:
        structlog.get_logger("test").exception("lead_failed")

    output = capsys.readouterr().out
    [line] = json_lines(output)
    assert line["exception"][0]["exc_type"] == "RuntimeError"
    assert "jane.prospect@example.com" not in output


def test_uvicorn_access_log_is_silenced_because_the_middleware_logs_requests(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("DEBUG", json_logs=True)

    logging.getLogger("uvicorn.access").info('127.0.0.1 - "GET / HTTP/1.1" 200')

    assert capsys.readouterr().out == ""


def test_sql_statements_are_not_logged_by_default(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("DEBUG", json_logs=True)

    logging.getLogger("sqlalchemy.engine.Engine").info("INSERT INTO leads ... ('jane@example.com')")

    assert capsys.readouterr().out == ""

"""Map exceptions to HTTP responses with ONE error shape:

    {"error": {"code": "not_found", "message": "...", "request_id": "..."}}

Clients branch on the stable `code`, humans read `message`, and `request_id`
finds the matching log lines. Unexpected exceptions return a generic 500:
details stay in the logs, never in the response.
"""

from typing import Any

import structlog
from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from leadops.api.middleware import REQUEST_ID_HEADER
from leadops.errors import AppError

logger = structlog.get_logger(__name__)

# Pydantic error entries can carry the rejected input. It is dropped from
# responses so request bodies (which will hold personal data from M2 on) are
# never echoed back or copied into anything that stores responses.
_VALIDATION_DETAIL_KEYS = ("type", "loc", "msg")


def _current_request_id() -> str | None:
    request_id = structlog.contextvars.get_contextvars().get("request_id")
    return request_id if isinstance(request_id, str) else None


def error_response(
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
    **extra: Any,
) -> JSONResponse:
    body: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": _current_request_id(),
        **extra,
    }
    return JSONResponse(
        status_code=status_code, content={"error": jsonable_encoder(body)}, headers=headers
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("request_failed", code=exc.code)
        return error_response(exc.status_code, exc.code, exc.message, headers=exc.headers or None)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {key: error[key] for key in _VALIDATION_DETAIL_KEYS if key in error}
            for error in exc.errors()
        ]
        return error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "validation_error",
            "Request validation failed",
            details=details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return error_response(exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", error_type=type(exc).__name__)
        # This handler runs outside RequestContextMiddleware, so the header that
        # middleware normally adds must be set here.
        request_id = _current_request_id()
        headers = {REQUEST_ID_HEADER: request_id} if request_id else None
        return error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            "Internal server error",
            headers=headers,
        )

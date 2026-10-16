"""Request context middleware: a request ID on every request, one access log line each.

Plain ASGI middleware rather than Starlette's BaseHTTPMiddleware, which has
known problems with context variables and streaming responses.

Request ID rules:
- A client may send X-Request-ID. It is kept only if it is short and uses safe
  characters; anything else is replaced, so callers cannot inject newlines or
  huge strings into the logs.
- The ID is bound to structlog's context, so every log line written while the
  request runs includes it, and it is returned in the X-Request-ID header.
"""

import re
import time
import uuid

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")

# Probes hit these every few seconds. Their access lines are logged at DEBUG
# so they do not drown out real traffic at the default INFO level.
_PROBE_PATHS = frozenset({"/healthz", "/readyz"})

logger = structlog.get_logger("leadops.http")


def resolve_request_id(incoming: str | None) -> str:
    """Keep a safe client-supplied ID, otherwise generate a new one."""
    # fullmatch, not match + "$": "$" also matches before a trailing newline.
    if incoming and _SAFE_REQUEST_ID.fullmatch(incoming):
        return incoming
    return uuid.uuid4().hex


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = resolve_request_id(Headers(scope=scope).get(REQUEST_ID_HEADER))
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        status_code = 500  # assume failure until a response actually starts
        start = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            log = logger.debug if scope["path"] in _PROBE_PATHS else logger.info
            log(
                "request_completed",
                method=scope["method"],
                path=scope["path"],
                status=status_code,
                duration_ms=round((time.perf_counter() - start) * 1000, 1),
            )
            # Context is NOT cleared here: the unhandled-exception handler runs
            # outside this middleware, after this point, and still needs
            # request_id. Each new request clears it at the top instead.

"""Reject request bodies over a size limit before the app reads them.

Two checks, because a client can lie about or omit Content-Length:
1. If Content-Length is present and too large: 413 immediately, body unread.
2. Otherwise the body is counted as it streams in, and reading stops with
   413 as soon as the limit is passed. A huge chunked upload never gets
   fully buffered in memory.

Routes that accept a body read it with `await request.body()` themselves
(they need the exact bytes for signatures and payload hashing). FastAPI's
automatic body parsing would turn the size error into a generic 400.
"""

import json

import structlog
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BodyTooLargeError(Exception):
    pass


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = Headers(scope=scope).get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await self._reject(scope, send)
            return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise BodyTooLargeError
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except BodyTooLargeError:
            if response_started:
                raise
            await self._reject(scope, send)

    async def _reject(self, scope: Scope, send: Send) -> None:
        # Same error shape as api/errors.py. This middleware runs inside
        # RequestContextMiddleware, which has already bound request_id and adds
        # the X-Request-ID header to this response on the way out.
        request_id = structlog.contextvars.get_contextvars().get("request_id")
        body = json.dumps(
            {
                "error": {
                    "code": "payload_too_large",
                    "message": f"Request body exceeds {self.max_bytes} bytes",
                    "request_id": request_id,
                }
            }
        ).encode()
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ]
        await send({"type": "http.response.start", "status": 413, "headers": headers})
        await send({"type": "http.response.body", "body": body})

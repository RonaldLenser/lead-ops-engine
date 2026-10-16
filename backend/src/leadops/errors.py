"""Application errors.

Services raise these and know nothing about HTTP. The API layer
(api/errors.py) turns each one into a status code and the standard JSON
error body. Subclasses are added when a milestone needs them.
"""


class AppError(Exception):
    """Base class. `code` is a stable, machine-readable identifier for clients."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.headers: dict[str, str] = headers or {}


class BadRequestError(AppError):
    status_code = 400
    code = "bad_request"


class AuthenticationError(AppError):
    """Missing or invalid credentials. One message for every cause, so callers
    cannot tell an unknown key from a wrong secret or a revoked key."""

    status_code = 401
    code = "unauthorized"

    def __init__(self, message: str = "Missing or invalid credentials") -> None:
        super().__init__(message, headers={"WWW-Authenticate": "Bearer"})


class InvalidSignatureError(AppError):
    status_code = 401
    code = "invalid_signature"

    def __init__(self) -> None:
        super().__init__("Missing, malformed, expired, or incorrect request signature")


class PermissionDeniedError(AppError):
    status_code = 403
    code = "forbidden"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class IdempotencyConflictError(AppError):
    """Same idempotency key or event ID, different request content."""

    status_code = 409
    code = "idempotency_conflict"


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(
            f"Too many requests. Retry in {retry_after_seconds} seconds.",
            headers={"Retry-After": str(retry_after_seconds)},
        )

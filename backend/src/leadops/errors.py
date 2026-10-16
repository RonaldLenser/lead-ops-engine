"""Application errors.

Services raise these and know nothing about HTTP. The API layer
(api/errors.py) turns each one into a status code and the standard JSON
error body. Subclasses are added when a milestone needs them.
"""


class AppError(Exception):
    """Base class. `code` is a stable, machine-readable identifier for clients."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

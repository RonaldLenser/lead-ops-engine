"""Read and validate a JSON body by hand.

Intake routes need the exact request bytes (for signatures) and the raw
parsed JSON (stored as the inbound event payload), and they must let the
body-size middleware's 413 through. FastAPI's automatic body parameter
would hide all three, so these routes call parse_json_body() instead.
"""

import json
from typing import Any

from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError

from leadops.errors import BadRequestError


def parse_json_object(body: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BadRequestError("Request body must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise BadRequestError("Request body must be a JSON object")
    return parsed


def validate_body[ModelT: BaseModel](model: type[ModelT], data: dict[str, Any]) -> ModelT:
    """Validate with the same 422 shape FastAPI uses (input values are never echoed)."""
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        errors = [{**error, "loc": ("body", *error["loc"])} for error in exc.errors()]
        raise RequestValidationError(errors) from exc


def openapi_json_body(model: type[BaseModel]) -> dict[str, Any]:
    """Document the body in OpenAPI even though the route reads it manually."""
    return {
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": model.model_json_schema()}},
        }
    }

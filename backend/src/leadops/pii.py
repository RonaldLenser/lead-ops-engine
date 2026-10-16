"""Deterministic masking of personal data and secrets in log output.

Logs should carry IDs (lead_id, request_id), not personal data. This is the
safety net for when personal data reaches a log line anyway: an exception
message that quotes an email, a library warning that includes a phone number.

Masking is rule-based and deterministic: the same input always produces the
same masked output, and nothing is sent anywhere.

    jane.prospect@example.com   ->  j***@e***.com
    +1 (540) 395-0123           ->  ***23
    lok_1a2b3c4d5e_<secret>     ->  lok_1a2b3c4d5e_***

Only string values are masked. Numbers stay numbers, so durations and counts
are untouched. Keys that only hold system identifiers (anything ending in
_id or _prefix, plus timestamp, level, logger, path, method) are skipped.
"""

import re
from typing import Any

from structlog.typing import EventDict, WrappedLogger

_EMAIL = re.compile(
    r"(?P<local>[A-Za-z0-9._%+-]+)@(?P<domain>[A-Za-z0-9-]+)"
    r"(?P<rest>(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})"
)

# 10 to 15 digits with common separators, not touching letters, digits, or a
# hyphen on either side (so a numeric segment inside a UUID is left alone).
# Short numbers and dates like 2026-10-16 do not match.
_PHONE = re.compile(r"(?<![\w+-])\+?\d[\d\s().-]{8,18}\d(?![\w-])")

# API keys issued by this system (see leadops.security.api_keys).
_API_KEY = re.compile(r"\b(lok_[0-9a-f]{10}_)[A-Za-z0-9_-]+")

# Keys that only ever hold system values. Keys ending in "_id" or "_prefix" are skipped too.
_SKIP_KEYS = frozenset({"timestamp", "level", "logger", "path", "method"})


def _mask_email(match: re.Match[str]) -> str:
    tld = match.group("rest").rsplit(".", 1)[-1]
    return f"{match.group('local')[0]}***@{match.group('domain')[0]}***.{tld}"


def _mask_phone(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    if not 10 <= len(digits) <= 15:
        return match.group(0)
    return f"***{digits[-2:]}"


def mask_text(text: str) -> str:
    text = _API_KEY.sub(r"\1***", text)
    text = _EMAIL.sub(_mask_email, text)
    return _PHONE.sub(_mask_phone, text)


def mask_value(value: Any) -> Any:
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, dict):
        return {key: mask_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [mask_value(item) for item in value]
    return value


def mask_pii_processor(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    """structlog processor: mask every string value except known-safe keys."""
    for key, value in event_dict.items():
        if key not in _SKIP_KEYS and not key.endswith(("_id", "_prefix")):
            event_dict[key] = mask_value(value)
    return event_dict

"""Deterministic contact normalization.

Same input, same output, no network calls, no LLM. These values decide which
contact a lead belongs to, so they must be predictable and testable.

A value that cannot be normalized is NOT an error for the lead: the lead is
still accepted, the raw value is kept on the lead, and the problem is
recorded as a contact issue. Losing a real inquiry because someone typed
their phone number oddly is worse than storing it unverified.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

import phonenumbers

ContactIssue = Literal["email_invalid", "phone_invalid"]

# Deliberately simple: one @, no whitespace, a dot in the domain, sane length.
# Full RFC 5322 validation rejects nothing useful here; deliverability is only
# provable by sending, which happens much later and only after approval.
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s.]+")
MAX_EMAIL_LENGTH = 254


def normalize_email(raw: str | None) -> str | None:
    """Lowercased, trimmed email, or None if absent or malformed."""
    if raw is None:
        return None
    candidate = raw.strip().lower()
    if not candidate or len(candidate) > MAX_EMAIL_LENGTH:
        return None
    return candidate if _EMAIL.fullmatch(candidate) else None


def normalize_phone(raw: str | None, default_region: str) -> str | None:
    """E.164 phone number (+15403950000), or None if absent or not a valid number.

    Numbers without a country code are read in `default_region` (US for this
    business). Validity uses libphonenumber's numbering-plan metadata, so
    "555-0000" style fakes and wrong-length numbers are rejected.
    """
    if raw is None or not raw.strip():
        return None
    try:
        parsed = phonenumbers.parse(raw, default_region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


@dataclass(frozen=True)
class NormalizedContact:
    email: str | None
    phone: str | None
    name: str | None
    issues: list[ContactIssue] = field(default_factory=list)

    @property
    def identifiable(self) -> bool:
        """True when there is something to dedupe a contact on."""
        return self.email is not None or self.phone is not None


def normalize_contact(
    *, email: str | None, phone: str | None, name: str | None, default_region: str
) -> NormalizedContact:
    normalized_email = normalize_email(email)
    normalized_phone = normalize_phone(phone, default_region)
    issues: list[ContactIssue] = []
    if email and email.strip() and normalized_email is None:
        issues.append("email_invalid")
    if phone and phone.strip() and normalized_phone is None:
        issues.append("phone_invalid")
    clean_name = name.strip() if name and name.strip() else None
    return NormalizedContact(
        email=normalized_email, phone=normalized_phone, name=clean_name, issues=issues
    )

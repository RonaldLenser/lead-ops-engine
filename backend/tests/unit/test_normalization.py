import pytest

from leadops.domain.normalization import normalize_contact, normalize_email, normalize_phone


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Jane.Prospect@Example.COM", "jane.prospect@example.com"),
        ("  owner@shop.co.uk \n", "owner@shop.co.uk"),
        ("a+tag@b.io", "a+tag@b.io"),
    ],
)
def test_valid_emails_are_trimmed_and_lowercased(raw: str, expected: str) -> None:
    assert normalize_email(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "no-at-sign",
        "two@@signs.com",
        "a@b",
        "a b@c.com",
        "a@b.",
        "x" * 250 + "@a.com",
    ],
)
def test_invalid_emails_normalize_to_none(raw: str | None) -> None:
    assert normalize_email(raw) is None


@pytest.mark.parametrize(
    "raw",
    ["(540) 395-0123", "540-395-0123", "540.395.0123", "+1 540 395 0123", "15403950123"],
)
def test_us_phone_formats_all_become_the_same_e164(raw: str) -> None:
    assert normalize_phone(raw, "US") == "+15403950123"


def test_international_numbers_keep_their_country_code() -> None:
    assert normalize_phone("+44 20 7946 0958", "US") == "+442079460958"


@pytest.mark.parametrize("raw", [None, "", "12", "not a phone", "555-0100", "+1 000 000 0000"])
def test_invalid_phones_normalize_to_none(raw: str | None) -> None:
    assert normalize_phone(raw, "US") is None


def test_contact_records_issues_instead_of_failing() -> None:
    contact = normalize_contact(
        email="not-an-email", phone="12", name="  Jane  ", default_region="US"
    )

    assert (contact.email, contact.phone, contact.name) == (None, None, "Jane")
    assert contact.issues == ["email_invalid", "phone_invalid"]
    assert contact.identifiable is False


def test_absent_fields_are_not_issues() -> None:
    contact = normalize_contact(email=None, phone="", name=None, default_region="US")

    assert contact.issues == []
    assert contact.name is None


def test_normalization_is_deterministic() -> None:
    first = normalize_contact(email="A@B.com", phone="540 395 0123", name="X", default_region="US")
    second = normalize_contact(email="A@B.com", phone="540 395 0123", name="X", default_region="US")

    assert first == second

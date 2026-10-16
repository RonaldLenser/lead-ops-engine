import pytest
from pydantic import ValidationError

from leadops.schemas.intake import DirectLeadRequest, WebhookLeadPayload, canonical_sha256

BASE = {"source": "website_form", "message": "Need a site", "email": "a@b.com"}


def test_same_meaning_gives_the_same_hash() -> None:
    first = DirectLeadRequest.model_validate(BASE)
    reordered = DirectLeadRequest.model_validate(
        {"email": " a@b.com ", "message": "Need a site  ", "source": "website_form", "name": None}
    )

    assert canonical_sha256(first) == canonical_sha256(reordered)


def test_any_content_change_changes_the_hash() -> None:
    first = DirectLeadRequest.model_validate(BASE)
    changed = DirectLeadRequest.model_validate({**BASE, "message": "Need a logo"})

    assert canonical_sha256(first) != canonical_sha256(changed)


@pytest.mark.parametrize(
    "payload",
    [
        {**BASE, "source": "Website Form"},
        {**BASE, "message": ""},
        {**BASE, "message": "x" * 10_001},
        {**BASE, "extra": "field"},
        {"source": "website_form"},
    ],
)
def test_invalid_direct_requests_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        DirectLeadRequest.model_validate(payload)


@pytest.mark.parametrize("event_id", ["", "has space", "x" * 201, "semi;colon"])
def test_webhook_event_ids_are_restricted(event_id: str) -> None:
    with pytest.raises(ValidationError):
        WebhookLeadPayload.model_validate({"event_id": event_id, "message": "hi"})

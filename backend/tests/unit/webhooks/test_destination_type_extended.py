"""TDD RED: DestinationType must accept all 8 notification channel type values.

NOTIF-01 / Plan 30-02 - extending destination_type_enum with email, pagerduty,
opsgenie, ntfy.
"""
from __future__ import annotations

import uuid
import pytest
from pydantic import ValidationError

from app.schemas.webhooks import DestinationType, WebhookCreate


_NEW_TYPES = ["email", "pagerduty", "opsgenie", "ntfy"]
_EXISTING_TYPES = ["slack", "teams", "discord", "generic"]
_ALL_TYPES = _EXISTING_TYPES + _NEW_TYPES

_DUMMY_PROJECT_ID = uuid.uuid4()
_DUMMY_URL = "https://example.com/hook"
_DUMMY_NAME = "test-hook"


def _make_create(destination_type: str) -> WebhookCreate:
    return WebhookCreate(
        name=_DUMMY_NAME,
        project_id=_DUMMY_PROJECT_ID,
        destination_type=destination_type,  # type: ignore[arg-type]
        url=_DUMMY_URL,
    )


@pytest.mark.parametrize("dtype", _ALL_TYPES)
def test_destination_type_accepts_all_8_values(dtype: str) -> None:
    """All 8 destination type literals must pass Pydantic validation."""
    obj = _make_create(dtype)
    assert obj.destination_type == dtype


def test_destination_type_rejects_invalid_value() -> None:
    """An invalid type (e.g. 'sms') must raise ValidationError."""
    with pytest.raises(ValidationError):
        _make_create("sms")


def test_destination_type_literal_includes_new_values() -> None:
    """DestinationType.__args__ must contain all 4 new values."""
    args = set(DestinationType.__args__)
    for new_type in _NEW_TYPES:
        assert new_type in args, f"'{new_type}' missing from DestinationType"


def test_destination_type_literal_preserves_existing_values() -> None:
    """DestinationType.__args__ must still contain all 4 original values."""
    args = set(DestinationType.__args__)
    for existing in _EXISTING_TYPES:
        assert existing in args, f"'{existing}' missing from DestinationType"

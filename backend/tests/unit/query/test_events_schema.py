"""EventItem geo_lat/geo_lon schema — plan 06-03 target (MAP-01, MAP-05)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.schemas.events import EventItem

_MINIMAL = {
    "id": uuid.uuid4(),
    "observed_at": datetime.now(tz=timezone.utc),
    "fetched_at": datetime.now(tz=timezone.utc),
    "source_id": None,
    "stix_id": None,
    "stix_type": "indicator",
    "title": None,
    "description": None,
    "archived": False,
    "visibility": "shared",
}


def test_event_item_accepts_geo_lat_lon():
    """EventItem instantiates when geo_lat and geo_lon are provided."""
    item = EventItem(**_MINIMAL, geo_lat=48.85, geo_lon=2.35)
    assert item.geo_lat == 48.85
    assert item.geo_lon == 2.35


def test_event_item_geo_defaults_none():
    """EventItem.geo_lat and geo_lon both default to None when omitted."""
    item = EventItem(**_MINIMAL)
    assert item.geo_lat is None
    assert item.geo_lon is None


def test_event_item_geo_excluded_from_serialized_none_in_strict_mode():
    """model_dump() includes geo_lat and geo_lon keys with None values (keys are present)."""
    item = EventItem(**_MINIMAL)
    dumped = item.model_dump()
    assert "geo_lat" in dumped
    assert "geo_lon" in dumped
    assert dumped["geo_lat"] is None
    assert dumped["geo_lon"] is None

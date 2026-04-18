"""Shared fake EventItem builder used by payload builder tests (07-02) and
dispatcher tests (07-03). EventItem schema from backend/app/schemas/events.py
(Phase 4 D-11). Using a helper keeps the 4 payload test files DRY."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


def build_fake_event(
    title: str = "Test event",
    tlp: str | None = "amber",
    stix_type: str = "indicator",
    source_name: str = "MITRE CTI",
    description: str | None = "A test description",
    tags: list[str] | None = None,
    attack_techniques: list[str] | None = None,
) -> dict[str, Any]:
    """Return a dict shaped like EventItem (for dispatcher that works with dicts)."""
    return {
        "id": str(uuid.uuid4()),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source_id": str(uuid.uuid4()),
        "source_name": source_name,
        "source_type": "taxii",
        "stix_id": None,
        "stix_type": stix_type,
        "title": title,
        "description": description,
        "tlp": tlp,
        "tags": tags or [],
        "attack_techniques": attack_techniques or [],
        "archived": False,
        "visibility": "shared",
        "geo_lat": None,
        "geo_lon": None,
    }

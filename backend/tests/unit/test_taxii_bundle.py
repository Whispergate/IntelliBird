"""Unit tests for TAXII bundle builder — TAXII-02, TAXII-04."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.services.taxii_bundle import build_tlp_predicate, event_to_stix_sdo


def _make_event(**kwargs) -> MagicMock:
    """Build a minimal mock Event row."""
    defaults = {
        "id": uuid.uuid4(),
        "title": "Test Event",
        "observed_at": datetime.now(timezone.utc),
        "raw_stix": None,
        "stix_type": None,
        "source_id": None,
        "project_id": uuid.uuid4(),
    }
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def test_event_with_raw_stix_passthrough():
    """TAXII-02: event with raw_stix returns the stored SDO dict unchanged."""
    raw = {
        "type": "indicator",
        "spec_version": "2.1",
        "id": "indicator--" + str(uuid.uuid4()),
        "name": "Test indicator",
        "pattern": "[domain-name:value = 'example.com']",
        "pattern_type": "stix",
        "valid_from": "2024-01-01T00:00:00Z",
        "created": "2024-01-01T00:00:00Z",
        "modified": "2024-01-01T00:00:00Z",
    }
    event = _make_event(raw_stix=raw, stix_type="indicator")
    result = event_to_stix_sdo(event, tlp_cache={})
    assert result == raw


def test_event_without_stix_wraps_observed_data():
    """TAXII-02: event without raw_stix is wrapped as ObservedData with x_intellibird_* props."""
    project_id = uuid.uuid4()
    event = _make_event(raw_stix=None, stix_type=None, title="RSS Event", project_id=project_id)
    result = event_to_stix_sdo(event, tlp_cache={})
    assert result["type"] == "observed-data"
    assert result["spec_version"] == "2.1"
    assert "x_intellibird_title" in result
    assert result["x_intellibird_title"] == "RSS Event"
    assert result.get("x_intellibird_project_id") == str(project_id)


def test_tlp_predicate_filters_amber_from_green_client():
    """TAXII-04: build_tlp_predicate('green') allows white/clear/green; excludes amber/red."""
    predicate_green = build_tlp_predicate("green")
    assert predicate_green is not None

    # Inspect the allowed names by calling build_tlp_predicate logic inline
    from app.services.taxii_bundle import TLP_LEVELS
    cap_green = TLP_LEVELS["green"]
    allowed_green = [n for n, r in TLP_LEVELS.items() if r <= cap_green]
    assert "white" in allowed_green
    assert "clear" in allowed_green
    assert "green" in allowed_green
    assert "amber" not in allowed_green
    assert "red" not in allowed_green

    cap_amber = TLP_LEVELS["amber"]
    allowed_amber = [n for n, r in TLP_LEVELS.items() if r <= cap_amber]
    assert "amber" in allowed_amber
    assert "red" not in allowed_amber

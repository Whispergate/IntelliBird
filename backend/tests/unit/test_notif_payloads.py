"""
Tests for notification payload builders (NOTIF-03, NOTIF-04, NOTIF-05).
"""

from __future__ import annotations

import pytest

from app.services.webhook_payloads import (
    build_ntfy_payload,
    build_opsgenie_payload,
    build_pagerduty_payload,
)


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

_EVENT = {
    "id": "evt-001",
    "title": "Ransomware campaign detected",
    "description": "Critical ransomware campaign targeting financial sector.",
    "stix_type": "threat-actor",
    "tlp": "S",
    "tags": ["ransomware", "finance"],
    "source_name": "test-source",
    "observed_at": "2026-01-15T10:00:00Z",
}

_DASHBOARD_URL = "https://intellibird.example.com"
_PRESET = "critical-alerts"


# ---------------------------------------------------------------------------
# PagerDuty payload builder (NOTIF-03)
# ---------------------------------------------------------------------------


def test_build_pagerduty_payload() -> None:
    """NOTIF-03: builder returns dict with 'event_action', 'dedup_key', nested payload.severity."""
    result = build_pagerduty_payload([_EVENT], _PRESET, _DASHBOARD_URL)
    assert result["event_action"] == "trigger"
    assert result["dedup_key"] == "evt-001"
    assert "payload" in result
    assert "severity" in result["payload"]


def test_pagerduty_severity_mapping() -> None:
    """S → critical, A → error, B → warning, C/D → info."""
    ev = dict(_EVENT)
    for tlp, expected in [("S", "critical"), ("A", "error"), ("B", "warning"), ("C", "info"), ("D", "info")]:
        ev["tlp"] = tlp
        result = build_pagerduty_payload([ev], _PRESET, _DASHBOARD_URL)
        assert result["payload"]["severity"] == expected, f"tlp={tlp}"


def test_pagerduty_routing_key_in_body() -> None:
    """routing_key is present in the returned dict body (not a header)."""
    result = build_pagerduty_payload([_EVENT], _PRESET, _DASHBOARD_URL)
    assert "routing_key" in result
    assert result["routing_key"] == "_PENDING_INJECTION_"


def test_pagerduty_custom_details_fields() -> None:
    """custom_details includes preset name, stix_type, tlp, tags."""
    result = build_pagerduty_payload([_EVENT], _PRESET, _DASHBOARD_URL)
    details = result["payload"]["custom_details"]
    assert details["preset"] == _PRESET
    assert details["stix_type"] == "threat-actor"
    assert details["tlp"] == "S"
    assert isinstance(details["tags"], list)


# ---------------------------------------------------------------------------
# Opsgenie payload builder (NOTIF-05)
# ---------------------------------------------------------------------------


def test_build_opsgenie_payload() -> None:
    """NOTIF-05: returns dict with 'message', 'alias', 'priority'."""
    result = build_opsgenie_payload([_EVENT], _PRESET, _DASHBOARD_URL)
    assert "message" in result
    assert "alias" in result
    assert "priority" in result
    assert result["alias"] == "evt-001"


def test_opsgenie_priority_mapping() -> None:
    """S → P1, A → P2, B → P3, C → P4, D → P5."""
    ev = dict(_EVENT)
    for tlp, expected in [("S", "P1"), ("A", "P2"), ("B", "P3"), ("C", "P4"), ("D", "P5")]:
        ev["tlp"] = tlp
        result = build_opsgenie_payload([ev], _PRESET, _DASHBOARD_URL)
        assert result["priority"] == expected, f"tlp={tlp}"


def test_opsgenie_source_and_tags() -> None:
    """source field is 'IntelliBird', tags list includes preset_name."""
    result = build_opsgenie_payload([_EVENT], _PRESET, _DASHBOARD_URL)
    assert result["source"] == "IntelliBird"
    assert _PRESET in result["tags"]


# ---------------------------------------------------------------------------
# ntfy payload builder (NOTIF-04)
# ---------------------------------------------------------------------------


def test_build_ntfy_payload() -> None:
    """NOTIF-04: returns dict with 'topic', 'title', 'message', 'priority'."""
    params = {"ntfy_url": "https://ntfy.sh/my-topic"}
    result = build_ntfy_payload([_EVENT], _PRESET, _DASHBOARD_URL, params)
    assert "topic" in result
    assert "title" in result
    assert "message" in result
    assert "priority" in result


def test_ntfy_topic_extracted_from_url() -> None:
    """URL 'https://ntfy.sh/my-topic' → topic='my-topic'."""
    params = {"ntfy_url": "https://ntfy.sh/my-topic"}
    result = build_ntfy_payload([_EVENT], _PRESET, _DASHBOARD_URL, params)
    assert result["topic"] == "my-topic"


def test_ntfy_topic_fallback_when_no_url() -> None:
    """Falls back to 'intellibird' when ntfy_url is absent or has empty path."""
    result = build_ntfy_payload([_EVENT], _PRESET, _DASHBOARD_URL, None)
    assert result["topic"] == "intellibird"


def test_ntfy_priority_mapping() -> None:
    """S → 5, A → 4, B → 3, C/D → 2."""
    ev = dict(_EVENT)
    params = {"ntfy_url": "https://ntfy.sh/alerts"}
    for tlp, expected in [("S", 5), ("A", 4), ("B", 3), ("C", 2), ("D", 2)]:
        ev["tlp"] = tlp
        result = build_ntfy_payload([ev], _PRESET, _DASHBOARD_URL, params)
        assert result["priority"] == expected, f"tlp={tlp}"

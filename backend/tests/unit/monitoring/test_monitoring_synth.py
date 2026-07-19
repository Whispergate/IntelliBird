"""MON-05 monitoring event synthesis - plan 16-03.

Tests that monitoring_synth.py produces deterministic content_hash values and
correctly-shaped canonical event dicts for each alert type, using the sentinel
project_id for monitoring-originated events.
"""
from __future__ import annotations

from datetime import datetime, timezone


from app.services.monitoring_synth import (
    SENTINEL_PROJECT_ID,
    _content_hash,
    build_drift_event_dict,
    build_parse_error_event_dict,
    build_silence_event_dict,
)

utc = timezone.utc
_REQUIRED_KEYS = {"stix_type", "stix_id", "title", "description", "observed_at", "tags", "raw_stix", "content_hash", "project_id"}


def test_content_hash_deterministic() -> None:
    """sha256(source_id + alert_type + window_bucket) is stable across calls."""
    h1 = _content_hash("s1", "source_silence", "2026-04-25T12:00:00+00:00")
    h2 = _content_hash("s1", "source_silence", "2026-04-25T12:00:00+00:00")
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex digest


def test_content_hash_differs_by_source() -> None:
    """Different source_id produces different hash."""
    h1 = _content_hash("s1", "source_silence", "2026-04-25T12:00:00+00:00")
    h2 = _content_hash("s2", "source_silence", "2026-04-25T12:00:00+00:00")
    assert h1 != h2


def test_build_silence_event_dict_shape() -> None:
    """build_silence_event_dict returns correctly shaped dict."""
    last_seen = datetime(2026, 4, 24, 12, 0, tzinfo=utc)
    result = build_silence_event_dict(
        source_id="s1",
        source_name="ACME RSS",
        last_event_at=last_seen,
        sla_seconds=86400,
    )
    assert _REQUIRED_KEYS.issubset(result.keys())
    assert result["stix_type"] == "x-monitoring-alert"
    assert result["project_id"] == SENTINEL_PROJECT_ID
    assert "monitoring" in result["tags"]
    assert "monitoring:source_silence" in result["tags"]
    assert "source:s1" in result["tags"]
    assert result["raw_stix"] is None


def test_build_drift_event_dict_shape() -> None:
    """build_drift_event_dict returns correctly shaped dict with severity tag."""
    window = datetime(2026, 4, 25, 10, 0, tzinfo=utc)
    result = build_drift_event_dict(
        source_id="s2",
        source_name="CVE Feed",
        severity="high",
        z_score=3.5,
        baseline_mean=100.0,
        current_value=150.0,
        window_bucket=window,
    )
    assert _REQUIRED_KEYS.issubset(result.keys())
    assert result["stix_type"] == "x-monitoring-alert"
    assert result["project_id"] == SENTINEL_PROJECT_ID
    assert "monitoring:high" in result["tags"]
    assert "monitoring:volume_drift" in result["tags"]
    assert "source:s2" in result["tags"]


def test_build_parse_error_event_dict_shape() -> None:
    """build_parse_error_event_dict description mentions error rate."""
    window = datetime(2026, 4, 25, 10, 0, tzinfo=utc)
    result = build_parse_error_event_dict(
        source_id="s3",
        source_name="TAXII Feed",
        parse_ok=2,
        parse_error=8,
        window_bucket=window,
    )
    assert _REQUIRED_KEYS.issubset(result.keys())
    assert result["stix_type"] == "x-monitoring-alert"
    assert result["project_id"] == SENTINEL_PROJECT_ID
    # error rate = 8/10 = 0.80 - description must mention it (formatted as 80.00%)
    assert "80.00%" in result["description"]
    assert "monitoring:parse_error_rate" in result["tags"]
    assert "source:s3" in result["tags"]


def test_uses_sentinel_project_id() -> None:
    """All builders use the locked sentinel project_id."""
    assert SENTINEL_PROJECT_ID == "00000000-0000-0000-0000-000000000000"
    window = datetime(2026, 4, 25, 10, 0, tzinfo=utc)
    for d in [
        build_silence_event_dict(
            source_id="x", source_name="X", last_event_at=window, sla_seconds=3600
        ),
        build_drift_event_dict(
            source_id="x", source_name="X", severity="medium",
            z_score=2.1, baseline_mean=50.0, current_value=70.0, window_bucket=window,
        ),
        build_parse_error_event_dict(
            source_id="x", source_name="X", parse_ok=5, parse_error=5, window_bucket=window
        ),
    ]:
        assert d["project_id"] == "00000000-0000-0000-0000-000000000000"


def test_all_builders_consistent_shape() -> None:
    """All 3 builders produce the same top-level keys."""
    window = datetime(2026, 4, 25, 10, 0, tzinfo=utc)
    dicts = [
        build_silence_event_dict(
            source_id="x", source_name="X", last_event_at=window, sla_seconds=3600
        ),
        build_drift_event_dict(
            source_id="x", source_name="X", severity="low",
            z_score=1.5, baseline_mean=20.0, current_value=25.0, window_bucket=window,
        ),
        build_parse_error_event_dict(
            source_id="x", source_name="X", parse_ok=9, parse_error=1, window_bucket=window
        ),
    ]
    keys_list = [set(d.keys()) for d in dicts]
    assert keys_list[0] == keys_list[1] == keys_list[2]

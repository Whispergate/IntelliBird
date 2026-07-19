"""Canonical event synthesis for monitoring alerts.

Mirrors backend/app/services/brand_synth.py. Emits dict rows that the existing
events INSERT path consumes; the existing webhook fan-out picks them up via
webhook_alert_type_enum (extended in migration 016).

All monitoring events carry project_id = SENTINEL_PROJECT_ID because:
  - events.project_id is NOT NULL since migration 009
  - Monitoring alerts are cross-project / admin-scope (CONTEXT.md decision)
  - Webhook subscriptions for the system project receive these alerts
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Literal

SENTINEL_PROJECT_ID = "00000000-0000-0000-0000-000000000000"
STIX_TYPE = "x-monitoring-alert"

AlertType = Literal["source_silence", "volume_drift", "parse_error_rate"]
Severity = Literal["high", "medium", "low"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _content_hash(source_id: str, alert_type: str, window_bucket_iso: str) -> str:
    """Deterministic sha256 hex digest used for events-table dedup.

    Formula (locked): sha256(source_id + alert_type + window_bucket_iso)
    """
    raw = f"{source_id}{alert_type}{window_bucket_iso}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _base(
    *,
    source_id: str,
    source_name: str,
    alert_type: str,
    severity: str,
    title: str,
    description: str,
    window_bucket_iso: str,
) -> dict:
    """Build the common fields shared by all monitoring event dicts.

    Dict shape mirrors brand_synth.build_event_dict output so the downstream
    events INSERT helper can be reused without modification.
    """
    return {
        "stix_type": STIX_TYPE,
        "stix_id": None,
        "title": title,
        "description": description,
        "observed_at": datetime.now(timezone.utc),
        "tags": [
            "monitoring",
            f"monitoring:{alert_type}",
            f"monitoring:{severity}",
            f"source:{source_id}",
        ],
        "raw_stix": None,
        "content_hash": _content_hash(str(source_id), alert_type, window_bucket_iso),
        "project_id": SENTINEL_PROJECT_ID,
    }


# ---------------------------------------------------------------------------
# Public factories
# ---------------------------------------------------------------------------

def build_silence_event_dict(
    *,
    source_id: str,
    source_name: str,
    last_event_at: datetime | None,
    sla_seconds: float,
    now: datetime | None = None,
) -> dict:
    """Synthesise a canonical event row for a source_silence alert.

    Window bucket is the SLA-aligned hour so repeated alerts within one SLA
    period produce the same content_hash (dedup via ON CONFLICT).

    Args:
        source_id:     Unique source identifier (string or UUID-as-string).
        source_name:   Human-readable source name for titles/descriptions.
        last_event_at: Timestamp of the last ingested event, or None (never).
        sla_seconds:   Maximum allowed silence before an alert fires (seconds).
        now:           Override "current time" for deterministic tests.
    """
    now = now or datetime.now(timezone.utc)
    silent_for: float | None = (
        (now - last_event_at).total_seconds() if last_event_at else None
    )
    # Window bucket = the hour boundary; dedupes repeated alerts within one SLA
    bucket = now.replace(minute=0, second=0, microsecond=0).isoformat()

    silent_hours = silent_for / 3600 if silent_for is not None else float("inf")
    sla_hours = sla_seconds / 3600

    return _base(
        source_id=source_id,
        source_name=source_name,
        alert_type="source_silence",
        severity="high",
        title=f"[source_silence] {source_name} silent for {silent_hours:.1f}h",
        description=(
            f"Source '{source_name}' (id={source_id}) has not delivered any events "
            f"for {silent_hours:.1f} hours (SLA: {sla_hours:.1f}h). "
            f"Last event at: {last_event_at.isoformat() if last_event_at else 'never'}."
        ),
        window_bucket_iso=bucket,
    )


def build_drift_event_dict(
    *,
    source_id: str,
    source_name: str,
    severity: str,
    z_score: float,
    baseline_mean: float,
    current_value: float,
    window_bucket: datetime | str,
) -> dict:
    """Synthesise a canonical event row for a volume_drift alert.

    Args:
        source_id:      Unique source identifier.
        source_name:    Human-readable source name.
        severity:       "high" (z>3) or "medium" (z>2).
        z_score:        Computed z-score against 7d EWMA baseline.
        baseline_mean:  7d EWMA baseline mean hourly count.
        current_value:  Current hourly event count.
        window_bucket:  1h bucket timestamp (datetime or ISO string).
    """
    bucket_iso = (
        window_bucket.isoformat()
        if hasattr(window_bucket, "isoformat")
        else str(window_bucket)
    )
    return _base(
        source_id=source_id,
        source_name=source_name,
        alert_type="volume_drift",
        severity=severity,
        title=f"[volume_drift] {source_name} z={z_score:.2f} ({severity})",
        description=(
            f"Source '{source_name}' hourly event count {current_value:.1f} deviates "
            f"{z_score:+.2f}σ from 7d EWMA baseline ({baseline_mean:.2f}). "
            f"Severity threshold: high z>3, medium z>2."
        ),
        window_bucket_iso=bucket_iso,
    )


def build_parse_error_event_dict(
    *,
    source_id: str,
    source_name: str,
    parse_ok: int,
    parse_error: int,
    window_bucket: datetime | str,
) -> dict:
    """Synthesise a canonical event row for a parse_error_rate alert.

    Args:
        source_id:     Unique source identifier.
        source_name:   Human-readable source name.
        parse_ok:      Count of successfully parsed items in the window.
        parse_error:   Count of failed parse attempts in the window.
        window_bucket: 1h bucket timestamp (datetime or ISO string).
    """
    total = parse_ok + parse_error
    rate = parse_error / total if total > 0 else 0.0
    bucket_iso = (
        window_bucket.isoformat()
        if hasattr(window_bucket, "isoformat")
        else str(window_bucket)
    )
    return _base(
        source_id=source_id,
        source_name=source_name,
        alert_type="parse_error_rate",
        severity="high",
        title=f"[parse_error_rate] {source_name} {rate:.0%} errors",
        description=(
            f"Source '{source_name}' parse error rate {rate:.2%} over last 1h "
            f"({parse_error} errors / {total} total). Threshold: 50%."
        ),
        window_bucket_iso=bucket_iso,
    )

"""MON-01 silence detection unit tests — plan 16-06.

Tests that silence_check_all() synthesises a canonical monitoring event when
a source has not produced any events within its configured SLA window, and that
maintenance windows and burst suppression suppress that alert.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, call
import uuid

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SOURCE_ID = str(uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"))
_SOURCE_NAME = "Test RSS Feed"
_NOW = datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc)
_LAST_EVENT_AT = _NOW - timedelta(hours=25)  # 25h ago — exceeds 24h RSS SLA


def _make_source_row(
    source_id: str = _SOURCE_ID,
    name: str = _SOURCE_NAME,
    feed_type: str = "rss",
    last_event_at: datetime | None = _LAST_EVENT_AT,
    monitoring_config: dict | None = None,
    created_at: datetime | None = None,
):
    """Build a fake sources table row mapping."""
    row = MagicMock()
    row.__getitem__ = lambda self, key: {
        "id": source_id,
        "name": name,
        "feed_type": feed_type,
        "last_event_at": last_event_at,
        "monitoring_config": monitoring_config or {},
        "created_at": created_at or (_NOW - timedelta(days=30)),
    }[key]
    return row


def _make_mock_session(rows=None):
    """Return a mock sync SQLAlchemy session yielding the given rows."""
    session = MagicMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows or []
    session.execute.return_value = result
    return session


def _make_mock_redis(suppressed: bool = False):
    """Return a mock sync Redis client."""
    r = MagicMock()
    pipe = MagicMock()
    # pipeline().execute() returns [N_removed, count]
    # If suppressed=True, count=5 (at cap)
    pipe.execute.return_value = [0, 5 if suppressed else 0]
    r.pipeline.return_value = pipe
    return r


# ---------------------------------------------------------------------------
# test_silence_check_emits_event
# ---------------------------------------------------------------------------


def test_silence_check_emits_event() -> None:
    """Source silent 25h > 24h RSS SLA — build_silence_event_dict called, event dispatched."""
    from app.scheduler.monitoring_jobs import silence_check_all_job

    source_row = _make_source_row()
    mock_session = _make_mock_session(rows=[source_row])
    mock_redis = _make_mock_redis(suppressed=False)

    dispatched_events = []

    def _fake_persist(session, event_dict):
        dispatched_events.append(event_dict)

    ctx_session = MagicMock()
    ctx_session.__enter__ = MagicMock(return_value=mock_session)
    ctx_session.__exit__ = MagicMock(return_value=False)

    ctx_redis = MagicMock()
    ctx_redis.__enter__ = MagicMock(return_value=mock_redis)
    ctx_redis.__exit__ = MagicMock(return_value=False)

    with patch("app.scheduler.monitoring_jobs._sync_session", return_value=ctx_session), \
         patch("app.scheduler.monitoring_jobs._sync_redis", return_value=ctx_redis), \
         patch("app.scheduler.monitoring_jobs.is_maintenance_active", return_value=False), \
         patch("app.scheduler.monitoring_jobs._persist_canonical_event", side_effect=_fake_persist), \
         patch("app.scheduler.monitoring_jobs._get_now", return_value=_NOW):
        silence_check_all_job()

    assert len(dispatched_events) == 1, "Expected 1 event dispatched for silent source"
    event = dispatched_events[0]
    assert event["stix_type"] == "x-monitoring-alert"
    assert "monitoring:source_silence" in event["tags"]
    assert f"source:{_SOURCE_ID}" in event["tags"]


# ---------------------------------------------------------------------------
# test_suppressed_by_maintenance
# ---------------------------------------------------------------------------


def test_suppressed_by_maintenance() -> None:
    """Active maintenance window suppresses silence alert."""
    from app.scheduler.monitoring_jobs import silence_check_all_job

    source_row = _make_source_row()
    mock_session = _make_mock_session(rows=[source_row])
    mock_redis = _make_mock_redis(suppressed=False)

    dispatched_events = []

    def _fake_persist(session, event_dict):
        dispatched_events.append(event_dict)

    ctx_session = MagicMock()
    ctx_session.__enter__ = MagicMock(return_value=mock_session)
    ctx_session.__exit__ = MagicMock(return_value=False)

    ctx_redis = MagicMock()
    ctx_redis.__enter__ = MagicMock(return_value=mock_redis)
    ctx_redis.__exit__ = MagicMock(return_value=False)

    with patch("app.scheduler.monitoring_jobs._sync_session", return_value=ctx_session), \
         patch("app.scheduler.monitoring_jobs._sync_redis", return_value=ctx_redis), \
         patch("app.scheduler.monitoring_jobs.is_maintenance_active", return_value=True), \
         patch("app.scheduler.monitoring_jobs._persist_canonical_event", side_effect=_fake_persist), \
         patch("app.scheduler.monitoring_jobs._get_now", return_value=_NOW):
        silence_check_all_job()

    assert len(dispatched_events) == 0, "Maintenance window must suppress silence alert"


# ---------------------------------------------------------------------------
# test_silence_respects_per_source_sla
# ---------------------------------------------------------------------------


def test_silence_respects_per_source_sla() -> None:
    """Source with custom 6h SLA, silent 5h, does NOT trigger alert (within SLA)."""
    from app.scheduler.monitoring_jobs import silence_check_all_job

    # 5h silent — below 6h custom SLA
    last_event_at = _NOW - timedelta(hours=5)
    source_row = _make_source_row(
        last_event_at=last_event_at,
        monitoring_config={"last_event_sla_seconds": 21600},  # 6h
    )
    mock_session = _make_mock_session(rows=[source_row])
    mock_redis = _make_mock_redis(suppressed=False)

    dispatched_events = []

    def _fake_persist(session, event_dict):
        dispatched_events.append(event_dict)

    ctx_session = MagicMock()
    ctx_session.__enter__ = MagicMock(return_value=mock_session)
    ctx_session.__exit__ = MagicMock(return_value=False)

    ctx_redis = MagicMock()
    ctx_redis.__enter__ = MagicMock(return_value=mock_redis)
    ctx_redis.__exit__ = MagicMock(return_value=False)

    with patch("app.scheduler.monitoring_jobs._sync_session", return_value=ctx_session), \
         patch("app.scheduler.monitoring_jobs._sync_redis", return_value=ctx_redis), \
         patch("app.scheduler.monitoring_jobs.is_maintenance_active", return_value=False), \
         patch("app.scheduler.monitoring_jobs._persist_canonical_event", side_effect=_fake_persist), \
         patch("app.scheduler.monitoring_jobs._get_now", return_value=_NOW):
        silence_check_all_job()

    assert len(dispatched_events) == 0, "Source within custom SLA must not trigger alert"


# ---------------------------------------------------------------------------
# test_burst_suppression_prevents_dispatch
# ---------------------------------------------------------------------------


def test_burst_suppression_prevents_dispatch() -> None:
    """Burst cap reached for source — alert suppressed even though SLA is breached."""
    from app.scheduler.monitoring_jobs import silence_check_all_job

    source_row = _make_source_row()
    mock_session = _make_mock_session(rows=[source_row])
    mock_redis = _make_mock_redis(suppressed=True)  # cap reached

    dispatched_events = []

    def _fake_persist(session, event_dict):
        dispatched_events.append(event_dict)

    ctx_session = MagicMock()
    ctx_session.__enter__ = MagicMock(return_value=mock_session)
    ctx_session.__exit__ = MagicMock(return_value=False)

    ctx_redis = MagicMock()
    ctx_redis.__enter__ = MagicMock(return_value=mock_redis)
    ctx_redis.__exit__ = MagicMock(return_value=False)

    with patch("app.scheduler.monitoring_jobs._sync_session", return_value=ctx_session), \
         patch("app.scheduler.monitoring_jobs._sync_redis", return_value=ctx_redis), \
         patch("app.scheduler.monitoring_jobs.is_maintenance_active", return_value=False), \
         patch("app.scheduler.monitoring_jobs._persist_canonical_event", side_effect=_fake_persist), \
         patch("app.scheduler.monitoring_jobs._get_now", return_value=_NOW):
        silence_check_all_job()

    assert len(dispatched_events) == 0, "Burst-suppressed source must not dispatch alert"

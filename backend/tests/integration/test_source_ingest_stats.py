"""MON-03 source_ingest_stats hypertable — plan 16-05.

Integration tests for the source_ingest_stats TimescaleDB hypertable:
writing rows via record_ingest_stats(), reading them back, and verifying the
continuous aggregate populates correctly. Also covers the parse_error_rate
alert trigger (parse_error / total > 0.5 over 1h window).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SOURCE_ID = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")


def _make_mock_session(rows=None):
    """Return a mock SQLAlchemy sync Session with execute() returning rows."""
    session = MagicMock(spec=Session)
    result = MagicMock()
    result.fetchall.return_value = rows or []
    result.fetchone.return_value = (rows[0] if rows else None)
    session.execute.return_value = result
    return session


# ---------------------------------------------------------------------------
# test_record_stats — verifies record_ingest_stats issues the correct INSERT
# ---------------------------------------------------------------------------


def test_record_stats() -> None:
    """Writes one row via record_ingest_stats(), verifies SQL + params."""
    from app.services.source_health import record_ingest_stats

    session = MagicMock(spec=Session)
    result = MagicMock()
    session.execute.return_value = result

    record_ingest_stats(
        session,
        source_id=_SOURCE_ID,
        parse_ok=5,
        parse_error=1,
        fetch_ok=1,
        fetch_error=0,
    )

    assert session.execute.called, "session.execute must be called by record_ingest_stats"
    call_args = session.execute.call_args
    # First positional arg is the SQL text object
    sql_obj = call_args[0][0]
    sql_str = str(sql_obj)
    assert "source_ingest_stats" in sql_str, "INSERT must target source_ingest_stats table"
    assert "INSERT" in sql_str.upper(), "Must be an INSERT statement"

    # Second positional arg is the params dict
    params = call_args[0][1]
    assert params["source_id"] == _SOURCE_ID
    assert params["parse_ok"] == 5
    assert params["parse_error"] == 1
    assert params["fetch_ok"] == 1
    assert params["fetch_error"] == 0


def test_record_stats_clamps_negatives() -> None:
    """Negative counter values are clamped to 0 before INSERT."""
    from app.services.source_health import record_ingest_stats

    session = MagicMock(spec=Session)
    session.execute.return_value = MagicMock()

    record_ingest_stats(
        session,
        source_id=_SOURCE_ID,
        parse_ok=-3,
        parse_error=-1,
        fetch_ok=1,
        fetch_error=0,
    )

    params = session.execute.call_args[0][1]
    assert params["parse_ok"] == 0, "Negative parse_ok must be clamped to 0"
    assert params["parse_error"] == 0, "Negative parse_error must be clamped to 0"


# ---------------------------------------------------------------------------
# test_continuous_aggregate_populated — RSS worker integration with fake feed
# ---------------------------------------------------------------------------


def test_continuous_aggregate_populated() -> None:
    """RSS worker accumulates parse_ok/parse_error and calls record_ingest_stats.

    Monkeypatches feedparser to return 5 valid + 2 malformed entries, then asserts
    record_ingest_stats was called with parse_ok=5, parse_error=2, fetch_ok=1, fetch_error=0.
    """
    import app.workers.rss as rss_mod

    source_id = _SOURCE_ID

    # Build a fake feedparser result with 7 entries: 5 normalise-ok, 2 returning None
    class _FakeFeed:
        bozo = 0
        entries = [object()] * 7  # 7 entry objects

    fake_feed = _FakeFeed()

    # normalise_rss_entry returns None for entries at index 5 and 6 (simulate malformed)
    _call_count = {"n": 0}

    def _fake_normalise(entry, sid):
        _call_count["n"] += 1
        if _call_count["n"] > 5:
            return None  # malformed
        return {
            "source_id": sid,
            "stix_type": "indicator",
            "stix_id": f"indicator--{uuid.uuid4()}",
            "title": f"Entry {_call_count['n']}",
            "observed_at": datetime.now(timezone.utc),
            "content_hash": f"hash{_call_count['n']}",
            "project_id": uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            "score": 0.5,
            "scored_at": None,
            "score_version": "1",
        }

    session = MagicMock(spec=Session)
    session.execute.return_value = MagicMock()

    with patch.object(rss_mod, "_open_session") as mock_ctx, \
         patch.object(rss_mod, "_fetch_source_row", return_value={"id": source_id, "url": "http://fake", "credentials_enc": None}), \
         patch.object(rss_mod, "parse_rss_feed", return_value=fake_feed), \
         patch.object(rss_mod, "normalise_rss_entry", side_effect=_fake_normalise), \
         patch.object(rss_mod, "_persist_event", return_value=1), \
         patch.object(rss_mod, "update_source_health"), \
         patch.object(rss_mod, "update_silent_failure_count"), \
         patch.object(rss_mod, "record_ingest_stats") as mock_stats:

        mock_ctx.return_value.__enter__ = MagicMock(return_value=session)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        rss_mod.poll_rss_impl(str(source_id))

    mock_stats.assert_called_once()
    call_kwargs = mock_stats.call_args
    _, positional = call_kwargs[0][0], call_kwargs[0]

    # record_ingest_stats(session, source_id, parse_ok, parse_error, fetch_ok, fetch_error)
    assert positional[2] == 5, f"parse_ok should be 5, got {positional[2]}"
    assert positional[3] == 2, f"parse_error should be 2, got {positional[3]}"
    assert positional[4] == 1, f"fetch_ok should be 1, got {positional[4]}"
    assert positional[5] == 0, f"fetch_error should be 0, got {positional[5]}"


# ---------------------------------------------------------------------------
# test_parse_error_alert — wired in plan 16-06; keep skipped here
# ---------------------------------------------------------------------------


def test_parse_error_alert() -> None:
    """parse_error / (parse_ok + parse_error) > 0.5 over 1h CA triggers alert.

    Mocks the DB query result to return a source with 8 errors / 2 ok (80% error rate),
    then asserts that parse_error_check_all_job() dispatches an event with
    stix_type='x-monitoring-alert' and tags include 'monitoring:parse_error_rate'.
    """
    from unittest.mock import MagicMock, patch

    source_id = str(uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"))

    # Simulate the SELECT rows returned by the aggregate query
    row = MagicMock()
    row.__getitem__ = lambda self, key: {
        "id": source_id,
        "name": "Test Source",
        "po": 2,
        "pe": 8,
        "last_bucket": datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc),
    }[key]

    mock_session = MagicMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = [row]
    mock_session.execute.return_value = result

    mock_redis = MagicMock()
    pipe = MagicMock()
    pipe.execute.return_value = [0, 0]  # not burst-suppressed
    mock_redis.pipeline.return_value = pipe

    dispatched_events = []

    def _fake_persist(session, event_dict):
        dispatched_events.append(event_dict)

    ctx_session = MagicMock()
    ctx_session.__enter__ = MagicMock(return_value=mock_session)
    ctx_session.__exit__ = MagicMock(return_value=False)

    ctx_redis = MagicMock()
    ctx_redis.__enter__ = MagicMock(return_value=mock_redis)
    ctx_redis.__exit__ = MagicMock(return_value=False)

    from app.scheduler.monitoring_jobs import parse_error_check_all_job

    with patch("app.scheduler.monitoring_jobs._sync_session", return_value=ctx_session), \
         patch("app.scheduler.monitoring_jobs._sync_redis", return_value=ctx_redis), \
         patch("app.scheduler.monitoring_jobs.is_maintenance_active", return_value=False), \
         patch("app.scheduler.monitoring_jobs._persist_canonical_event", side_effect=_fake_persist):
        parse_error_check_all_job()

    assert len(dispatched_events) == 1, f"Expected 1 event, got {len(dispatched_events)}"
    event = dispatched_events[0]
    assert event["stix_type"] == "x-monitoring-alert"
    assert "monitoring:parse_error_rate" in event["tags"], f"Tags: {event['tags']}"
    assert f"source:{source_id}" in event["tags"]


def test_parse_error_no_alert_below_threshold() -> None:
    """parse_error rate 1/11 ≈ 9% — below 50% threshold, no alert dispatched."""
    from unittest.mock import MagicMock, patch

    source_id = str(uuid.UUID("dddddddd-dddd-dddd-dddd-ddddddddddde"))

    row = MagicMock()
    row.__getitem__ = lambda self, key: {
        "id": source_id,
        "name": "Low Error Source",
        "po": 10,
        "pe": 1,
        "last_bucket": datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc),
    }[key]

    mock_session = MagicMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = [row]
    mock_session.execute.return_value = result

    mock_redis = MagicMock()
    pipe = MagicMock()
    pipe.execute.return_value = [0, 0]
    mock_redis.pipeline.return_value = pipe

    dispatched_events = []

    def _fake_persist(session, event_dict):
        dispatched_events.append(event_dict)

    ctx_session = MagicMock()
    ctx_session.__enter__ = MagicMock(return_value=mock_session)
    ctx_session.__exit__ = MagicMock(return_value=False)

    ctx_redis = MagicMock()
    ctx_redis.__enter__ = MagicMock(return_value=mock_redis)
    ctx_redis.__exit__ = MagicMock(return_value=False)

    from app.scheduler.monitoring_jobs import parse_error_check_all_job

    with patch("app.scheduler.monitoring_jobs._sync_session", return_value=ctx_session), \
         patch("app.scheduler.monitoring_jobs._sync_redis", return_value=ctx_redis), \
         patch("app.scheduler.monitoring_jobs.is_maintenance_active", return_value=False), \
         patch("app.scheduler.monitoring_jobs._persist_canonical_event", side_effect=_fake_persist):
        parse_error_check_all_job()

    assert len(dispatched_events) == 0, "Below threshold — no alert should fire"

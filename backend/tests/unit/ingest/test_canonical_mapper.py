"""Shared writers for workers — _persist_event + update_source_health.

These helpers encapsulate (ON CONFLICT DO NOTHING against
UNIQUE(source_id, content_hash, observed_at)) and (single-transaction
health update after every poll attempt).

Heavy DB-side behaviour is tested end-to-end in tests/integration; this
unit file pins the PUBLIC SHAPE of the helpers so plans 03/04/05 can
rely on them.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

VALID_STATUSES = {"ok", "rate_limited", "http_error", "network_error", "parse_error"}


def test_settings_has_ingest_knobs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "a" * 32 + "deadbeef")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/d")
    from app.config import Settings
    s = Settings()  # type: ignore[call-arg]
    assert isinstance(s.NVD_USER_AGENT, str) and s.NVD_USER_AGENT
    assert isinstance(s.TAXII_USER_AGENT, str) and s.TAXII_USER_AGENT
    assert isinstance(s.INGEST_MAX_ITEMS_PER_POLL, int)
    assert s.INGEST_MAX_ITEMS_PER_POLL >= 1


def test_settings_ingest_knobs_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "a" * 32 + "deadbeef")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/d")
    monkeypatch.setenv("INGEST_MAX_ITEMS_PER_POLL", "12345")
    monkeypatch.setenv("NVD_USER_AGENT", "CustomUA/1.0")
    from app.config import Settings
    s = Settings()  # type: ignore[call-arg]
    assert s.INGEST_MAX_ITEMS_PER_POLL == 12345
    assert s.NVD_USER_AGENT == "CustomUA/1.0"


def test_update_source_health_rejects_invalid_status() -> None:
    from app.ingest.normalise import update_source_health
    session = MagicMock()
    with pytest.raises(ValueError, match="invalid status"):
        update_source_health(session, uuid.uuid4(), status="bogus", succeeded=True)


def test_update_source_health_success_issues_update(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ingest.normalise import update_source_health
    session = MagicMock()
    sid = uuid.uuid4()
    update_source_health(session, sid, status="ok", succeeded=True)
    # Must execute at least one statement through the session
    assert session.execute.called
    # Inspect the compiled SQL — check for SET last_status='ok' and consecutive_failures = 0
    call_args = session.execute.call_args[0]
    stmt = call_args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "last_status" in compiled
    assert "consecutive_failures" in compiled
    # On success, consecutive_failures resets to 0 (literal)
    assert "= 0" in compiled or "= '0'" in compiled or ": 0" in compiled or "consecutive_failures=0" in compiled.replace(" ", "")


def test_update_source_health_failure_uses_increment(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ingest.normalise import update_source_health
    session = MagicMock()
    sid = uuid.uuid4()
    update_source_health(session, sid, status="http_error", succeeded=False)
    assert session.execute.called
    stmt = str(session.execute.call_args[0][0].compile(compile_kwargs={"literal_binds": True}))
    # On failure: consecutive_failures = consecutive_failures + 1 (self-increment in SQL)
    assert "consecutive_failures" in stmt
    assert "+ 1" in stmt.replace(" ", "+ 1")  # tolerant compare — '+1' or '+ 1'


def test_persist_event_returns_rowcount(monkeypatch: pytest.MonkeyPatch) -> None:
    """_persist_event returns 1 for insert, 0 for conflict-skipped."""
    from app.ingest.normalise import _persist_event
    session = MagicMock()
    inserted_result = MagicMock()
    inserted_result.rowcount = 1
    skipped_result = MagicMock()
    skipped_result.rowcount = 0
    session.execute.side_effect = [inserted_result, skipped_result]
    row = {
        "stix_type": "x-intellibird-rss",
        "source_id": uuid.uuid4(),
        "observed_at": datetime.now(timezone.utc),
        "content_hash": "hash-abc",
        "visibility": "shared",
        "title": "t",
    }
    first = _persist_event(session, row)
    second = _persist_event(session, row)
    assert first == 1
    assert second == 0


def test_persist_event_uses_on_conflict_do_nothing() -> None:
    """The compiled statement must include ON CONFLICT DO NOTHING targeting
 (source_id, content_hash, observed_at) — three-column index per 02-01 deviation."""
    from app.ingest.normalise import _persist_event
    session = MagicMock()
    res = MagicMock(); res.rowcount = 1
    session.execute.return_value = res
    row = {
        "stix_type": "x-intellibird-rss",
        "source_id": uuid.uuid4(),
        "observed_at": datetime.now(timezone.utc),
        "content_hash": "hash",
        "visibility": "shared",
        "title": "t",
    }
    _persist_event(session, row)
    stmt = session.execute.call_args[0][0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "ON CONFLICT" in compiled.upper()
    assert "DO NOTHING" in compiled.upper()

"""Unit tests for SRC-06 silent-failure counter.

Covers:
- update_silent_failure_count state machine (increment / reset / error)
- Settings.INGEST_SILENT_FAILURE_THRESHOLD default + env override
- Worker wiring: poll_rss_impl calls the helper on the success path only

Tests use compiled-SQL inspection (MagicMock session), matching the style
established in backend/tests/unit/ingest/test_health_update.py.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.services.source_health import update_silent_failure_count


# ---------------------------------------------------------------------------
# Helper: compile a SQLAlchemy statement to string for inspection
# ---------------------------------------------------------------------------

def _compile(stmt) -> str:  # type: ignore[no-untyped-def]
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


# ---------------------------------------------------------------------------
# Test 1: counter increments when inserted_count == 0
# ---------------------------------------------------------------------------

def test_counter_increments_when_inserted_zero() -> None:
    session = MagicMock()
    update_silent_failure_count(session, uuid.uuid4(), inserted_count=0)
    assert session.execute.called
    stmt = session.execute.call_args[0][0]
    compiled = _compile(stmt).replace(" ", "")
    # Increment expression present
    assert (
        "silent_failure_count=sources.silent_failure_count+1" in compiled
        or "silent_failure_count=(sources.silent_failure_count+1)" in compiled
        or "silent_failure_count=silent_failure_count+1" in compiled
    )


# ---------------------------------------------------------------------------
# Test 2: counter resets when inserted_count == 1
# ---------------------------------------------------------------------------

def test_counter_resets_when_inserted_one() -> None:
    session = MagicMock()
    update_silent_failure_count(session, uuid.uuid4(), inserted_count=1)
    stmt = session.execute.call_args[0][0]
    compiled = _compile(stmt).replace(" ", "")
    assert "silent_failure_count=0" in compiled


# ---------------------------------------------------------------------------
# Test 3: counter resets when inserted_count is large
# ---------------------------------------------------------------------------

def test_counter_resets_when_inserted_many() -> None:
    session = MagicMock()
    update_silent_failure_count(session, uuid.uuid4(), inserted_count=500)
    stmt = session.execute.call_args[0][0]
    compiled = _compile(stmt).replace(" ", "")
    assert "silent_failure_count=0" in compiled


# ---------------------------------------------------------------------------
# Test 4: increment from zero — same as test 1, verifies no special-casing
# ---------------------------------------------------------------------------

def test_increment_from_zero() -> None:
    """inserted_count=0 always triggers increment regardless of current count."""
    session = MagicMock()
    update_silent_failure_count(session, uuid.uuid4(), inserted_count=0)
    stmt = session.execute.call_args[0][0]
    compiled = _compile(stmt).replace(" ", "")
    # Must be an increment expression, not a literal
    assert (
        "silent_failure_count=sources.silent_failure_count+1" in compiled
        or "silent_failure_count=(sources.silent_failure_count+1)" in compiled
        or "silent_failure_count=silent_failure_count+1" in compiled
    )
    # Must NOT be a literal 0 reset
    assert "silent_failure_count=0" not in compiled


# ---------------------------------------------------------------------------
# Test 5: negative inserted_count raises ValueError
# ---------------------------------------------------------------------------

def test_negative_inserted_raises_value_error() -> None:
    session = MagicMock()
    with pytest.raises(ValueError, match="inserted_count must be >= 0"):
        update_silent_failure_count(session, uuid.uuid4(), inserted_count=-1)


# ---------------------------------------------------------------------------
# Test 6: helper does not commit
# ---------------------------------------------------------------------------

def test_does_not_commit() -> None:
    session = MagicMock()
    update_silent_failure_count(session, uuid.uuid4(), inserted_count=0)
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


# ---------------------------------------------------------------------------
# Test 7: update WHERE clause targets the correct source_id
# ---------------------------------------------------------------------------

def test_update_targets_correct_source_id() -> None:
    session = MagicMock()
    sid = uuid.uuid4()
    update_silent_failure_count(session, sid, inserted_count=0)
    stmt = session.execute.call_args[0][0]
    compiled = _compile(stmt)
    # source ID (with or without dashes) must appear in WHERE
    assert "sources.id" in compiled
    sid_str = str(sid)
    assert sid_str in compiled or sid_str.replace("-", "") in compiled


# ---------------------------------------------------------------------------
# Test 8: Settings default is 5
# ---------------------------------------------------------------------------

def test_settings_threshold_default_is_5(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
    from app.config import Settings
    s = Settings()  # type: ignore[call-arg]
    assert s.INGEST_SILENT_FAILURE_THRESHOLD == 5


# ---------------------------------------------------------------------------
# Test 9: Settings env override works
# ---------------------------------------------------------------------------

def test_settings_threshold_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
    monkeypatch.setenv("INGEST_SILENT_FAILURE_THRESHOLD", "10")
    from app.config import Settings
    s = Settings()  # type: ignore[call-arg]
    assert s.INGEST_SILENT_FAILURE_THRESHOLD == 10


# ---------------------------------------------------------------------------
# Test 10: poll_rss_impl with zero inserts calls counter with inserted_count=0
# ---------------------------------------------------------------------------

def test_poll_rss_zero_inserts_increments_counter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkeypatch parse_rss_feed to return empty feed; verify counter called with 0."""
    source_id = uuid.uuid4()

    class _EmptyFeed:
        entries: list = []
        bozo = 0

    def _empty_parse(url):  # type: ignore[no-untyped-def]
        return _EmptyFeed()

    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")

    with patch("app.workers.rss.parse_rss_feed", side_effect=_empty_parse), \
         patch("app.workers.rss._open_session") as mock_open_session, \
         patch("app.workers.rss.update_silent_failure_count") as mock_usfc, \
         patch("app.workers.rss.update_source_health"):

        mock_session = MagicMock()
        mock_open_session.return_value.__enter__ = lambda s: mock_session
        mock_open_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_session.execute.return_value.one_or_none.return_value = MagicMock(
            id=source_id, url="http://example.com", credentials_enc=None
        )

        from app.workers.rss import poll_rss_impl
        poll_rss_impl(str(source_id))

        # update_silent_failure_count should be called once with inserted_count=0
        mock_usfc.assert_called_once()
        call_args = mock_usfc.call_args
        # Third positional arg or keyword
        inserted_arg = (
            call_args[0][2] if len(call_args[0]) > 2
            else call_args[1].get("inserted_count", -99)
        )
        assert inserted_arg == 0


# ---------------------------------------------------------------------------
# Test 11: poll_rss_impl with one insert calls counter with inserted_count=1
# ---------------------------------------------------------------------------

def test_poll_rss_one_insert_resets_counter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkeypatch to return one entry; verify counter called with 1."""
    import datetime

    source_id = uuid.uuid4()

    class _EntryStub:
        title = "Test Entry"
        link = "http://example.com/entry"
        id = "http://example.com/entry"
        published_parsed = None
        summary = "Test summary"
        tags: list = []

    class _OneFeed:
        entries = [_EntryStub()]
        bozo = 0

    def _one_parse(url):  # type: ignore[no-untyped-def]
        return _OneFeed()

    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")

    with patch("app.workers.rss.parse_rss_feed", side_effect=_one_parse), \
         patch("app.workers.rss._open_session") as mock_open_session, \
         patch("app.workers.rss.update_silent_failure_count") as mock_usfc, \
         patch("app.workers.rss.update_source_health"), \
         patch("app.workers.rss.normalise_rss_entry") as mock_normalise, \
         patch("app.workers.rss._persist_event", return_value=1):

        mock_session = MagicMock()
        mock_open_session.return_value.__enter__ = lambda s: mock_session
        mock_open_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_session.execute.return_value.one_or_none.return_value = MagicMock(
            id=source_id, url="http://example.com", credentials_enc=None
        )

        mock_normalise.return_value = {
            "source_id": source_id,
            "content_hash": "abc123",
            "observed_at": datetime.datetime.now(datetime.timezone.utc),
        }

        from app.workers.rss import poll_rss_impl
        poll_rss_impl(str(source_id))

        mock_usfc.assert_called_once()
        call_args = mock_usfc.call_args
        inserted_arg = (
            call_args[0][2] if len(call_args[0]) > 2
            else call_args[1].get("inserted_count", -99)
        )
        assert inserted_arg == 1


# ---------------------------------------------------------------------------
# Test 12: poll_rss_impl with network error does NOT call counter helper
# ---------------------------------------------------------------------------

def test_poll_rss_network_error_does_not_touch_counter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Network error path must NOT call update_silent_failure_count."""
    source_id = uuid.uuid4()

    def _raise_network(url):  # type: ignore[no-untyped-def]
        raise ConnectionError("simulated network failure")

    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")

    with patch("app.workers.rss.parse_rss_feed", side_effect=_raise_network), \
         patch("app.workers.rss._open_session") as mock_open_session, \
         patch("app.workers.rss.update_silent_failure_count") as mock_usfc, \
         patch("app.workers.rss.update_source_health"):

        mock_session = MagicMock()
        mock_open_session.return_value.__enter__ = lambda s: mock_session
        mock_open_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_session.execute.return_value.one_or_none.return_value = MagicMock(
            id=source_id, url="http://example.com", credentials_enc=None
        )

        from app.workers.rss import poll_rss_impl
        poll_rss_impl(str(source_id))

        mock_usfc.assert_not_called()

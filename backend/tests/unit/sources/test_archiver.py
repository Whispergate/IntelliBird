"""Unit tests for app.services.archiver - STO-01, STO-03, STO-04.

All tests use mocked sessions (no live DB required). The mock session
captures execute calls so we can assert SQL shape and bind params.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(rowcount: int = 0, source_rows: list | None = None):
    """Create a mock SQLAlchemy Session for unit tests.

 Args:
 rowcount: The rowcount returned by execute on DML statements.
 source_rows: Rows returned when SELECT... FROM sources is called.
"""
    session = MagicMock()

    # Default execute result for DML (DELETE/UPDATE)
    dml_result = MagicMock()
    dml_result.rowcount = rowcount

    if source_rows is not None:
        # First call to execute returns source rows, subsequent calls return dml_result
        select_result = MagicMock()
        select_result.all.return_value = source_rows
        session.execute.side_effect = [select_result] + [MagicMock(rowcount=rowcount) for _ in source_rows]
    else:
        session.execute.return_value = dml_result

    return session


def _extract_sql(session: MagicMock, call_index: int = 0) -> str:
    """Extract the SQL text from a session.execute call."""
    call_args = session.execute.call_args_list[call_index]
    sql_obj = call_args[0][0]
    # text objects have a.text attribute
    return str(sql_obj) if not hasattr(sql_obj, "text") else sql_obj.text


# ---------------------------------------------------------------------------
# _archive_source tests
# ---------------------------------------------------------------------------

class TestArchiveSourceKeep:
    def test_archive_keep_policy_issues_no_sql(self):
        """keep policy should return 0 without executing any SQL."""
        from app.services.archiver import _archive_source

        session = MagicMock()
        result = _archive_source(session, "source-uuid", 30, "keep")

        assert result == 0
        session.execute.assert_not_called()


class TestArchiveSourceDrop:
    def test_archive_drop_policy_issues_delete(self):
        """drop policy must issue DELETE FROM events with correct WHERE clauses."""
        from app.services.archiver import _archive_source

        session = _make_session(rowcount=0)
        _archive_source(session, "source-uuid", 30, "drop")

        assert session.execute.called
        sql = _extract_sql(session)
        assert "DELETE FROM events" in sql
        assert "archived = false" in sql
        assert "observed_at < now() -" in sql
        assert "source_id = :sid" in sql

    def test_archive_rowcount_returned(self):
        """_archive_source should return the rowcount from the DML result."""
        from app.services.archiver import _archive_source

        session = _make_session(rowcount=7)
        result = _archive_source(session, "source-uuid", 30, "drop")

        assert result == 7

    def test_archive_drop_passes_correct_params(self):
        """drop policy must bind sid and days correctly."""
        from app.services.archiver import _archive_source

        session = _make_session(rowcount=0)
        _archive_source(session, "abc-123", 14, "drop")

        call_args = session.execute.call_args_list[0]
        params = call_args[0][1]
        assert params["sid"] == "abc-123"
        assert params["days"] == "14"


class TestArchiveSourceMoveToCold:
    def test_archive_move_to_cold_policy_issues_update_set_archived_true(self):
        """move-to-cold policy must issue UPDATE events SET archived=true."""
        from app.services.archiver import _archive_source

        session = _make_session(rowcount=0)
        _archive_source(session, "source-uuid", 30, "move-to-cold")

        assert session.execute.called
        sql = _extract_sql(session)
        assert "UPDATE events" in sql
        assert "SET archived = true" in sql
        assert "archived = false" in sql  # WHERE guard prevents re-archiving
        assert "observed_at < now() -" in sql
        assert "source_id = :sid" in sql

    def test_archive_move_to_cold_rowcount_returned(self):
        """move-to-cold should return rowcount."""
        from app.services.archiver import _archive_source

        session = _make_session(rowcount=3)
        result = _archive_source(session, "source-uuid", 7, "move-to-cold")

        assert result == 3


class TestArchiveSourceUnknownPolicy:
    def test_archive_unknown_policy_logs_warning_and_returns_zero(self, caplog):
        """Unknown policy should log archiver_unknown_policy warning and return 0."""
        from app.services.archiver import _archive_source

        with caplog.at_level(logging.WARNING, logger="app.services.archiver"):
            result = _archive_source(MagicMock(), "source-uuid", 30, "bogus")

        assert result == 0
        assert any("archiver_unknown_policy" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# archive_once tests
# ---------------------------------------------------------------------------

class TestArchiveOnce:
    def _build_source_row(self, sid: str, days: int, policy: str):
        """Build a mock source row tuple."""
        return (sid, days, policy)

    def test_archive_once_processes_all_sources(self):
        """archive_once must call _archive_source for each source row."""
        from app.services import archiver

        source_rows = [
            self._build_source_row("s1", 30, "keep"),
            self._build_source_row("s2", 7, "drop"),
            self._build_source_row("s3", 14, "move-to-cold"),
        ]
        session = _make_session(source_rows=source_rows)

        with patch.object(archiver, "_archive_source", return_value=0) as mock_arch:
            archiver.archive_once(session)

        assert mock_arch.call_count == 3

    def test_archive_once_commits_per_source(self):
        """archive_once must commit once per successfully processed source."""
        from app.services import archiver

        source_rows = [
            self._build_source_row("s1", 30, "keep"),
            self._build_source_row("s2", 7, "drop"),
            self._build_source_row("s3", 14, "move-to-cold"),
        ]
        session = _make_session(source_rows=source_rows)

        with patch.object(archiver, "_archive_source", return_value=0):
            archiver.archive_once(session)

        assert session.commit.call_count == 3

    def test_archive_once_one_source_failure_does_not_halt_iteration(self):
        """A failure in one source must not stop the archiver; rollback is called once."""
        from app.services import archiver

        source_rows = [
            self._build_source_row("s1", 30, "drop"),
            self._build_source_row("s2", 7, "drop"),
            self._build_source_row("s3", 14, "drop"),
        ]
        session = _make_session(source_rows=source_rows)

        call_count = 0

        def _side_effect(sess, sid, days, policy):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("simulated source failure")
            return 5

        with patch.object(archiver, "_archive_source", side_effect=_side_effect):
            totals = archiver.archive_once(session)

        # All 3 sources attempted (call_count == 3)
        assert call_count == 3
        # rollback called once (for the failing source)
        assert session.rollback.call_count == 1
        # The 2 successful sources contributed 5+5=10 to drop
        assert totals["drop"] == 10

    def test_archive_once_returns_totals_dict_with_all_keys(self):
        """archive_once must always return a dict with keep, drop, and move-to-cold keys."""
        from app.services import archiver

        source_rows = []
        session = _make_session(source_rows=source_rows)

        totals = archiver.archive_once(session)

        assert "keep" in totals
        assert "drop" in totals
        assert "move-to-cold" in totals

    def test_archive_once_sums_rows_per_policy(self):
        """Two 'drop' sources returning 5 and 3 should sum to totals['drop'] == 8."""
        from app.services import archiver

        source_rows = [
            self._build_source_row("s1", 7, "drop"),
            self._build_source_row("s2", 7, "drop"),
        ]
        session = _make_session(source_rows=source_rows)

        rowcounts = iter([5, 3])

        def _side_effect(sess, sid, days, policy):
            return next(rowcounts)

        with patch.object(archiver, "_archive_source", side_effect=_side_effect):
            totals = archiver.archive_once(session)

        assert totals["drop"] == 8

    def test_archive_once_keep_counts_zero(self):
        """keep policy sources contribute 0 to keep totals (no SQL rows affected)."""
        from app.services import archiver

        source_rows = [
            self._build_source_row("s1", 30, "keep"),
            self._build_source_row("s2", 30, "keep"),
        ]
        session = _make_session(source_rows=source_rows)

        with patch.object(archiver, "_archive_source", return_value=0):
            totals = archiver.archive_once(session)

        assert totals["keep"] == 0

    def test_archive_once_mixed_policy_totals(self):
        """Mixed policies accumulate totals independently."""
        from app.services import archiver

        source_rows = [
            self._build_source_row("s1", 7, "drop"),
            self._build_source_row("s2", 14, "move-to-cold"),
            self._build_source_row("s3", 7, "drop"),
            self._build_source_row("s4", 30, "keep"),
        ]
        session = _make_session(source_rows=source_rows)

        # Returns per policy: drop=10, move-to-cold=5, keep=0
        policy_returns = {"s1": 10, "s2": 5, "s3": 0, "s4": 0}

        def _side_effect(sess, sid, days, policy):
            return policy_returns[sid]

        with patch.object(archiver, "_archive_source", side_effect=_side_effect):
            totals = archiver.archive_once(session)

        assert totals["drop"] == 10   # s1(10) + s3(0)
        assert totals["move-to-cold"] == 5
        assert totals["keep"] == 0

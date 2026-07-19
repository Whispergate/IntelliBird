"""Unit tests for bbot_runner orphan reaper functions (EASM-10).

Covers:
- reap_orphan_containers: subprocess interaction, label filter, noops when empty
- reap_orphan_scans: async UPDATE logic for stale running scans
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

# pydantic-settings singleton loaded at first app.* import - set required env vars before that
os.environ.setdefault("SECRET_KEY", "a" * 32)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SIGNING_KEY", "b" * 32)


# ---------------------------------------------------------------------------
# reap_orphan_containers tests
# ---------------------------------------------------------------------------


def test_reap_containers_calls_ps_with_intellibird_easm_label():
    """docker ps -a must be called with --filter label=intellibird.easm=true."""
    with patch("subprocess.run") as mock_run:
        # docker ps returns empty (no containers found)
        ps_result = MagicMock()
        ps_result.stdout = ""
        ps_result.returncode = 0
        mock_run.return_value = ps_result

        from app.services.bbot_runner import reap_orphan_containers
        reap_orphan_containers()

        # Verify ps call was made with the correct label filter
        assert mock_run.called
        ps_call_args = mock_run.call_args_list[0][0][0]  # first positional arg to first call
        assert "docker" in ps_call_args
        assert "ps" in ps_call_args
        assert "-a" in ps_call_args
        # Check label filter present (may be in --filter label=... form)
        args_str = " ".join(ps_call_args)
        assert "intellibird.easm" in args_str


def test_reap_containers_calls_rm_when_ids_present():
    """docker rm must be called with all container IDs when ps finds exited containers."""
    with patch("subprocess.run") as mock_run:
        ps_result = MagicMock()
        ps_result.stdout = "abc123\nxyz789\n"
        ps_result.returncode = 0

        rm_result = MagicMock()
        rm_result.returncode = 0

        mock_run.side_effect = [ps_result, rm_result]

        from app.services.bbot_runner import reap_orphan_containers
        removed = reap_orphan_containers()

        assert removed == ["abc123", "xyz789"]
        assert mock_run.call_count == 2  # ps + rm
        rm_call_args = mock_run.call_args_list[1][0][0]
        assert "rm" in rm_call_args
        assert "abc123" in rm_call_args
        assert "xyz789" in rm_call_args


def test_reap_containers_noops_when_none():
    """docker rm must NOT be called when ps returns no container IDs."""
    with patch("subprocess.run") as mock_run:
        ps_result = MagicMock()
        ps_result.stdout = ""
        ps_result.returncode = 0
        mock_run.return_value = ps_result

        from app.services.bbot_runner import reap_orphan_containers
        removed = reap_orphan_containers()

        assert removed == []
        assert mock_run.call_count == 1  # only ps, no rm


def test_reap_containers_noops_when_whitespace_only():
    """docker rm must NOT be called when ps returns only whitespace."""
    with patch("subprocess.run") as mock_run:
        ps_result = MagicMock()
        ps_result.stdout = "   \n  \n"
        ps_result.returncode = 0
        mock_run.return_value = ps_result

        from app.services.bbot_runner import reap_orphan_containers
        removed = reap_orphan_containers()

        assert removed == []
        assert mock_run.call_count == 1


# ---------------------------------------------------------------------------
# reap_orphan_scans tests (async, no live DB)
# ---------------------------------------------------------------------------


import pytest  # noqa: E402


@pytest.mark.asyncio
async def test_reap_scans_updates_stale_running():
    """reap_orphan_scans executes an UPDATE targeting status='running' + started_at < threshold."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = 2
    mock_db.execute.return_value = mock_result

    from app.services.bbot_runner import reap_orphan_scans
    count = await reap_orphan_scans(mock_db)

    assert count == 2
    assert mock_db.execute.called
    assert mock_db.commit.called

    # Validate the SQL text contains required clauses
    executed_stmt = mock_db.execute.call_args[0][0]
    sql_text = str(executed_stmt)
    assert "UPDATE easm_scans" in sql_text
    assert "status='orphaned'" in sql_text or "status='running'" in sql_text
    # The WHERE clause must filter on status and started_at
    assert "started_at" in sql_text


@pytest.mark.asyncio
async def test_reap_scans_returns_zero_when_no_rows():
    """reap_orphan_scans returns 0 when rowcount is None (no stale scans)."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = None
    mock_db.execute.return_value = mock_result

    from app.services.bbot_runner import reap_orphan_scans
    count = await reap_orphan_scans(mock_db)

    assert count == 0

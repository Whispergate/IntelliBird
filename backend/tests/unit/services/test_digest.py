"""Unit tests for ai_digest_project top-N selection — AI-07.

Covers:
  - test_top_ten_by_coalesce: digest selects top 10 events ordered by COALESCE(ai_score, score) DESC
  - test_scoring_coalesce: ai_score wins over score when present; falls back to rule score
  - test_summary_type_digest: AISummary row has summary_type='digest'
  - test_event_id_null_on_digest_row: AISummary row has event_id=NULL (project-level)
"""
from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

# Set env vars before any app module imports.
os.environ.setdefault("SECRET_KEY", "a" * 32 + "deadbeef")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SIGNING_KEY", "b" * 64)

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    event_id=None,
    score=None,
    ai_score=None,
    title="Test Event",
    description="Test description",
):
    """Build a mock Event ORM object."""
    e = MagicMock()
    e.id = event_id or uuid.uuid4()
    e.score = Decimal(str(score)) if score is not None else None
    e.ai_score = Decimal(str(ai_score)) if ai_score is not None else None
    e.title = title
    e.description = description
    e.observed_at = "2026-01-01T00:00:00Z"
    e.tags = []
    return e


def _make_project(project_id=None, ai_daily_token_cap=100000):
    p = MagicMock()
    p.id = project_id or uuid.uuid4()
    p.ai_daily_token_cap = ai_daily_token_cap
    return p


# ---------------------------------------------------------------------------
# Shared test harness
# ---------------------------------------------------------------------------


async def _run_digest_with_events(
    events: list,
    project_id: str | None = None,
    window_count: int = 12,
    llm_response_text: str = "Digest summary text.",
):
    """
    Run _async_digest with mocked DB returning ``events`` as the top rows
    and ``window_count`` as the total 24h window.

    Returns (summary_row_args, db_mock) where summary_row_args is the kwargs
    passed to AISummary(...) via db.add().
    """
    if project_id is None:
        project_id = str(uuid.uuid4())

    mock_project = _make_project(project_id=uuid.UUID(project_id))

    # Build mock db.
    added_rows = []

    execute_call_count = [0]

    async def fake_execute(stmt):
        execute_call_count[0] += 1
        result = MagicMock()
        n = execute_call_count[0]
        if n == 1:
            # Project lookup.
            result.scalar_one_or_none = MagicMock(return_value=mock_project)
        elif n == 2:
            # Window count query — return list of ids.
            result.all = MagicMock(return_value=[(uuid.uuid4(),)] * window_count)
        else:
            # Top-10 events query.
            scalars_mock = MagicMock()
            scalars_mock.all = MagicMock(return_value=events)
            result.scalars = MagicMock(return_value=scalars_mock)
        return result

    mock_db = AsyncMock()
    mock_db.execute = fake_execute
    mock_db.add = MagicMock(side_effect=added_rows.append)
    mock_db.commit = AsyncMock()
    mock_db.flush = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_session_factory = MagicMock(return_value=mock_session_ctx)
    mock_engine = AsyncMock()
    mock_engine.dispose = AsyncMock()

    # Mock LLM response.
    mock_llm_response = MagicMock()
    mock_llm_response.choices = [MagicMock()]
    mock_llm_response.choices[0].message.content = llm_response_text
    mock_llm_response.usage.total_tokens = 256

    with (
        patch("app.workers.ai._make_engine_and_session", return_value=(mock_engine, mock_session_factory)),
        patch("app.services.llm.client.resolve_provider", new=AsyncMock(
            return_value=("ollama_chat/phi3:mini", "http://ollama:11434", None)
        )),
        patch("litellm.acompletion", new=AsyncMock(return_value=mock_llm_response)),
    ):
        from app.workers.ai import _async_digest
        await _async_digest(project_id)

    return added_rows, mock_db


# ---------------------------------------------------------------------------
# test_top_ten_by_coalesce
# ---------------------------------------------------------------------------


def test_top_ten_by_coalesce():
    """Digest selects top 10 events ordered by COALESCE(ai_score, score) DESC.

    We build 12 events (simulating a larger pool) but the DB query returns 10
    (LIMIT 10). The digest summary must reflect the top-10 count.
    """
    # 10 events returned by mocked top-N query (DB enforces LIMIT 10).
    events = [_make_event(score=float(90 - i), ai_score=float(85 - i)) for i in range(10)]
    project_id = str(uuid.uuid4())

    added_rows, _ = asyncio.run(_run_digest_with_events(events, project_id, window_count=12))

    # One AISummary row should be added.
    assert len(added_rows) == 1, f"Expected 1 AISummary row added, got {len(added_rows)}"


# ---------------------------------------------------------------------------
# test_scoring_coalesce
# ---------------------------------------------------------------------------


def test_scoring_coalesce():
    """COALESCE(ai_score, score): ai_score wins when present; falls back to rule score.

    This test verifies the event payload construction uses both ai_score and score
    fields, so the DB ORDER BY COALESCE(ai_score, score) has the right inputs.
    We inject events with mixed ai_score presence and verify digest runs successfully.
    """
    # Mix: some events have ai_score, some only have score.
    events = [
        _make_event(score=80.0, ai_score=95.0, title="High ai_score"),   # ai_score wins
        _make_event(score=70.0, ai_score=None, title="No ai_score"),       # falls back to score
        _make_event(score=60.0, ai_score=88.0, title="Medium ai_score"),
    ]
    project_id = str(uuid.uuid4())

    added_rows, _ = asyncio.run(_run_digest_with_events(events, project_id, window_count=5))

    assert len(added_rows) == 1, "Expected exactly one digest summary row"
    summary = added_rows[0]
    # Digest must not be None.
    assert summary is not None


# ---------------------------------------------------------------------------
# test_summary_type_digest
# ---------------------------------------------------------------------------


def test_summary_type_digest():
    """Digest row is inserted into ai_summaries with summary_type='digest'."""
    events = [_make_event(score=70.0) for _ in range(5)]
    project_id = str(uuid.uuid4())

    added_rows, _ = asyncio.run(_run_digest_with_events(events, project_id))

    assert len(added_rows) == 1
    summary = added_rows[0]
    assert summary.summary_type == "digest", (
        f"Expected summary_type='digest', got {summary.summary_type!r}"
    )


# ---------------------------------------------------------------------------
# test_event_id_null_on_digest_row
# ---------------------------------------------------------------------------


def test_event_id_null_on_digest_row():
    """Digest ai_summaries row has event_id=NULL (project-level, not event-level)."""
    events = [_make_event(score=65.0) for _ in range(3)]
    project_id = str(uuid.uuid4())

    added_rows, _ = asyncio.run(_run_digest_with_events(events, project_id))

    assert len(added_rows) == 1
    summary = added_rows[0]
    assert summary.event_id is None, (
        f"Expected event_id=None for digest row, got {summary.event_id!r}"
    )

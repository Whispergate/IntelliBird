"""Integration tests for AI-02 ai_summaries - soft-FK contract and project scoping.

Covers:
  - ai_summaries.event_id is a soft FK: NULL event_id does not cause a constraint failure.
  - summary_type='event' insert with a UUID event_id that does not exist in events.
  - summary_type='digest' insert with event_id=NULL (digest record pattern).
  - PROD-01 extension: ai_summaries rows are project-scoped - no cross-project leakage.

AI-01, AI-02: task 1 (migration) and task 3 (PROD-01 extension).
"""
from __future__ import annotations

import os
import uuid

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


async def _make_project(db_session) -> uuid.UUID:
    """Insert a minimal project row and return its id."""
    project_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO projects (id, name, engagement_type, created_by) "
            "VALUES (:id, :name, 'intel_only', 'test')"
        ),
        {"id": project_id, "name": f"test-project-{project_id}"},
    )
    await db_session.commit()
    return project_id


async def _insert_summary(db_session, project_id: uuid.UUID, event_id=None, summary_type="event") -> uuid.UUID:
    """Insert an ai_summaries row and return its id."""
    summary_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO ai_summaries "
            "(id, project_id, event_id, summary_type, provider_used, model_used, "
            "prompt_template_version, summary_text) "
            "VALUES (:id, :pid, :eid, :stype, 'ollama', 'phi3:mini', 'EVENT_SUMMARY_PROMPT_V1', 'Test summary.')"
        ),
        {
            "id": summary_id,
            "pid": project_id,
            "eid": event_id,
            "stype": summary_type,
        },
    )
    return summary_id


# ---------------------------------------------------------------------------
# Soft FK tests (stub replacements from Wave 0)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_id_soft_fk_no_constraint_failure(db_session) -> None:
    """ai_summaries.event_id is a soft FK - NULL does not cause constraint failure.

    Inserts a summary row with event_id=NULL (digest pattern). Must NOT raise a
    FK constraint error since events is a hypertable and cannot be a FK target.
    """
    project_id = await _make_project(db_session)
    summary_id = await _insert_summary(db_session, project_id, event_id=None, summary_type="digest")
    await db_session.commit()

    result = await db_session.execute(
        text("SELECT event_id, summary_type FROM ai_summaries WHERE id = :id"),
        {"id": summary_id},
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] is None, "event_id should be NULL for digest summary"
    assert row[1] == "digest"


@pytest.mark.asyncio
async def test_summary_type_event_insert(db_session) -> None:
    """Insert ai_summaries row with summary_type='event' and a phantom event_id UUID.

    The insert must succeed with no FK constraint error - events is a hypertable,
    so event_id is a soft UUID column only.
    """
    project_id = await _make_project(db_session)
    phantom_event_id = uuid.uuid4()  # does not exist in events table
    summary_id = await _insert_summary(
        db_session, project_id, event_id=phantom_event_id, summary_type="event"
    )
    await db_session.commit()

    result = await db_session.execute(
        text("SELECT event_id, summary_type FROM ai_summaries WHERE id = :id"),
        {"id": summary_id},
    )
    row = result.fetchone()
    assert row is not None
    assert str(row[0]) == str(phantom_event_id), (
        f"event_id mismatch: expected {phantom_event_id}, got {row[0]}"
    )
    assert row[1] == "event"


@pytest.mark.asyncio
async def test_summary_type_digest_insert(db_session) -> None:
    """Insert ai_summaries row with summary_type='digest' and event_id=NULL.

    Digest summaries synthesise multiple events into one summary; they never
    reference a single event_id.
    """
    project_id = await _make_project(db_session)
    summary_id = await _insert_summary(db_session, project_id, event_id=None, summary_type="digest")
    await db_session.commit()

    result = await db_session.execute(
        text("SELECT event_id, summary_type, requires_analyst_review FROM ai_summaries WHERE id = :id"),
        {"id": summary_id},
    )
    row = result.fetchone()
    assert row is not None
    event_id, summary_type, requires_review = row
    assert event_id is None, "digest summary must have NULL event_id"
    assert summary_type == "digest"
    # requires_analyst_review defaults to TRUE; digest rows set it false in service layer
    # but here we only test schema default (true)
    assert requires_review is True, "requires_analyst_review should default to true from schema"


# ---------------------------------------------------------------------------
# PROD-01 extension: ai_summaries project scoping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prod01_leakage_extension_ai_summaries(db_session) -> None:
    """PROD-01 extension: ai_summaries rows are project-scoped - no cross-project leakage.

    Seeds 3 summaries under Project A and 3 under Project B (disjoint). Queries
    ai_summaries WHERE project_id = A and asserts only A rows are returned.
    Then queries WHERE project_id = B and asserts only B rows are returned.
    The two ID sets must be disjoint.
    """
    project_a = await _make_project(db_session)
    project_b = await _make_project(db_session)

    # Seed 3 summaries under Project A
    a_ids = set()
    for _ in range(3):
        sid = await _insert_summary(db_session, project_a, event_id=uuid.uuid4(), summary_type="event")
        a_ids.add(str(sid))
    await db_session.commit()

    # Seed 3 summaries under Project B
    b_ids = set()
    for _ in range(3):
        sid = await _insert_summary(db_session, project_b, event_id=uuid.uuid4(), summary_type="event")
        b_ids.add(str(sid))
    await db_session.commit()

    # Query A-scoped summaries
    result_a = await db_session.execute(
        text("SELECT id FROM ai_summaries WHERE project_id = :pid"),
        {"pid": project_a},
    )
    returned_a = {str(r[0]) for r in result_a.fetchall()}

    # Query B-scoped summaries
    result_b = await db_session.execute(
        text("SELECT id FROM ai_summaries WHERE project_id = :pid"),
        {"pid": project_b},
    )
    returned_b = {str(r[0]) for r in result_b.fetchall()}

    # Project A query must contain exactly A's summaries
    assert a_ids.issubset(returned_a), (
        f"LEAK: Some Project A summary IDs missing from A-scoped query. "
        f"Expected {a_ids}, got {returned_a}"
    )
    # Project B IDs must NOT appear in Project A query results
    assert not (returned_a & b_ids), (
        f"LEAK: Project B summary IDs appeared in Project A scoped query: "
        f"{returned_a & b_ids}"
    )
    # Project B query must contain exactly B's summaries
    assert b_ids.issubset(returned_b), (
        f"LEAK: Some Project B summary IDs missing from B-scoped query. "
        f"Expected {b_ids}, got {returned_b}"
    )
    # Project A IDs must NOT appear in Project B query results
    assert not (returned_b & a_ids), (
        f"LEAK: Project A summary IDs appeared in Project B scoped query: "
        f"{returned_b & a_ids}"
    )
    # Sanity: two result sets are disjoint
    assert not (returned_a & returned_b), (
        f"LEAK: ai_summaries result sets for Project A and B overlap: "
        f"{returned_a & returned_b}"
    )

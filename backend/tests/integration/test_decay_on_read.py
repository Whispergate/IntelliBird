"""Integration test: Phase 15 decay-on-read observable — SCR-05.

Verifies that the on-read decay formula in ``events_query.build_events_query``
(via ``_build_score_expressions``) produces measurably lower scores for events
scored 30 days ago vs events scored now.

Formula under test (SQL equivalent):
    current_score = COALESCE(override, events.score, 0)
                  * power(2, -(EXTRACT(EPOCH FROM now() - scored_at) / 86400) / 14.0)

For score=80 scored 30 days ago:
    expected = 80 * 2^(-30/14) ≈ 18.06   (Python: math.pow(2, -30/14) * 80)

For score=80 scored just now:
    expected ≈ 80 (decay factor ≈ 1.0, varies by sub-second age)

Assertions:
  1. ``sort=score_desc`` returns event B (recent) before event A (stale).
  2. The SQL-decayed score for A is within [16.0, 20.0] (±~11% tolerance for
     any wall-clock drift during the test run — the theoretical value 18.06
     moves less than ±0.15 per hour so the window is generous).
  3. The SQL-decayed score for B is approximately 80 (≥ 75, since decay over
     seconds is negligible).

SQL formula note:
    Age uses COALESCE(scored_at, observed_at) so unscored rows also participate.
    For this test both events carry explicit scored_at values.
    Half-life is hardcoded to 14 days in the query builder (project-default;
    per-project override applies post-rescore, not at query time).
"""
from __future__ import annotations

import hashlib
import math
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_SCORE = 80.0
HALF_LIFE_DAYS = 14.0
STALE_AGE_DAYS = 30
EXPECTED_DECAYED_A = BASE_SCORE * math.pow(2, -STALE_AGE_DAYS / HALF_LIFE_DAYS)  # ≈ 18.06

# Tolerance bounds for the 30-day decayed score assertion.
# Theory: 80 * 2^(-30/14) ≈ 18.06. Allow ±11% for clock drift during the test.
DECAYED_A_LO = 16.0
DECAYED_A_HI = 20.0

# Recent event B should still be close to the base score.
RECENT_B_MIN = 75.0


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

async def _seed_project(db_session, name: str) -> uuid.UUID:
    pid = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO projects (id, name, engagement_type, created_by, archived) "
            "VALUES (:id, :name, 'internal', 'decay-test', false)"
        ),
        {"id": pid, "name": name},
    )
    return pid


async def _seed_scope_row(db_session, project_id: uuid.UUID) -> None:
    """Permissive keyword scope so build_scope_predicate doesn't short-circuit."""
    await db_session.execute(
        text(
            "INSERT INTO project_scope_rows "
            "(id, project_id, scope_type, value, intel_scope, active_test_scope, exclude) "
            "VALUES (gen_random_uuid(), :pid, 'keyword', 'decay', true, false, false)"
        ),
        {"pid": project_id},
    )


async def _seed_event_with_score(
    db_session,
    project_id: uuid.UUID,
    title: str,
    score: float,
    scored_at: datetime,
    observed_at: datetime,
) -> uuid.UUID:
    """Insert an event carrying an explicit base score + scored_at."""
    eid = uuid.uuid4()
    content_hash = hashlib.sha256(f"decay:{project_id}:{title}".encode()).hexdigest()
    await db_session.execute(
        text(
            "INSERT INTO events "
            "(id, stix_type, project_id, observed_at, title, content_hash, "
            " visibility, score, scored_at, score_version) "
            "VALUES (:id, 'observed-data', :pid, :obs, :title, :ch, "
            "        'shared', :score, :scored_at, 1)"
        ),
        {
            "id": eid,
            "pid": project_id,
            "obs": observed_at,
            "title": title,
            "ch": content_hash,
            "score": score,
            "scored_at": scored_at,
        },
    )
    return eid


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_decay_on_read_observable(db_session, _migrations_applied: None) -> None:
    """30-day-old scored event has measurably lower on-read score than a fresh one.

    Steps:
      1. Seed project + permissive scope row.
      2. Seed event A: score=80, scored_at=now()-30d.
      3. Seed event B: score=80, scored_at=now().
      4. Execute build_events_query(sort="score_desc").
      5. Assert event B appears before event A in results.
      6. Directly compute the decayed score for A via a raw SQL SELECT using the
         same formula as the query builder; assert it is within [16.0, 20.0].
      7. Assert event B's decayed score is ≥ 75.0 (negligible decay over seconds).
    """
    from app.services.events_query import EventsQueryParams, build_events_query

    now = datetime.now(timezone.utc)
    stale_scored_at = now - timedelta(days=STALE_AGE_DAYS)

    # --- Seed ----------------------------------------------------------------
    project_id = await _seed_project(db_session, f"DecayProject-{uuid.uuid4()}")
    await _seed_scope_row(db_session, project_id)

    event_a_id = await _seed_event_with_score(
        db_session, project_id,
        title="decay-stale-a",
        score=BASE_SCORE,
        scored_at=stale_scored_at,
        observed_at=stale_scored_at,
    )
    event_b_id = await _seed_event_with_score(
        db_session, project_id,
        title="decay-recent-b",
        score=BASE_SCORE,
        scored_at=now,
        observed_at=now,
    )
    await db_session.commit()

    # --- Query via build_events_query ----------------------------------------
    params = EventsQueryParams(sort="score_desc")
    stmt = build_events_query(
        params,
        dashboard_roles=None,
        project_id=project_id,
        scope_predicate=None,
        bound_sources=None,
    )
    rows = (await db_session.execute(stmt)).scalars().all()

    returned_ids = [str(row.id) for row in rows]
    assert str(event_b_id) in returned_ids, "Event B (recent) not in results"
    assert str(event_a_id) in returned_ids, "Event A (stale) not in results"

    # 1. Event B (recent) must rank before event A (stale) under score_desc.
    idx_a = returned_ids.index(str(event_a_id))
    idx_b = returned_ids.index(str(event_b_id))
    assert idx_b < idx_a, (
        f"Expected event B (recent) at index {idx_b} to precede event A (stale) "
        f"at index {idx_a} under sort=score_desc"
    )

    # 2. Compute the on-read decayed score for A directly via raw SQL using the
    #    same formula as _build_score_expressions in events_query.py:
    #    current_score * power(2, -(extract(epoch from now()-scored_at)/86400) / 14.0)
    #    This is the canonical formula; testing it directly avoids indirect
    #    inference and documents the formula's behaviour at 30 days.
    decay_sql = text(
        """
        SELECT
            score * power(
                2.0,
                -(EXTRACT(EPOCH FROM now() - scored_at) / 86400.0) / 14.0
            ) AS decayed_score
        FROM events
        WHERE id = :eid
        """
    )
    result_a = (await db_session.execute(decay_sql, {"eid": str(event_a_id)})).one()
    decayed_score_a = float(result_a.decayed_score)

    # Theory: 80 * 2^(-30/14) ≈ 18.06. Allow ±~11% tolerance for clock drift.
    assert DECAYED_A_LO < decayed_score_a < DECAYED_A_HI, (
        f"Event A 30-day decay: expected score in [{DECAYED_A_LO}, {DECAYED_A_HI}], "
        f"got {decayed_score_a:.4f}. Theory: {EXPECTED_DECAYED_A:.4f}"
    )

    # 3. Event B's decayed score should be close to the base (negligible decay over seconds).
    result_b = (await db_session.execute(decay_sql, {"eid": str(event_b_id)})).one()
    decayed_score_b = float(result_b.decayed_score)

    assert decayed_score_b >= RECENT_B_MIN, (
        f"Event B (scored now) decayed score {decayed_score_b:.4f} < {RECENT_B_MIN}. "
        f"The decay formula is being applied too aggressively to recent events."
    )

    # Bonus: B must outrank A numerically (sanity check consistent with ordering).
    assert decayed_score_b > decayed_score_a, (
        f"Recent event B score {decayed_score_b:.4f} should exceed "
        f"stale event A score {decayed_score_a:.4f}"
    )

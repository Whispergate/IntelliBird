"""— dismiss expiry sweep integration tests (BRP-04).

Covers the must-have truth: `brand_dismiss_expiry_sweep` flips
lifecycle_status='dismissed' → 'new' + clears dismiss_until on expired rows,
while leaving active dismissals (dismiss_until in the future) + NULL
dismiss_until rows untouched.
"""
from __future__ import annotations

import os

os.environ.setdefault("SECRET_KEY", "a" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "b" * 64)

import asyncio
import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_dismiss_expiry_sweep_reactivates_expired_only(db_session):
    """Seed one project + one term + four matches covering each state:
      A. dismissed, dismiss_until = NOW() - 1h   → reactivated to 'new'
      B. dismissed, dismiss_until = NOW() + 1d   → kept 'dismissed'
      C. dismissed, dismiss_until = NULL         → kept 'dismissed' (permanent)
      D. 'confirmed',  dismiss_until = NOW() - 1h → kept 'confirmed' (not dismissed)
    """
    from app.scheduler import jobs as jobs_mod

    pid = uuid.uuid4()
    tid = uuid.uuid4()

    await db_session.execute(
        text(
            """
            INSERT INTO projects (id, name, engagement_type, created_by, archived)
            VALUES (:id, 'suppress-test', 'internal', 'tester', false)
            """
        ),
        {"id": str(pid)},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO brand_terms
                (id, project_id, term_type, value, mode, archived, high_noise_risk)
            VALUES
                (:tid, :pid, 'keyword', 'examplecorp', 'active', false, false)
            """
        ),
        {"tid": str(tid), "pid": str(pid)},
    )

    mid_a = uuid.uuid4()  # expired dismissal → should reactivate
    mid_b = uuid.uuid4()  # future dismissal → keep
    mid_c = uuid.uuid4()  # permanent dismissal (NULL) → keep
    mid_d = uuid.uuid4()  # confirmed with stale dismiss_until → keep confirmed

    await db_session.execute(
        text(
            """
            INSERT INTO brand_matches
                (id, project_id, brand_term_id, matched_value, match_source,
                 severity, first_seen, last_seen, lifecycle_status, dismiss_until)
            VALUES
                (:a, :pid, :tid, 'hit-a', 'fts', 'low',
                 NOW() - INTERVAL '2 days', NOW() - INTERVAL '2 days',
                 'dismissed', NOW() - INTERVAL '1 hour'),
                (:b, :pid, :tid, 'hit-b', 'fts', 'low',
                 NOW() - INTERVAL '2 days', NOW() - INTERVAL '2 days',
                 'dismissed', NOW() + INTERVAL '1 day'),
                (:c, :pid, :tid, 'hit-c', 'fts', 'low',
                 NOW() - INTERVAL '2 days', NOW() - INTERVAL '2 days',
                 'dismissed', NULL),
                (:d, :pid, :tid, 'hit-d', 'fts', 'low',
                 NOW() - INTERVAL '2 days', NOW() - INTERVAL '2 days',
                 'confirmed', NOW() - INTERVAL '1 hour')
            """
        ),
        {
            "a": str(mid_a),
            "b": str(mid_b),
            "c": str(mid_c),
            "d": str(mid_d),
            "pid": str(pid),
            "tid": str(tid),
        },
    )
    await db_session.commit()

    await asyncio.to_thread(jobs_mod.brand_dismiss_expiry_sweep_job)

    res = await db_session.execute(
        text(
            "SELECT id, lifecycle_status, dismiss_until FROM brand_matches "
            "WHERE id IN (:a, :b, :c, :d)"
        ),
        {"a": str(mid_a), "b": str(mid_b), "c": str(mid_c), "d": str(mid_d)},
    )
    rows = {row[0]: (row[1], row[2]) for row in res.all()}

    # A — reactivated + dismiss_until cleared
    status_a, until_a = rows[mid_a]
    assert status_a == "new", f"expired dismissal must flip to 'new', got {status_a!r}"
    assert until_a is None, "dismiss_until must be cleared when reactivating"

    # B — still dismissed, dismiss_until untouched (future timestamp)
    status_b, until_b = rows[mid_b]
    assert status_b == "dismissed", "future-dated dismissal must be left alone"
    assert until_b is not None

    # C — permanent dismissal (NULL dismiss_until) must survive
    status_c, until_c = rows[mid_c]
    assert status_c == "dismissed", "NULL dismiss_until = permanent, must not reactivate"
    assert until_c is None

    # D — confirmed with stale dismiss_until column: sweep filters by
    # lifecycle_status='dismissed' so this must NOT change.
    status_d, _until_d = rows[mid_d]
    assert status_d == "confirmed", (
        "sweep must not touch non-dismissed rows (filter is lifecycle_status='dismissed')"
    )


@pytest.mark.asyncio
async def test_dismiss_expiry_sweep_idempotent(db_session):
    """Running the sweep twice against the same expired row must not error +
    the second run has no additional effect."""
    from app.scheduler import jobs as jobs_mod

    pid = uuid.uuid4()
    tid = uuid.uuid4()
    mid = uuid.uuid4()

    await db_session.execute(
        text(
            """
            INSERT INTO projects (id, name, engagement_type, created_by, archived)
            VALUES (:id, 'suppress-idem', 'internal', 'tester', false)
            """
        ),
        {"id": str(pid)},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO brand_terms
                (id, project_id, term_type, value, mode, archived, high_noise_risk)
            VALUES
                (:tid, :pid, 'keyword', 'idem', 'active', false, false)
            """
        ),
        {"tid": str(tid), "pid": str(pid)},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO brand_matches
                (id, project_id, brand_term_id, matched_value, match_source,
                 severity, first_seen, last_seen, lifecycle_status, dismiss_until)
            VALUES
                (:m, :pid, :tid, 'idem-hit', 'fts', 'low',
                 NOW() - INTERVAL '2 days', NOW() - INTERVAL '2 days',
                 'dismissed', NOW() - INTERVAL '2 hours')
            """
        ),
        {"m": str(mid), "pid": str(pid), "tid": str(tid)},
    )
    await db_session.commit()

    # First sweep — reactivates
    await asyncio.to_thread(jobs_mod.brand_dismiss_expiry_sweep_job)
    # Second sweep — no-op, must not raise
    await asyncio.to_thread(jobs_mod.brand_dismiss_expiry_sweep_job)

    res = await db_session.execute(
        text("SELECT lifecycle_status, dismiss_until FROM brand_matches WHERE id=:m"),
        {"m": str(mid)},
    )
    status, until = res.one()
    assert status == "new"
    assert until is None

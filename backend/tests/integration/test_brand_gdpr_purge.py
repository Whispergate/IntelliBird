"""- GDPR purge sweep integration tests (BRP-04 / L-3).

Covers the must-have truth: `brand_gdpr_purge` DELETEs person-type brand_matches
older than projects.gdpr_person_match_retention_days and leaves non-person
matches + recent person matches intact.
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
async def test_gdpr_purge_deletes_stale_person_matches_only(db_session):
    """Seed one project with retention=30 days. Insert four brand_matches:
      A. person + 100 days old   → DELETED
      B. person + 5 days old     → kept
      C. keyword + 100 days old  → kept (not person-type term)
      D. person + 100 days old (retention=365 project) → kept

    Assert only (A) is gone.
    """
    from app.scheduler import jobs as jobs_mod

    # Project with 30-day retention
    pid_short = uuid.uuid4()
    await db_session.execute(
        text(
            """
            INSERT INTO projects (id, name, engagement_type, created_by, archived,
                                  gdpr_person_match_retention_days)
            VALUES (:id, 'retention-30', 'internal', 'tester', false, 30)
            """
        ),
        {"id": str(pid_short)},
    )
    # Project with 365-day retention
    pid_long = uuid.uuid4()
    await db_session.execute(
        text(
            """
            INSERT INTO projects (id, name, engagement_type, created_by, archived,
                                  gdpr_person_match_retention_days)
            VALUES (:id, 'retention-365', 'internal', 'tester', false, 365)
            """
        ),
        {"id": str(pid_long)},
    )

    # Terms
    person_term_short = uuid.uuid4()
    keyword_term = uuid.uuid4()
    person_term_long = uuid.uuid4()
    await db_session.execute(
        text(
            """
            INSERT INTO brand_terms
                (id, project_id, term_type, value, mode, archived, high_noise_risk)
            VALUES
                (:p1, :pid_s, 'person', 'alice', 'active', false, false),
                (:p2, :pid_s, 'keyword', 'acme', 'active', false, false),
                (:p3, :pid_l, 'person', 'bob', 'active', false, false)
            """
        ),
        {
            "p1": str(person_term_short),
            "p2": str(keyword_term),
            "p3": str(person_term_long),
            "pid_s": str(pid_short),
            "pid_l": str(pid_long),
        },
    )

    # Matches
    match_a_stale_person = uuid.uuid4()  # should be deleted
    match_b_recent_person = uuid.uuid4()  # kept
    match_c_stale_keyword = uuid.uuid4()  # kept (keyword term)
    match_d_stale_person_long_retention = uuid.uuid4()  # kept (365-day project)

    await db_session.execute(
        text(
            """
            INSERT INTO brand_matches
                (id, project_id, brand_term_id, matched_value, match_source,
                 severity, first_seen, last_seen, lifecycle_status)
            VALUES
                (:a, :pid_s, :p1, 'alice-100d', 'fts', 'low',
                 NOW() - INTERVAL '100 days', NOW() - INTERVAL '100 days', 'new'),
                (:b, :pid_s, :p1, 'alice-5d',   'fts', 'low',
                 NOW() - INTERVAL '5 days',   NOW() - INTERVAL '5 days',   'new'),
                (:c, :pid_s, :p2, 'acme-100d',  'fts', 'low',
                 NOW() - INTERVAL '100 days', NOW() - INTERVAL '100 days', 'new'),
                (:d, :pid_l, :p3, 'bob-100d',   'fts', 'low',
                 NOW() - INTERVAL '100 days', NOW() - INTERVAL '100 days', 'new')
            """
        ),
        {
            "a": str(match_a_stale_person),
            "b": str(match_b_recent_person),
            "c": str(match_c_stale_keyword),
            "d": str(match_d_stale_person_long_retention),
            "pid_s": str(pid_short),
            "pid_l": str(pid_long),
            "p1": str(person_term_short),
            "p2": str(keyword_term),
            "p3": str(person_term_long),
        },
    )
    await db_session.commit()

    # Run the sync purge in a thread - avoids asyncio ↔ psycopg2 deadlock.
    await asyncio.to_thread(jobs_mod.brand_gdpr_purge_job)

    # Query survivors
    res = await db_session.execute(
        text("SELECT id FROM brand_matches ORDER BY id"),
    )
    surviving_ids = {row[0] for row in res.all()}

    assert match_a_stale_person not in surviving_ids, (
        "stale person match (100d > 30d retention) MUST be purged"
    )
    assert match_b_recent_person in surviving_ids, "recent person match must survive"
    assert match_c_stale_keyword in surviving_ids, (
        "stale keyword-term match must survive (purge is person-type only)"
    )
    assert match_d_stale_person_long_retention in surviving_ids, (
        "stale person match under 365-day retention must survive"
    )


@pytest.mark.asyncio
async def test_gdpr_purge_is_noop_on_empty_dataset(db_session):
    """Sweep on an empty brand_matches table must not raise and must leave the
    table empty. Tests the commit-even-on-zero-rows path."""
    from app.scheduler import jobs as jobs_mod

    # Wipe any residual brand data - db_session fixture TRUNCATEs projects
    # cascading to brand_terms → brand_matches, but be explicit.
    await db_session.execute(text("DELETE FROM brand_matches"))
    await db_session.commit()

    # Must not raise
    await asyncio.to_thread(jobs_mod.brand_gdpr_purge_job)

    res = await db_session.execute(text("SELECT COUNT(*) FROM brand_matches"))
    assert res.scalar_one() == 0

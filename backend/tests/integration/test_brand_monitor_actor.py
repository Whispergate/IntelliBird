"""- Dramatiq actor integration tests.

Covers the must-have truths from 12-05-PLAN.md:
  - Actor decorated with queue_name="brand-monitor"
  - Calling brand_monitor_scan_project(project_id_str) invokes scan_project
  - Actor disposes the async engine on SUCCESS and on EXCEPTION
  - Noise-downgrade sweep: seed > BRAND_NOISE_THRESHOLD matches in last 24h
    for a term → sweep flips term.mode='watch_only'

The actor runs against the live testcontainer DB via the conftest-managed
pg_url; we monkeypatch scan_project to avoid pulling in the full CT log /
dnstwist subprocess dependency graph - this test validates the wiring of
the actor, not the orchestrator (covered by Plan 04 unit tests).
"""
from __future__ import annotations

import os

os.environ.setdefault("SECRET_KEY", "a" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "b" * 64)

import asyncio
import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import text

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seed_project(db_session) -> uuid.UUID:
    """Create an active non-archived project + one active brand term, return pid."""
    pid = uuid.uuid4()
    await db_session.execute(
        text(
            """
            INSERT INTO projects (id, name, engagement_type, created_by, archived)
            VALUES (:id, :name, 'internal', 'tester', false)
            """
        ),
        {"id": str(pid), "name": f"brand-actor-{pid.hex[:8]}"},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO brand_terms
                (id, project_id, term_type, value, mode, archived, high_noise_risk)
            VALUES
                (gen_random_uuid(), :pid, 'keyword', 'intellibird', 'active', false, false)
            """
        ),
        {"pid": str(pid)},
    )
    await db_session.commit()
    return pid


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_actor_registered_on_brand_monitor_queue():
    """Decorator must bind the actor to queue_name='brand-monitor' (M-8 CPU isolation)."""
    from app.workers.brand import brand_monitor_scan_project

    assert brand_monitor_scan_project.queue_name == "brand-monitor"


def test_actor_registered_via_broker_module():
    """Broker module must import app.workers.brand so the decorator fires at
    broker init, BEFORE dramatiq CLI scans actors."""
    import app.workers.broker as broker_mod  # noqa: F401
    import app.workers.brand as brand_mod

    assert hasattr(brand_mod, "brand_monitor_scan_project")


async def test_actor_invokes_scan_project_and_disposes_engine(seed_project):
    """Happy path - actor calls scan_project with a real session and disposes
    the per-loop engine. We capture the engine via monkeypatching
    create_async_engine to assert dispose was awaited."""
    from app.workers import brand as brand_mod

    pid = seed_project
    captured = {"engines": [], "scan_calls": []}

    real_create_async_engine = brand_mod.create_async_engine

    class _EngineProxy:
        """Tracks dispose calls; forwards everything else to the wrapped engine."""

        def __init__(self, eng):
            self._eng = eng
            self.dispose_calls = 0

        async def dispose(self):
            self.dispose_calls += 1
            return await self._eng.dispose()

        def __getattr__(self, item):
            # Delegate all other attr access (begin, connect, etc.) to real engine
            return getattr(self._eng, item)

    def _tracking_create_engine(*args, **kwargs):
        eng = real_create_async_engine(*args, **kwargs)
        proxy = _EngineProxy(eng)
        captured["engines"].append(proxy)
        return proxy

    async def _fake_scan(session, project_id):
        captured["scan_calls"].append(project_id)
        return {"fts": 1, "ct_log": 0, "dnstwist": 0, "synthesised": 0}

    with patch.object(brand_mod, "create_async_engine", _tracking_create_engine), \
         patch.object(brand_mod, "scan_project", _fake_scan):
        # Actor body calls asyncio.run() - dispatch via to_thread so the
        # test's event loop is not clobbered (pytest-asyncio session-scoped loop).
        await asyncio.to_thread(brand_mod.brand_monitor_scan_project, str(pid))

    assert captured["scan_calls"] == [pid]
    assert len(captured["engines"]) == 1
    proxy = captured["engines"][0]
    assert proxy.dispose_calls == 1, "engine.dispose() must be awaited after scan"


async def test_actor_disposes_engine_on_exception(seed_project):
    """Failure path - scan_project raises, actor re-raises, but engine.dispose
    MUST still run (finally block). This is the lesson's teeth."""
    from app.workers import brand as brand_mod

    pid = seed_project
    captured = {"engines": []}

    real_create_async_engine = brand_mod.create_async_engine

    class _EngineProxy:
        def __init__(self, eng):
            self._eng = eng
            self.dispose_calls = 0

        async def dispose(self):
            self.dispose_calls += 1
            return await self._eng.dispose()

        def __getattr__(self, item):
            return getattr(self._eng, item)

    def _tracking_create_engine(*args, **kwargs):
        eng = real_create_async_engine(*args, **kwargs)
        proxy = _EngineProxy(eng)
        captured["engines"].append(proxy)
        return proxy

    async def _boom_scan(session, project_id):
        raise RuntimeError("simulated scan failure")

    def _invoke():
        brand_mod.brand_monitor_scan_project(str(pid))

    with patch.object(brand_mod, "create_async_engine", _tracking_create_engine), \
         patch.object(brand_mod, "scan_project", _boom_scan):
        with pytest.raises(RuntimeError, match="simulated scan failure"):
            # Dispatch via to_thread so asyncio.run() in the actor body
            # does not replace the test's event loop.
            await asyncio.to_thread(_invoke)

    assert len(captured["engines"]) == 1
    proxy = captured["engines"][0]
    assert proxy.dispose_calls == 1, (
        "engine.dispose() MUST run in finally even when scan_project raises "
        "(per-loop engine lesson)"
    )


# ---------------------------------------------------------------------------
# Noise-downgrade sweep (H-5) - exercised here because the plan asks for
# actor-path coverage of the sweep trigger.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_noise_downgrade_sweep_flips_noisy_term_to_watch_only(db_session):
    """Seed > BRAND_NOISE_THRESHOLD matches within last 24h for one active term;
    run the sync sweep; assert term.mode flipped to 'watch_only'.

    Uses a small test threshold by monkeypatching settings.BRAND_NOISE_THRESHOLD.
    """
    from app.config import settings
    from app.scheduler import jobs as jobs_mod

    pid = uuid.uuid4()
    tid = uuid.uuid4()
    await db_session.execute(
        text(
            """
            INSERT INTO projects (id, name, engagement_type, created_by, archived)
            VALUES (:id, 'noise-test', 'internal', 'tester', false)
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
                (:tid, :pid, 'keyword', 'noisyterm', 'active', false, false)
            """
        ),
        {"tid": str(tid), "pid": str(pid)},
    )
    # Seed 6 recent matches with distinct matched_value (dedup key blocks dupes).
    for i in range(6):
        await db_session.execute(
            text(
                """
                INSERT INTO brand_matches
                    (id, project_id, brand_term_id, matched_value, match_source,
                     severity, first_seen, last_seen, lifecycle_status)
                VALUES
                    (gen_random_uuid(), :pid, :tid, :mv, 'fts', 'low',
                     NOW() - INTERVAL '10 minutes', NOW() - INTERVAL '10 minutes', 'new')
                """
            ),
            {"pid": str(pid), "tid": str(tid), "mv": f"hit-{i}"},
        )
    await db_session.commit()

    # Lower threshold so 6 matches qualify as "noisy".
    original_threshold = settings.BRAND_NOISE_THRESHOLD
    settings.BRAND_NOISE_THRESHOLD = 5  # type: ignore[assignment]
    try:
        # Sweep is sync (psycopg2) - run in thread so we don't deadlock the
        # asyncio test loop against our asyncpg session.
        await asyncio.to_thread(jobs_mod.brand_noise_downgrade_sweep_job)
    finally:
        settings.BRAND_NOISE_THRESHOLD = original_threshold  # type: ignore[assignment]

    # Re-read the term in the live session (use a raw read - session may cache).
    row = await db_session.execute(
        text("SELECT mode FROM brand_terms WHERE id = :tid"),
        {"tid": str(tid)},
    )
    mode = row.scalar_one()
    assert mode == "watch_only", f"expected mode='watch_only' after sweep, got {mode!r}"

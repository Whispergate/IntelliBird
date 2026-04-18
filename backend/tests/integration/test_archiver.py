"""Integration tests for the per-source archiver — STO-01, STO-03, STO-04.

Uses testcontainers PostgreSQL (intellibird-db:m1) with alembic upgrade head
to get a real TimescaleDB hypertable. Tests prove the DELETE (drop) and
UPDATE archived=true (move-to-cold) paths affect real rows, and the keep
policy is a no-op.
"""
from __future__ import annotations

import os
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def live_db():
    """Start intellibird-db:m1 container, run alembic upgrade head, yield (engine, env)."""
    with PostgresContainer("intellibird-db:m1") as pg:
        url = pg.get_connection_url()
        parsed_url = make_url(url)
        asyncpg_url = (
            f"postgresql+asyncpg://{parsed_url.username}:{parsed_url.password}"
            f"@{parsed_url.host}:{parsed_url.port}/{parsed_url.database}"
        )
        env = os.environ | {
            "DATABASE_URL": asyncpg_url,
            "SECRET_KEY": "x" * 48,
            "REDIS_URL": "redis://localhost:1",
        }
        r = subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head"],
            cwd=str(BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            pytest.skip(f"alembic failed: {r.stderr[:500]}")
        sync_url = (
            f"postgresql://{parsed_url.username}:{parsed_url.password}"
            f"@{parsed_url.host}:{parsed_url.port}/{parsed_url.database}"
        )
        engine = create_engine(sync_url, future=True)
        yield engine, env
        engine.dispose()


def _insert_source(
    engine,
    *,
    archive_policy: str = "drop",
    hot_retention_days: int = 7,
    enabled: bool = True,
) -> uuid.UUID:
    """Insert a source row and return its UUID."""
    sid = uuid.uuid4()
    with Session(engine) as s:
        s.execute(
            text("""
                INSERT INTO sources (id, name, feed_type, url, poll_interval_sec, enabled,
                                     hot_retention_days, archive_policy)
                VALUES (:id, :name, :ft, :url, :iv, :en, :hrd, :ap)
            """),
            {
                "id": str(sid),
                "name": f"archiver-fixture-{sid}",
                "ft": "rss",
                "url": f"http://fixture/archiver/{sid}",
                "iv": 3600,
                "en": enabled,
                "hrd": hot_retention_days,
                "ap": archive_policy,
            },
        )
        s.commit()
    return sid


def _insert_event(
    engine,
    *,
    source_id: uuid.UUID,
    observed_at: datetime,
    content_hash: str | None = None,
) -> uuid.UUID:
    """Insert an event row and return its UUID."""
    eid = uuid.uuid4()
    if content_hash is None:
        content_hash = str(uuid.uuid4())
    with Session(engine) as s:
        s.execute(
            text("""
                INSERT INTO events (id, source_id, stix_type, observed_at, content_hash)
                VALUES (:id, :sid, 'indicator', :observed_at, :ch)
            """),
            {
                "id": str(eid),
                "sid": str(source_id),
                "observed_at": observed_at,
                "ch": content_hash,
            },
        )
        s.commit()
    return eid


def _apply_env(monkeypatch: pytest.MonkeyPatch, env: dict) -> None:
    """Apply env vars and reload app.config.settings."""
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import importlib
    import app.config as cfg_module
    importlib.reload(cfg_module)
    monkeypatch.setattr("app.config.settings", cfg_module.settings)


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

def test_archiver_drop_policy_deletes_old_events(live_db, monkeypatch):
    """drop policy: events older than hot_retention_days are deleted; recent events remain."""
    engine, env = live_db
    _apply_env(monkeypatch, env)

    source_id = _insert_source(engine, archive_policy="drop", hot_retention_days=7)
    now = datetime.now(timezone.utc)

    old_id_1 = _insert_event(engine, source_id=source_id, observed_at=now - timedelta(days=10))
    old_id_2 = _insert_event(engine, source_id=source_id, observed_at=now - timedelta(days=15))
    recent_id = _insert_event(engine, source_id=source_id, observed_at=now - timedelta(hours=1))

    from app.services.archiver import archive_once

    with Session(engine) as session:
        totals = archive_once(session)

    # Verify 2 rows deleted
    assert totals["drop"] >= 2

    # Confirm DB state
    with Session(engine) as s:
        remaining = s.execute(
            text("SELECT id FROM events WHERE source_id = :sid"),
            {"sid": str(source_id)},
        ).all()
    remaining_ids = {str(r[0]) for r in remaining}
    assert str(recent_id) in remaining_ids
    assert str(old_id_1) not in remaining_ids
    assert str(old_id_2) not in remaining_ids


def test_archiver_move_to_cold_sets_archived_true(live_db, monkeypatch):
    """move-to-cold policy: old events set archived=true, recent events stay archived=false."""
    engine, env = live_db
    _apply_env(monkeypatch, env)

    source_id = _insert_source(engine, archive_policy="move-to-cold", hot_retention_days=7)
    now = datetime.now(timezone.utc)

    old_id_1 = _insert_event(engine, source_id=source_id, observed_at=now - timedelta(days=10))
    old_id_2 = _insert_event(engine, source_id=source_id, observed_at=now - timedelta(days=20))
    recent_id = _insert_event(engine, source_id=source_id, observed_at=now - timedelta(hours=2))

    from app.services.archiver import archive_once

    with Session(engine) as session:
        totals = archive_once(session)

    assert totals["move-to-cold"] >= 2

    # Verify all 3 events still exist
    with Session(engine) as s:
        rows = s.execute(
            text("SELECT id, archived FROM events WHERE source_id = :sid"),
            {"sid": str(source_id)},
        ).all()
    id_to_archived = {str(r[0]): r[1] for r in rows}

    assert str(old_id_1) in id_to_archived
    assert str(old_id_2) in id_to_archived
    assert str(recent_id) in id_to_archived
    assert id_to_archived[str(old_id_1)] is True
    assert id_to_archived[str(old_id_2)] is True
    assert id_to_archived[str(recent_id)] is False


def test_archiver_keep_policy_is_noop(live_db, monkeypatch):
    """keep policy: no events deleted or archived regardless of age."""
    engine, env = live_db
    _apply_env(monkeypatch, env)

    source_id = _insert_source(engine, archive_policy="keep", hot_retention_days=1)
    now = datetime.now(timezone.utc)

    old_id = _insert_event(engine, source_id=source_id, observed_at=now - timedelta(days=365))
    recent_id = _insert_event(engine, source_id=source_id, observed_at=now - timedelta(hours=1))

    from app.services.archiver import archive_once

    with Session(engine) as session:
        totals = archive_once(session)

    # keep contributes 0 rows
    assert totals["keep"] == 0

    with Session(engine) as s:
        rows = s.execute(
            text("SELECT id, archived FROM events WHERE source_id = :sid"),
            {"sid": str(source_id)},
        ).all()
    id_to_archived = {str(r[0]): r[1] for r in rows}

    # Both events present and not archived
    assert str(old_id) in id_to_archived
    assert str(recent_id) in id_to_archived
    assert id_to_archived[str(old_id)] is False
    assert id_to_archived[str(recent_id)] is False


def test_scheduler_registers_archiver_nightly_job(live_db, monkeypatch):
    """build_scheduler() must register archiver_nightly with CronTrigger(hour=3, minute=0)."""
    engine, env = live_db
    _apply_env(monkeypatch, env)

    from app.scheduler.jobs import build_scheduler

    sched = build_scheduler()
    job = sched.get_job("archiver_nightly")
    assert job is not None, "archiver_nightly job not registered"
    assert isinstance(job.trigger, CronTrigger), f"Expected CronTrigger, got {type(job.trigger)}"

    # Verify the cron fields
    trigger_fields = {f.name: str(f) for f in job.trigger.fields}
    assert trigger_fields.get("hour") == "3", f"Expected hour=3, got {trigger_fields.get('hour')}"
    assert trigger_fields.get("minute") == "0", f"Expected minute=0, got {trigger_fields.get('minute')}"

    if sched.state:
        sched.shutdown(wait=False)


def test_scheduler_preserves_phase1_and_phase2_jobs(live_db, monkeypatch):
    """build_scheduler() must still register Phase 1 jobs (non-regression)."""
    engine, env = live_db
    _apply_env(monkeypatch, env)

    from app.scheduler.jobs import build_scheduler

    sched = build_scheduler()
    job_ids = {j.id for j in sched.get_jobs()}

    assert "attack_weekly_refresh" in job_ids, "Phase 1 attack_weekly_refresh job missing"
    assert "attack_first_boot" in job_ids, "Phase 1 attack_first_boot job missing"
    assert "archiver_nightly" in job_ids, "Phase 3 archiver_nightly job missing"

    if sched.state:
        sched.shutdown(wait=False)

"""APScheduler per-source job registration — /.

Uses testcontainers PG to seed sources rows, then invokes build_scheduler
and introspects scheduler.get_jobs to verify one IntervalTrigger job per
enabled source with deterministic id.
"""
from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def live_db():
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
            "JWT_SIGNING_KEY": "j" * 64,
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
    feed_type: str,
    enabled: bool = True,
    interval: int = 3600,
) -> uuid.UUID:
    sid = uuid.uuid4()
    with Session(engine) as s:
        s.execute(
            text("""
 INSERT INTO sources (id, name, feed_type, url, poll_interval_sec, enabled)
 VALUES (:id,:name,:ft,:url,:iv,:en)
"""),
            {
                "id": str(sid),
                "name": f"{feed_type}-fixture-{sid}",
                "ft": feed_type,
                "url": f"http://fixture/{feed_type}/{sid}",
                "iv": interval,
                "en": enabled,
            },
        )
        s.commit()
    return sid


def _apply_env(monkeypatch: pytest.MonkeyPatch, env: dict) -> None:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    # Force Settings reload so it picks up the new env vars
    import importlib

    import app.config as cfg_module

    importlib.reload(cfg_module)
    monkeypatch.setattr("app.config.settings", cfg_module.settings)


def test_build_scheduler_preserves_phase_1_jobs(live_db, monkeypatch):
    engine, env = live_db
    _apply_env(monkeypatch, env)
    from app.scheduler.jobs import build_scheduler

    sched = build_scheduler()
    ids = {j.id for j in sched.get_jobs()}
    assert "attack_weekly_refresh" in ids
    assert "attack_first_boot" in ids
    if sched.state:
        sched.shutdown(wait=False)


def test_build_scheduler_registers_one_job_per_enabled_source(live_db, monkeypatch):
    engine, env = live_db
    _apply_env(monkeypatch, env)
    # Clean slate
    with Session(engine) as s:
        s.execute(text("DELETE FROM sources"))
        s.commit()
    rss_id = _insert_source(engine, "rss", enabled=True, interval=600)
    nvd_id = _insert_source(engine, "nvd", enabled=True, interval=3600)
    taxii_id = _insert_source(engine, "taxii", enabled=True, interval=1800)

    from app.scheduler.jobs import build_scheduler

    sched = build_scheduler()
    ids = {j.id for j in sched.get_jobs()}
    assert f"poll_rss_{rss_id}" in ids
    assert f"poll_nvd_{nvd_id}" in ids
    assert f"poll_taxii_{taxii_id}" in ids
    if sched.state:
        sched.shutdown(wait=False)


def test_build_scheduler_skips_disabled_sources(live_db, monkeypatch):
    engine, env = live_db
    _apply_env(monkeypatch, env)
    with Session(engine) as s:
        s.execute(text("DELETE FROM sources"))
        s.commit()
    enabled_id = _insert_source(engine, "rss", enabled=True)
    disabled_id = _insert_source(engine, "rss", enabled=False)

    from app.scheduler.jobs import build_scheduler

    sched = build_scheduler()
    ids = {j.id for j in sched.get_jobs()}
    assert f"poll_rss_{enabled_id}" in ids
    assert f"poll_rss_{disabled_id}" not in ids
    if sched.state:
        sched.shutdown(wait=False)


def test_build_scheduler_uses_source_poll_interval(live_db, monkeypatch):
    engine, env = live_db
    _apply_env(monkeypatch, env)
    with Session(engine) as s:
        s.execute(text("DELETE FROM sources"))
        s.commit()
    sid = _insert_source(engine, "rss", interval=900)

    from app.scheduler.jobs import build_scheduler

    sched = build_scheduler()
    job = sched.get_job(f"poll_rss_{sid}")
    assert job is not None
    assert isinstance(job.trigger, IntervalTrigger)
    assert job.trigger.interval.total_seconds() == 900
    if sched.state:
        sched.shutdown(wait=False)


def test_build_scheduler_idempotent(live_db, monkeypatch):
    engine, env = live_db
    _apply_env(monkeypatch, env)
    with Session(engine) as s:
        s.execute(text("DELETE FROM sources"))
        s.commit()
    sid = _insert_source(engine, "rss")

    from app.scheduler.jobs import build_scheduler

    first = build_scheduler()
    first_ids = {j.id for j in first.get_jobs()}
    if first.state:
        first.shutdown(wait=False)

    second = build_scheduler()
    second_ids = {j.id for j in second.get_jobs()}
    if second.state:
        second.shutdown(wait=False)

    assert first_ids == second_ids
    assert f"poll_rss_{sid}" in first_ids


def test_build_scheduler_ignores_unknown_feed_type(live_db, monkeypatch, caplog):
    engine, env = live_db
    _apply_env(monkeypatch, env)
    with Session(engine) as s:
        s.execute(text("DELETE FROM sources"))
        s.commit()
    custom_id = _insert_source(engine, "custom", enabled=True)

    from app.scheduler.jobs import build_scheduler

    with caplog.at_level("WARNING"):
        sched = build_scheduler()
    ids = {j.id for j in sched.get_jobs()}
    assert not any(f"_{custom_id}" in i for i in ids)
    assert any("scheduler_unknown_feed_type" in rec.getMessage() for rec in caplog.records)
    if sched.state:
        sched.shutdown(wait=False)

"""Integration: poll_rss end-to-end against captured Krebs fixture + live PG.

INGR-01 (schedule + persist) via direct invocation (APScheduler wiring in plan 06).
INGR-02 (normalisation) — SYS-01 provenance asserted.
INGR-03 (dedup) — re-poll yields zero new rows.
D-33 — sources.last_polled_at / last_status / consecutive_failures updated.
"""
from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[2]
FIXTURE = BACKEND_DIR / "tests" / "fixtures" / "rss_krebs_2026-04.xml"


@pytest.fixture(scope="module")
def live_db():
    with PostgresContainer("intellibird-db:m1") as pg:
        url = pg.get_connection_url()
        raw = pg.get_connection_url()
        # Build asyncpg URL from raw components to avoid URL masking issues
        from sqlalchemy.engine import make_url
        parsed_url = make_url(url)
        asyncpg_url = (
            f"postgresql+asyncpg://{parsed_url.username}:{parsed_url.password}"
            f"@{parsed_url.host}:{parsed_url.port}/{parsed_url.database}"
        )
        env = os.environ | {
            "DATABASE_URL": asyncpg_url,
            "SECRET_KEY": "x" * 48,
            "REDIS_URL": "redis://localhost:1",  # actor runs sync in tests, broker not touched
        }
        r = subprocess.run(["uv", "run", "alembic", "upgrade", "head"],
                           cwd=str(BACKEND_DIR), env=env, capture_output=True, text=True)
        if r.returncode != 0:
            pytest.skip(f"alembic failed (AGE missing likely): {r.stderr[:400]}")
        sync_url = (
            f"postgresql://{parsed_url.username}:{parsed_url.password}"
            f"@{parsed_url.host}:{parsed_url.port}/{parsed_url.database}"
        )
        engine = create_engine(sync_url, future=True)
        yield engine, env
        engine.dispose()


@pytest.fixture()
def rss_source_id(live_db):
    engine, env = live_db
    sid = uuid.uuid4()
    fixture_url = str(FIXTURE)
    with Session(engine) as s:
        s.execute(text("""
            INSERT INTO sources (id, name, feed_type, url, poll_interval_sec)
            VALUES (:id, 'krebs-fixture', 'rss', :url, 3600)
        """), {"id": str(sid), "url": fixture_url})
        s.commit()
    return sid


def test_rss_poll_end_to_end(live_db, rss_source_id, monkeypatch: pytest.MonkeyPatch):
    engine, env = live_db
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    # Force settings to re-read env
    from app.config import Settings
    monkeypatch.setattr("app.config.settings", Settings())  # type: ignore[call-arg]

    from app.workers.rss import poll_rss_impl
    poll_rss_impl(str(rss_source_id))

    with Session(engine) as s:
        count = s.execute(
            text("SELECT count(*) FROM events WHERE source_id = :sid"),
            {"sid": str(rss_source_id)},
        ).scalar()
        assert count == 2

        row = s.execute(
            text("""SELECT title, raw_reference, source_id, stix_type, content_hash
                     FROM events WHERE source_id = :sid ORDER BY observed_at"""),
            {"sid": str(rss_source_id)},
        ).all()
        titles = [r.title for r in row]
        assert titles[0].startswith("Fixture Entry One")
        assert all(r.stix_type == "x-intellibird-rss" for r in row)
        assert all(r.content_hash for r in row)


def test_rss_poll_dedup_on_refetch(live_db, rss_source_id, monkeypatch: pytest.MonkeyPatch):
    engine, env = live_db
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from app.config import Settings
    monkeypatch.setattr("app.config.settings", Settings())  # type: ignore[call-arg]

    from app.workers.rss import poll_rss_impl
    poll_rss_impl(str(rss_source_id))
    poll_rss_impl(str(rss_source_id))  # second poll — should dedup

    with Session(engine) as s:
        count = s.execute(
            text("SELECT count(*) FROM events WHERE source_id = :sid"),
            {"sid": str(rss_source_id)},
        ).scalar()
        assert count == 2  # INGR-03 — no duplicate rows


def test_rss_poll_source_health_on_success(live_db, rss_source_id, monkeypatch: pytest.MonkeyPatch):
    engine, env = live_db
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from app.config import Settings
    monkeypatch.setattr("app.config.settings", Settings())  # type: ignore[call-arg]

    from app.workers.rss import poll_rss_impl
    poll_rss_impl(str(rss_source_id))

    with Session(engine) as s:
        row = s.execute(
            text("""SELECT last_polled_at, last_status, consecutive_failures
                     FROM sources WHERE id = :id"""),
            {"id": str(rss_source_id)},
        ).one()
        assert row.last_polled_at is not None
        assert row.last_status == "ok"
        assert row.consecutive_failures == 0

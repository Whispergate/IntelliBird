"""Integration tests for project_id binding fan-out in ingest — Quick task 260429-tyq.

Covers:
  1. One binding         → event lands in bound project (not LEGACY).
  2. Two bindings        → fan-out: two rows, same content_hash, different project_id.
  3. Zero bindings       → LEGACY fallback unchanged.
  4. Per-project dedup   → second identical insert returns (0, 1).
  5. Unique index shape  → uq_events_source_content_hash leads with project_id.

Pattern follows test_migration_012.py — module-scoped testcontainer with sync engine.
Tests target `_persist_event_for_bindings` directly (sync helper, sync session).
"""
from __future__ import annotations

import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[2]
LEGACY_PROJECT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture(scope="module")
def live_db_head():
    """Spin up intellibird-db:m1, run `alembic upgrade head` (includes migration 021).

    Yields a sync Engine pointing at the upgraded DB. Module-scoped so the
    container survives across the 5 test functions in this file.
    """
    with PostgresContainer("intellibird-db:m1") as pg:
        url = pg.get_connection_url()
        parsed = make_url(url)
        asyncpg_url = (
            f"postgresql+asyncpg://{parsed.username}:{parsed.password}"
            f"@{parsed.host}:{parsed.port}/{parsed.database}"
        )
        env = os.environ | {
            "DATABASE_URL": asyncpg_url,
            "SECRET_KEY": "x" * 48,
            "JWT_SIGNING_KEY": "y" * 48,
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
            pytest.skip(f"alembic upgrade head failed: {r.stderr[:800]}")
        sync_url = (
            f"postgresql://{parsed.username}:{parsed.password}"
            f"@{parsed.host}:{parsed.port}/{parsed.database}"
        )
        engine = create_engine(sync_url, future=True)
        yield engine
        engine.dispose()


@pytest.fixture
def db_session(live_db_head) -> Session:
    """Function-scoped sync Session with per-test cleanup.

    Truncates events + project_sources + projects (preserving LEGACY sentinel)
    before each test so seed data does not leak across tests.
    """
    engine = live_db_head
    with Session(engine) as session:
        # Reset state — remove non-sentinel projects (cascades to project_sources,
        # events). Events truncate is explicit because its FK is RESTRICT-style on
        # projects.id (not CASCADE).
        session.execute(text("TRUNCATE TABLE attack_technique_tags RESTART IDENTITY"))
        session.execute(text("TRUNCATE TABLE events RESTART IDENTITY CASCADE"))
        session.execute(text(
            "DELETE FROM projects WHERE id NOT IN ("
            "  '00000000-0000-0000-0000-000000000000',"  # System Monitoring sentinel
            "  '00000000-0000-0000-0000-000000000001'"   # _legacy sentinel
            ")"
        ))
        session.execute(text(
            "DELETE FROM sources WHERE id <> '00000000-0000-0000-0000-000000000000'"
        ))
        session.commit()
        yield session


def _setup(session: Session, *, num_bindings: int) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Insert 1 source + N projects + N project_sources rows.

    Returns (source_id, [project_ids]).
    """
    source_id = uuid.uuid4()
    session.execute(text(
        "INSERT INTO sources (id, name, feed_type, url, enabled, confidence) "
        "VALUES (:id, :n, 'rss', 'https://example.com/feed.xml', true, 0.7)"
    ), {"id": str(source_id), "n": f"src-{source_id.hex[:8]}"})
    project_ids: list[uuid.UUID] = []
    for i in range(num_bindings):
        pid = uuid.uuid4()
        session.execute(text(
            "INSERT INTO projects (id, name, engagement_type, created_by) "
            "VALUES (:id, :n, 'internal', 'test')"
        ), {"id": str(pid), "n": f"proj-{pid.hex[:8]}-{i}"})
        session.execute(text(
            "INSERT INTO project_sources (project_id, source_id) VALUES (:p, :s)"
        ), {"p": str(pid), "s": str(source_id)})
        project_ids.append(pid)
    session.commit()
    return source_id, project_ids


def _make_row(source_id: uuid.UUID, *, content_hash: str, observed_at: datetime | None = None) -> dict:
    """Minimal valid event row dict for _persist_event_for_bindings."""
    obs = observed_at or datetime.now(timezone.utc)
    return {
        "stix_id": f"indicator--{uuid.uuid4()}",
        "stix_type": "indicator",
        "source_id": source_id,
        "fetched_at": obs,
        "observed_at": obs,
        "title": "test event",
        "description": "fixture",
        "content_hash": content_hash,
        "raw_stix": {"objects": []},
        "tags": [],
        "raw_reference": "https://example.com/item/1",
    }


def test_one_binding_routes_to_bound_project(db_session: Session) -> None:
    from app.ingest.normalise import _persist_event_for_bindings

    source_id, project_ids = _setup(db_session, num_bindings=1)
    row = _make_row(source_id, content_hash="hash_one_binding")
    inserted, fanout = _persist_event_for_bindings(db_session, row, source_id)
    db_session.commit()

    assert (inserted, fanout) == (1, 1)
    rows = db_session.execute(text(
        "SELECT project_id FROM events WHERE content_hash = :h"
    ), {"h": "hash_one_binding"}).all()
    assert len(rows) == 1
    assert rows[0][0] == project_ids[0]
    assert rows[0][0] != LEGACY_PROJECT_ID


def test_multi_binding_fans_out_per_project(db_session: Session) -> None:
    from app.ingest.normalise import _persist_event_for_bindings

    source_id, project_ids = _setup(db_session, num_bindings=2)
    row = _make_row(source_id, content_hash="shared_hash_multi")
    inserted, fanout = _persist_event_for_bindings(db_session, row, source_id)
    db_session.commit()

    assert (inserted, fanout) == (2, 2)
    rows = db_session.execute(text(
        "SELECT project_id FROM events WHERE content_hash = :h ORDER BY project_id"
    ), {"h": "shared_hash_multi"}).all()
    assert len(rows) == 2
    persisted = {r[0] for r in rows}
    assert persisted == set(project_ids)


def test_zero_bindings_falls_back_to_legacy(db_session: Session) -> None:
    from app.ingest.normalise import _persist_event_for_bindings

    source_id, _ = _setup(db_session, num_bindings=0)
    row = _make_row(source_id, content_hash="hash_unbound")
    inserted, fanout = _persist_event_for_bindings(db_session, row, source_id)
    db_session.commit()

    assert (inserted, fanout) == (1, 1)
    rows = db_session.execute(text(
        "SELECT project_id FROM events WHERE content_hash = :h"
    ), {"h": "hash_unbound"}).all()
    assert len(rows) == 1
    assert rows[0][0] == LEGACY_PROJECT_ID


def test_per_project_dedup_within_same_project(db_session: Session) -> None:
    from app.ingest.normalise import _persist_event_for_bindings

    source_id, project_ids = _setup(db_session, num_bindings=1)
    obs = datetime.now(timezone.utc)
    row = _make_row(source_id, content_hash="hash_dedup", observed_at=obs)

    first = _persist_event_for_bindings(db_session, row, source_id)
    db_session.commit()
    second = _persist_event_for_bindings(db_session, _make_row(
        source_id, content_hash="hash_dedup", observed_at=obs,
    ), source_id)
    db_session.commit()

    assert first == (1, 1)
    assert second == (0, 1)
    count = db_session.execute(text(
        "SELECT COUNT(*) FROM events WHERE content_hash = :h"
    ), {"h": "hash_dedup"}).scalar_one()
    assert count == 1


def test_unique_index_includes_project_id(db_session: Session) -> None:
    indexdef = db_session.execute(text(
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_events_source_content_hash'"
    )).scalar_one()
    # Migration 021 puts project_id first, then source_id, content_hash, observed_at.
    assert "project_id" in indexdef
    assert indexdef.index("project_id") < indexdef.index("source_id")
    assert "observed_at" in indexdef  # TimescaleDB partition column requirement

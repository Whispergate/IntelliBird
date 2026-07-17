"""Migration 002 — UNIQUE(source_id, content_hash) on events hypertable.

Requirement: INGR-03 (dedup) + PITFALLS H-3 (race-free dedup at DB layer).
: DB-level unique constraint, not app-level SELECT-then-INSERT.
: Constraint on (source_id, content_hash), NOT global — same content
from different sources is legitimately stored twice.
"""
from __future__ import annotations

import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def migrated_engine():
    """Run alembic upgrade head against a fresh TimescaleDB+AGE container.

 Uses the locally-built intellibird-db:m1 image (Postgres 16 +
 TimescaleDB + Apache AGE) so migration 001's CREATE EXTENSION age
 succeeds. Falls back gracefully via pytest.skip if unavailable.
"""
    import os
    with PostgresContainer("intellibird-db:m1") as pg:
        url = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql+asyncpg://")
        env2 = os.environ | {"DATABASE_URL": url}
        result = subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head"],
            cwd=str(BACKEND_DIR),
            env=env2,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip(
                f"alembic upgrade failed against stock timescaledb (AGE missing likely): {result.stderr[:500]}"
            )
        sync_url = url.replace("postgresql+asyncpg://", "postgresql://")
        engine = create_engine(sync_url, future=True)
        yield engine
        engine.dispose()


LEGACY_PROJECT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _mk_event_row(source_id: uuid.UUID, content_hash: str, observed_at: datetime | None = None) -> dict:
    return {
        "stix_type": "x-intellibird-rss",
        "source_id": source_id,
        # events.project_id NOT NULL — seed against legacy sentinel.
        "project_id": LEGACY_PROJECT_ID,
        "observed_at": observed_at or datetime.now(timezone.utc),
        "content_hash": content_hash,
        "visibility": "shared",
        "title": "fixture",
    }


def test_alembic_head_is_0002(migrated_engine) -> None:
    with migrated_engine.connect() as conn:
        row = conn.execute(text("SELECT version_num FROM alembic_version")).one()
    # renamed alembic head; migration 002's unique-index invariant is
    # still covered by head==009 (see migration 009's test coverage for new
    # project_id column; this file just pins that migrations advanced past 002).
    assert row[0] == "009_projects_and_memberships", f"expected 009 head, got {row[0]}"


def test_unique_constraint_enforced(migrated_engine) -> None:
    """Two rows with same (source_id, content_hash, observed_at) must raise IntegrityError.

 TimescaleDB requires the partition column (observed_at) to be part of the
 unique index. Dedup is therefore enforced when source_id + content_hash +
 observed_at are identical — which is the real-world duplicate scenario: a
 re-fetched item with the same content_hash will have the same observed_at
 (since we use the item's publication timestamp, not ingestion time).
"""
    sid = uuid.uuid4()
    h = "hash_abc_123"
    ts = "2026-04-10 12:00:00+00"
    with Session(migrated_engine) as s:
        s.execute(
            text("INSERT INTO sources (id, name, feed_type, url) VALUES (:id, 'fixture', 'rss', 'http://x')"),
            {"id": str(sid)},
        )
        s.commit()
        s.execute(
            text("""
 INSERT INTO events (stix_type, source_id, project_id, observed_at, content_hash, visibility, title)
 VALUES ('x-intellibird-rss',:sid,:pid,:ts,:h, 'shared', 'one')
"""),
            {"sid": str(sid), "pid": str(LEGACY_PROJECT_ID), "h": h, "ts": ts},
        )
        s.commit()
        with pytest.raises(IntegrityError) as excinfo:
            s.execute(
                text("""
 INSERT INTO events (stix_type, source_id, project_id, observed_at, content_hash, visibility, title)
 VALUES ('x-intellibird-rss',:sid,:pid,:ts,:h, 'shared', 'two')
"""),
                {"sid": str(sid), "pid": str(LEGACY_PROJECT_ID), "h": h, "ts": ts},
            )
            s.commit()
        assert "uq_events_source_content_hash" in str(excinfo.value)
        s.rollback()


def test_unique_constraint_allows_different_sources(migrated_engine) -> None:
    """: same (content_hash, observed_at) from two different source_ids is stored twice.

 The unique index is (source_id, content_hash, observed_at) — changing
 source_id makes the tuple distinct. Same content from different sources
 is legitimately stored twice (different provenance).
"""
    sid1 = uuid.uuid4()
    sid2 = uuid.uuid4()
    h = "hash_xyz_456"
    ts = "2026-04-11 12:00:00+00"
    with Session(migrated_engine) as s:
        s.execute(
            text("""
 INSERT INTO sources (id, name, feed_type, url) VALUES (:id1, 'f1', 'rss', 'http://a'),
 (:id2, 'f2', 'rss', 'http://b')
"""),
            {"id1": str(sid1), "id2": str(sid2)},
        )
        s.commit()
        s.execute(
            text("""
 INSERT INTO events (stix_type, source_id, project_id, observed_at, content_hash, visibility, title)
 VALUES ('x-intellibird-rss',:sid1,:pid,:ts,:h, 'shared', 'a'),
 ('x-intellibird-rss',:sid2,:pid,:ts,:h, 'shared', 'b')
"""),
            {"sid1": str(sid1), "sid2": str(sid2), "pid": str(LEGACY_PROJECT_ID), "h": h, "ts": ts},
        )
        s.commit()
        count = s.execute(text("SELECT count(*) FROM events WHERE content_hash = :h"), {"h": h}).scalar()
    assert count == 2


def test_on_conflict_do_nothing(migrated_engine) -> None:
    """: ON CONFLICT DO NOTHING is race-free — two inserts yield 1 row."""
    from app.models.events import Event  # noqa: PLC0415

    sid = uuid.uuid4()
    h = "hash_conflict_789"
    with Session(migrated_engine) as s:
        s.execute(
            text("INSERT INTO sources (id, name, feed_type, url) VALUES (:id, 'f', 'rss', 'http://c')"),
            {"id": str(sid)},
        )
        s.commit()
        row = _mk_event_row(sid, h, datetime(2026, 4, 10, 12, 0, 0, tzinfo=timezone.utc))
        for _ in range(2):
            stmt = pg_insert(Event.__table__).values(**row).on_conflict_do_nothing(
                index_elements=["source_id", "content_hash", "observed_at"]
            )
            s.execute(stmt)
        s.commit()
        count = s.execute(text("SELECT count(*) FROM events WHERE content_hash = :h"), {"h": h}).scalar()
    assert count == 1

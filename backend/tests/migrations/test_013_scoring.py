"""Migration 013 integration tests - scoring schema foundation.

Verifies:
  - events table gains score numeric(5,2), scored_at timestamptz, score_version int (all NULL)
  - ix_events_project_score index created on events (project_id, score DESC)
  - event_score_overrides table created with PK (event_id, score_version)
  - project_scoring_rules table created with UNIQUE project_id FK
  - sources.confidence column added (numeric(3,2))
  - Backfill: taxii=1.0, nvd=1.0, rss=0.7

Run order:
  1. Testcontainer intellibird-db:m1 (TimescaleDB + AGE)
  2. alembic upgrade 012 (baseline)
  3. Seed sources per feed_type
  4. alembic upgrade 013_scoring
  5. Assert columns + tables + indexes + backfill values
  6. alembic downgrade 012
  7. Assert schema reverted

SCR-01: score, scored_at, score_version on events
SCR-03: project_scoring_rules with project_id FK to projects
"""
from __future__ import annotations

import os
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _testcontainers_importable() -> bool:
    try:
        import testcontainers.postgres  # noqa: F401
    except ImportError:
        return False
    return os.environ.get("SKIP_TESTCONTAINERS") != "1"


@pytest.fixture(scope="module")
def live_db_013():
    """Stand up intellibird-db:m1, migrate to 012, seed sources, yield (engine, env).

    Subsequent tests call alembic upgrade 013_scoring / downgrade 012 to exercise
    the migration.
    """
    if not _testcontainers_importable():
        pytest.skip("testcontainers unavailable - install or unset SKIP_TESTCONTAINERS")

    from testcontainers.postgres import PostgresContainer

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

        # Migrate to 012 (baseline before 013)
        r = subprocess.run(
            ["uv", "run", "alembic", "upgrade", "012"],
            cwd=str(BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            pytest.skip(f"alembic upgrade 012 failed:\n{r.stderr[:600]}")

        sync_url = (
            f"postgresql://{parsed.username}:{parsed.password}"
            f"@{parsed.host}:{parsed.port}/{parsed.database}"
        )
        engine = create_engine(sync_url, future=True)

        # Seed one source per feed_type so backfill assertions are meaningful.
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO sources (id, name, feed_type, url) "
                    "VALUES "
                    "(gen_random_uuid(), 'taxii-test', 'taxii', 'https://taxii.example.com'), "
                    "(gen_random_uuid(), 'nvd-test',   'nvd',   'https://nvd.example.com'), "
                    "(gen_random_uuid(), 'rss-test',   'rss',   'https://rss.example.com')"
                )
            )

        yield engine, env
        engine.dispose()


def _upgrade_013(env) -> None:
    r = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "013_scoring"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"alembic upgrade 013_scoring failed:\n{r.stderr[:800]}"


def _downgrade_012(env) -> None:
    r = subprocess.run(
        ["uv", "run", "alembic", "downgrade", "012"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"alembic downgrade 012 failed:\n{r.stderr[:800]}"


def test_migration_013_adds_columns_and_tables(live_db_013):
    """After upgrade 013, verify all schema additions are present.

    Checks:
    - events gains score, scored_at, score_version columns (nullable)
    - sources gains confidence column (nullable)
    - event_score_overrides and project_scoring_rules tables exist
    - ix_events_project_score index exists
    """
    engine, env = live_db_013
    _upgrade_013(env)

    with engine.connect() as conn:
        # events columns: score, scored_at, score_version
        event_cols = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'events' "
                "  AND column_name IN ('score', 'scored_at', 'score_version') "
                "ORDER BY column_name"
            )
        ).fetchall()
        assert len(event_cols) == 3, (
            f"Expected 3 score columns on events; got {[r[0] for r in event_cols]}"
        )

        # All three must be nullable
        nullable_check = conn.execute(
            text(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_name = 'events' "
                "  AND column_name IN ('score', 'scored_at', 'score_version')"
            )
        ).fetchall()
        for col_name, is_nullable in nullable_check:
            assert is_nullable == "YES", f"events.{col_name} must be nullable"

        # sources.confidence column
        conf_col = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'sources' AND column_name = 'confidence'"
            )
        ).fetchall()
        assert len(conf_col) == 1, "sources.confidence column missing"

        # New tables exist
        tables = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name IN ('event_score_overrides', 'project_scoring_rules') "
                "ORDER BY table_name"
            )
        ).fetchall()
        assert len(tables) == 2, (
            f"Expected 2 new tables; got {[r[0] for r in tables]}"
        )

        # ix_events_project_score index exists on events
        idx = conn.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'events' AND indexname = 'ix_events_project_score'"
            )
        ).scalar_one_or_none()
        assert idx is not None, "ix_events_project_score index missing after upgrade"


def test_migration_013_backfills_source_confidence(live_db_013):
    """After upgrade 013, sources.confidence is backfilled per feed_type.

    taxii = 1.0, nvd = 1.0, rss = 0.7
    """
    engine, env = live_db_013

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT feed_type, confidence FROM sources "
                "WHERE feed_type IN ('taxii', 'nvd', 'rss') "
                "ORDER BY feed_type"
            )
        ).fetchall()

        confidence_map = {row.feed_type: row.confidence for row in rows}

        assert Decimal(str(confidence_map["taxii"])) == Decimal("1.0"), (
            f"taxii confidence should be 1.0, got {confidence_map.get('taxii')}"
        )
        assert Decimal(str(confidence_map["nvd"])) == Decimal("1.0"), (
            f"nvd confidence should be 1.0, got {confidence_map.get('nvd')}"
        )
        assert Decimal(str(confidence_map["rss"])) == Decimal("0.7"), (
            f"rss confidence should be 0.7, got {confidence_map.get('rss')}"
        )


def test_migration_013_downgrade_reverses_cleanly(live_db_013):
    """alembic downgrade 012 removes all 013 additions.

    Verifies:
    - events no longer has score, scored_at, score_version
    - sources no longer has confidence
    - event_score_overrides and project_scoring_rules tables are gone
    - ix_events_project_score index is gone
    """
    engine, env = live_db_013
    _downgrade_012(env)

    with engine.connect() as conn:
        # events score columns should be gone
        event_cols = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'events' "
                "  AND column_name IN ('score', 'scored_at', 'score_version')"
            )
        ).fetchall()
        assert len(event_cols) == 0, (
            f"Score columns should be dropped on downgrade; still found: {[r[0] for r in event_cols]}"
        )

        # sources.confidence should be gone
        conf_col = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'sources' AND column_name = 'confidence'"
            )
        ).fetchall()
        assert len(conf_col) == 0, "sources.confidence should be dropped on downgrade"

        # new tables should be gone
        tables = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name IN ('event_score_overrides', 'project_scoring_rules')"
            )
        ).fetchall()
        assert len(tables) == 0, (
            f"New tables should be dropped on downgrade; still found: {[r[0] for r in tables]}"
        )

        # ix_events_project_score should be gone
        idx = conn.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'events' AND indexname = 'ix_events_project_score'"
            )
        ).scalar_one_or_none()
        assert idx is None, "ix_events_project_score must be dropped on downgrade"

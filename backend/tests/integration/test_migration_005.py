"""Migration 005 partial geo index —-02 (MAP-05).

Tests verify:
- upgrade to 005 creates idx_events_geo_coords with a WHERE clause
- downgrade to 004 removes the index
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def live_db_004():
    """Start intellibird-db:m1, migrate to 004, yield (engine, env).

 The migration-005 tests need to control the exact revision they're on,
 so this fixture leaves the DB at 004 — tests can then upgrade to 005
 and downgrade back.
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
            "REDIS_URL": "redis://localhost:1",
        }
        # Migrate to 004 (one step below 005)
        r = subprocess.run(
            ["uv", "run", "alembic", "upgrade", "004_fts_and_presets"],
            cwd=str(BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            pytest.skip(f"alembic upgrade 004 failed: {r.stderr[:500]}")
        sync_url = (
            f"postgresql://{parsed.username}:{parsed.password}"
            f"@{parsed.host}:{parsed.port}/{parsed.database}"
        )
        engine = create_engine(sync_url, future=True)
        yield engine, env
        engine.dispose()


def test_migration_005_creates_partial_index(live_db_004):
    """Upgrading to 005 creates idx_events_geo_coords with a partial WHERE clause."""
    engine, env = live_db_004

    r = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "005_geo_backfill_and_indexes"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"alembic upgrade 005 failed:\n{r.stderr[:500]}"

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE indexname = 'idx_events_geo_coords'"
            )
        ).all()

    assert len(rows) == 1, (
        f"Expected exactly 1 row for idx_events_geo_coords, got {len(rows)}"
    )
    indexdef = rows[0][0]
    assert "WHERE" in indexdef, f"Expected partial index (WHERE clause) but got: {indexdef}"
    assert "geo_lat IS NOT NULL" in indexdef, (
        f"Expected 'geo_lat IS NOT NULL' in indexdef but got: {indexdef}"
    )


def test_migration_005_downgrade_drops_index(live_db_004):
    """Downgrading from 005 to 004 removes idx_events_geo_coords."""
    engine, env = live_db_004

    # The previous test left us at 005; downgrade to 004
    r = subprocess.run(
        ["uv", "run", "alembic", "downgrade", "004_fts_and_presets"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"alembic downgrade failed:\n{r.stderr[:500]}"

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE indexname = 'idx_events_geo_coords'"
            )
        ).all()

    assert len(rows) == 0, (
        f"Expected idx_events_geo_coords to be gone after downgrade, got {len(rows)} rows"
    )

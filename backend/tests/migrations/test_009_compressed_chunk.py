"""Migration 009 dry-run against TimescaleDB hypertable with compressed chunk.

Validates C-4 mitigation: three-step-plus sentinel backfill completes cleanly
even when events carries at least one compressed chunk. Tests both upgrade and
downgrade paths.

Spike finding (plan 10-01 live dry-run, 2026-04-19): TimescaleDB 2.26 rejects
`ADD COLUMN ... REFERENCES` as a single statement on a hypertable with
columnstore enabled. Migration 009 splits the FK into its own ALTER TABLE
statement. These tests are the regression gate for that fix.

Run order:
  1. Testcontainer intellibird-db:m1 (TimescaleDB + AGE extensions)
  2. alembic upgrade 008_users_and_auth
  3. Insert 5 seed events spanning >2 weeks; enable compression;
     compress_chunk the oldest
  4. alembic upgrade 009_projects_and_memberships
  5. Assert sentinel row + 3 NOT NULL columns + composite index + backfill
  6. alembic downgrade 008_users_and_auth
  7. Assert schema reverted (no projects table, no project_id columns, no enums)
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import sqlalchemy as sa
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
def live_db_009():
    """Stand up intellibird-db:m1, migrate to 008, seed+compress, yield (engine, env).

    Subsequent tests call alembic upgrade 009 / downgrade 008 to exercise the
    migration.
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

        # Migrate to 008 (one step below 009)
        r = subprocess.run(
            ["uv", "run", "alembic", "upgrade", "008_users_and_auth"],
            cwd=str(BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            pytest.skip(f"alembic upgrade 008 failed:\n{r.stderr[:600]}")

        sync_url = (
            f"postgresql://{parsed.username}:{parsed.password}"
            f"@{parsed.host}:{parsed.port}/{parsed.database}"
        )
        engine = create_engine(sync_url, future=True)

        # Seed 5 events + enable compression + compress the oldest chunk.
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO events (id, stix_type, observed_at, content_hash, visibility) "
                    "SELECT gen_random_uuid(), 'indicator', now() - (i * interval '4 days'), "
                    "'hash' || i::text, 'shared' FROM generate_series(0, 4) i"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE events SET (timescaledb.compress, "
                    "timescaledb.compress_orderby = 'observed_at DESC')"
                )
            )
            # Compress the oldest chunk (also covers the multi-chunk compression
            # path; TimescaleDB compression policies may compress all-eligible).
            conn.execute(
                text(
                    "SELECT compress_chunk(c) FROM show_chunks('events') c "
                    "ORDER BY 1 DESC LIMIT 1"
                )
            )
            # Sanity: at least one chunk should be compressed now.
            compressed = conn.execute(
                text(
                    "SELECT count(*) FROM timescaledb_information.chunks "
                    "WHERE hypertable_name='events' AND is_compressed"
                )
            ).scalar_one()
            assert compressed >= 1, "expected >=1 compressed chunk before migration 009"

        yield engine, env
        engine.dispose()


def _upgrade_009(env) -> None:
    r = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "009_projects_and_memberships"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"alembic upgrade 009 failed:\n{r.stderr[:800]}"


def _downgrade_008(env) -> None:
    r = subprocess.run(
        ["uv", "run", "alembic", "downgrade", "008_users_and_auth"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"alembic downgrade 008 failed:\n{r.stderr[:800]}"


def test_upgrade_with_compressed_chunk(live_db_009):
    """Migration 009 upgrade succeeds on a hypertable with >=1 compressed chunk.

    This is the CONTEXT.md-mandated compressed-chunk spike (C-4).
    """
    engine, env = live_db_009
    _upgrade_009(env)

    with engine.connect() as conn:
        # Sentinel row present with exact shape from CONTEXT.md.
        row = conn.execute(
            sa.text(
                "SELECT name, engagement_type, archived FROM projects "
                "WHERE id = '00000000-0000-0000-0000-000000000001'::uuid"
            )
        ).one()
        assert row.name == "_legacy"
        assert row.engagement_type == "intel_only"
        assert row.archived is True

        # All 5 pre-existing events backfilled to the sentinel.
        legacy_event_count = conn.execute(
            sa.text(
                "SELECT count(*) FROM events "
                "WHERE project_id = '00000000-0000-0000-0000-000000000001'::uuid"
            )
        ).scalar_one()
        assert legacy_event_count == 5


def test_legacy_sentinel_row_present(live_db_009):
    """After upgrade, LEGACY_PROJECT_ID sentinel row matches the contract."""
    engine, env = live_db_009
    with engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT name, engagement_type, description, created_by, archived, "
                "active_scans_authorised "
                "FROM projects WHERE id = '00000000-0000-0000-0000-000000000001'::uuid"
            )
        ).one()
        assert row.name == "_legacy"
        assert row.engagement_type == "intel_only"
        assert "Pre-project-scoping legacy data" in row.description
        assert row.created_by == "system"
        assert row.archived is True
        assert row.active_scans_authorised is False


def test_events_project_id_nonnull(live_db_009):
    """events.project_id is NOT NULL after backfill step."""
    engine, env = live_db_009
    with engine.connect() as conn:
        is_nullable = conn.execute(
            sa.text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name='events' AND column_name='project_id'"
            )
        ).scalar_one()
        assert is_nullable == "NO"


def test_filter_presets_project_id_nonnull(live_db_009):
    """filter_presets.project_id is NOT NULL after backfill step."""
    engine, env = live_db_009
    with engine.connect() as conn:
        is_nullable = conn.execute(
            sa.text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name='filter_presets' AND column_name='project_id'"
            )
        ).scalar_one()
        assert is_nullable == "NO"


def test_webhooks_project_id_nonnull(live_db_009):
    """webhooks.project_id is NOT NULL after backfill step."""
    engine, env = live_db_009
    with engine.connect() as conn:
        is_nullable = conn.execute(
            sa.text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name='webhooks' AND column_name='project_id'"
            )
        ).scalar_one()
        assert is_nullable == "NO"


def test_composite_index_exists(live_db_009):
    """events_project_observed_idx (project_id, observed_at DESC) exists."""
    engine, env = live_db_009
    with engine.connect() as conn:
        idx = conn.execute(
            sa.text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE tablename='events' AND indexname='events_project_observed_idx'"
            )
        ).scalar_one_or_none()
        assert idx is not None, "events_project_observed_idx missing after upgrade"
        assert "project_id" in idx
        assert "observed_at" in idx


def test_default_dropped_on_three_tables(live_db_009):
    """project_id DEFAULT is dropped after backfill (M-6 enforcement in DDL)."""
    engine, env = live_db_009
    with engine.connect() as conn:
        for table in ("events", "filter_presets", "webhooks"):
            default = conn.execute(
                sa.text(
                    "SELECT column_default FROM information_schema.columns "
                    "WHERE table_name = :t AND column_name='project_id'"
                ),
                {"t": table},
            ).scalar_one()
            assert default is None, f"{table}.project_id default should be NULL"


def test_downgrade_restores_schema(live_db_009):
    """alembic downgrade 008 drops projects + project_id columns + 3 enums."""
    engine, env = live_db_009
    _downgrade_008(env)

    with engine.connect() as conn:
        # projects table gone
        assert conn.execute(sa.text("SELECT to_regclass('public.projects')")).scalar_one() is None
        # project_id columns gone on all three tables
        for table in ("events", "filter_presets", "webhooks"):
            col = conn.execute(
                sa.text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = :t AND column_name='project_id'"
                ),
                {"t": table},
            ).scalar_one_or_none()
            assert col is None, f"{table}.project_id must be dropped after downgrade"
        # enums gone
        for type_name in ("engagement_type", "scope_type", "project_role"):
            t = conn.execute(
                sa.text("SELECT 1 FROM pg_type WHERE typname = :n"),
                {"n": type_name},
            ).scalar_one_or_none()
            assert t is None, f"{type_name} must be dropped after downgrade"

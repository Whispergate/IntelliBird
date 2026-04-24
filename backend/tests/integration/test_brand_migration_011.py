"""Brand Protection migration 011 integration test — brand_terms + brand_matches +
projects.gdpr_person_match_retention_days column.

Phase 12 / BRP-01..BRP-05.

Pattern follows test_easm_migration_010.py: spin up intellibird-db:m1, migrate to
010, upgrade to 011 and assert schema; downgrade back and assert clean teardown.

Tests verify:
- upgrade to 011 creates brand_terms + brand_matches tables
- 5 enum types exist: brand_term_type, brand_term_mode, brand_match_source,
  brand_match_severity, brand_match_lifecycle_status
- projects.gdpr_person_match_retention_days column exists with default 90
- ux_brand_terms_project_type_value UNIQUE functional index exists (case-insensitive)
- ux_brand_matches_dedup UNIQUE constraint on 4 columns exists
- ix_brand_matches_project_last_seen + partial ix_brand_matches_dismiss_until indexes exist
- FK brand_matches.brand_term_id -> brand_terms.id has confdeltype='c' (CASCADE)
- downgrade cleanly removes all 011 artifacts
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def live_db_010():
    """Start intellibird-db:m1, migrate to 010_easm, yield (engine, env).

    Leaves the DB at 010 — tests upgrade to 011 and can downgrade back.
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
            ["uv", "run", "alembic", "upgrade", "010_easm"],
            cwd=str(BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            pytest.skip(f"alembic upgrade 010 failed: {r.stderr[:500]}")
        sync_url = (
            f"postgresql://{parsed.username}:{parsed.password}"
            f"@{parsed.host}:{parsed.port}/{parsed.database}"
        )
        engine = create_engine(sync_url, future=True)
        yield engine, env
        engine.dispose()


def _upgrade_011(env) -> None:
    r = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "011"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"alembic upgrade 011 failed:\n{r.stderr[:800]}"


def _downgrade_010(env) -> None:
    r = subprocess.run(
        ["uv", "run", "alembic", "downgrade", "010_easm"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"alembic downgrade 010 failed:\n{r.stderr[:800]}"


def test_011_upgrade_creates_brand_tables_and_enums(live_db_010):
    """After alembic upgrade 011, brand_terms + brand_matches tables exist and
    all 5 enums are present with expected values."""
    engine, env = live_db_010
    _upgrade_011(env)

    with engine.connect() as conn:
        conn.execute(sa.text("SELECT * FROM brand_terms LIMIT 0"))
        conn.execute(sa.text("SELECT * FROM brand_matches LIMIT 0"))

        tt = conn.execute(sa.text(
            "SELECT unnest(enum_range(NULL::brand_term_type))::text"
        )).scalars().all()
        assert sorted(tt) == sorted(["keyword", "domain", "product", "person"])

        tm = conn.execute(sa.text(
            "SELECT unnest(enum_range(NULL::brand_term_mode))::text"
        )).scalars().all()
        assert sorted(tm) == sorted(["active", "watch_only"])

        ms = conn.execute(sa.text(
            "SELECT unnest(enum_range(NULL::brand_match_source))::text"
        )).scalars().all()
        assert sorted(ms) == sorted(["fts", "ct_log", "dnstwist"])

        sev = conn.execute(sa.text(
            "SELECT unnest(enum_range(NULL::brand_match_severity))::text"
        )).scalars().all()
        assert sorted(sev) == sorted(["low", "medium", "high"])

        lc = conn.execute(sa.text(
            "SELECT unnest(enum_range(NULL::brand_match_lifecycle_status))::text"
        )).scalars().all()
        assert sorted(lc) == sorted(["new", "confirmed", "dismissed", "watchlist"])


def test_011_upgrade_adds_projects_gdpr_retention_column(live_db_010):
    """projects.gdpr_person_match_retention_days exists, NOT NULL, DEFAULT 90."""
    engine, env = live_db_010

    with engine.connect() as conn:
        row = conn.execute(sa.text(
            "SELECT column_name, is_nullable, column_default, data_type "
            "FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='projects' "
            "AND column_name='gdpr_person_match_retention_days'"
        )).first()
        assert row is not None, "gdpr_person_match_retention_days column not found"
        assert row.is_nullable == "NO"
        assert "90" in (row.column_default or ""), f"expected default 90, got {row.column_default}"
        assert row.data_type == "integer"


def test_011_brand_terms_unique_case_insensitive(live_db_010):
    """ux_brand_terms_project_type_value functional index rejects duplicate on
    (project_id, term_type, lower(value))."""
    engine, env = live_db_010

    with engine.connect() as conn:
        idx = conn.execute(sa.text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename='brand_terms' AND indexname='ux_brand_terms_project_type_value'"
        )).scalar_one_or_none()
        assert idx is not None, "ux_brand_terms_project_type_value index not found"
        assert "lower" in idx.lower(), f"expected lower() functional index, got {idx}"


def test_011_brand_matches_unique_dedup_constraint(live_db_010):
    """ux_brand_matches_dedup UNIQUE covers 4 cols: project_id, brand_term_id,
    matched_value, match_source."""
    engine, env = live_db_010

    with engine.connect() as conn:
        row = conn.execute(sa.text(
            "SELECT conname, contype FROM pg_constraint "
            "WHERE conname='ux_brand_matches_dedup'"
        )).first()
        assert row is not None, "ux_brand_matches_dedup constraint not found"
        assert row.contype == "u"

        idx = conn.execute(sa.text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename='brand_matches' AND indexname='ux_brand_matches_dedup'"
        )).scalar_one_or_none()
        assert idx is not None
        for col in ("project_id", "brand_term_id", "matched_value", "match_source"):
            assert col in idx, f"Column '{col}' missing from dedup index"


def test_011_brand_matches_indexes_exist(live_db_010):
    """ix_brand_matches_project_last_seen + partial ix_brand_matches_dismiss_until exist."""
    engine, env = live_db_010

    with engine.connect() as conn:
        idx1 = conn.execute(sa.text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename='brand_matches' AND indexname='ix_brand_matches_project_last_seen'"
        )).scalar_one_or_none()
        assert idx1 is not None, "ix_brand_matches_project_last_seen not found"
        assert "last_seen" in idx1.lower()

        idx2 = conn.execute(sa.text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename='brand_matches' AND indexname='ix_brand_matches_dismiss_until'"
        )).scalar_one_or_none()
        assert idx2 is not None, "ix_brand_matches_dismiss_until not found"
        assert "where" in idx2.lower(), f"expected partial index, got {idx2}"


def test_011_brand_matches_fk_cascade_to_brand_terms(live_db_010):
    """FK brand_matches.brand_term_id -> brand_terms.id has ON DELETE CASCADE."""
    engine, env = live_db_010

    with engine.connect() as conn:
        row = conn.execute(sa.text(
            "SELECT confdeltype FROM pg_constraint "
            "WHERE contype='f' AND conrelid='brand_matches'::regclass "
            "AND confrelid='brand_terms'::regclass"
        )).first()
        assert row is not None, "FK brand_matches -> brand_terms not found"
        assert row.confdeltype == "c", f"expected CASCADE ('c'), got {row.confdeltype}"


def test_011_downgrade_removes_all_brand_artifacts(live_db_010):
    """Downgrade to 010 drops tables, enums, and projects retention column."""
    engine, env = live_db_010
    _downgrade_010(env)

    with engine.connect() as conn:
        assert conn.execute(sa.text(
            "SELECT to_regclass('public.brand_terms')"
        )).scalar_one() is None
        assert conn.execute(sa.text(
            "SELECT to_regclass('public.brand_matches')"
        )).scalar_one() is None

        for enum_name in (
            "brand_term_type", "brand_term_mode", "brand_match_source",
            "brand_match_severity", "brand_match_lifecycle_status",
        ):
            gone = conn.execute(sa.text(
                "SELECT 1 FROM pg_type WHERE typname = :n"
            ), {"n": enum_name}).scalar_one_or_none()
            assert gone is None, f"{enum_name} enum survived downgrade"

        col = conn.execute(sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='projects' "
            "AND column_name='gdpr_person_match_retention_days'"
        )).first()
        assert col is None, "gdpr_person_match_retention_days column survived downgrade"

    # Re-upgrade for idempotency verification (leaves DB at 011)
    _upgrade_011(env)

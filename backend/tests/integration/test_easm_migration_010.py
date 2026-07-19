"""EASM migration 010 integration test - easm_scans + easm_findings + project_easm_credentials.

EASM-01, EASM-02, EASM-04, EASM-06, EASM-10. Activated by plan 11-01.

Pattern follows test_migration_008.py: spin up an intellibird-db:m1 container,
migrate to 009, then upgrade to 010 and assert the schema. Tests use a synchronous
SQLAlchemy engine (the alembic command is a subprocess; introspection is sync).

Tests verify:
- upgrade to 010 creates easm_scans, easm_findings, project_easm_credentials tables
- easm_scan_status enum type exists with all 6 values
- uq_easm_findings_dedup UNIQUE constraint has 3-column tuple (M-4)
- fk_events_easm_scan_id FK uses ON DELETE SET NULL / confdeltype='n' (L-4)
- downgrade drops all EASM artifacts + enum types
- upgrade → downgrade → upgrade is idempotent
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
def live_db_009():
    """Start intellibird-db:m1, migrate to 009, yield (engine, env).

    Leaves the DB at 009 - tests upgrade to 010 and can downgrade back.
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
        # Migrate to 009 (one step below 010)
        r = subprocess.run(
            ["uv", "run", "alembic", "upgrade", "009_projects_and_memberships"],
            cwd=str(BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            pytest.skip(f"alembic upgrade 009 failed: {r.stderr[:500]}")
        sync_url = (
            f"postgresql://{parsed.username}:{parsed.password}"
            f"@{parsed.host}:{parsed.port}/{parsed.database}"
        )
        engine = create_engine(sync_url, future=True)
        yield engine, env
        engine.dispose()


def _upgrade_010(engine, env) -> None:
    """Helper: run alembic upgrade 010_easm and assert success."""
    r = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "010_easm"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"alembic upgrade 010 failed:\n{r.stderr[:800]}"


def test_010_upgrade_creates_easm_scans_table(live_db_009):
    """After alembic upgrade 010, easm_scans table exists and easm_scan_status enum is present."""
    engine, env = live_db_009
    _upgrade_010(engine, env)

    with engine.connect() as conn:
        # Table exists - SELECT * LIMIT 0 is the cheapest probe
        conn.execute(sa.text("SELECT * FROM easm_scans LIMIT 0"))

        # easm_scan_status enum exists with all 6 values
        values = conn.execute(sa.text(
            "SELECT unnest(enum_range(NULL::easm_scan_status))::text ORDER BY 1"
        )).scalars().all()
        assert sorted(values) == sorted([
            "queued", "running", "finished", "failed", "cancelled", "orphaned"
        ])

        # easm_scan_mode enum exists
        modes = conn.execute(sa.text(
            "SELECT unnest(enum_range(NULL::easm_scan_mode))::text ORDER BY 1"
        )).scalars().all()
        assert sorted(modes) == ["active", "passive"]

        # easm_findings and project_easm_credentials tables exist
        conn.execute(sa.text("SELECT * FROM easm_findings LIMIT 0"))
        conn.execute(sa.text("SELECT * FROM project_easm_credentials LIMIT 0"))

        # projects.active_auth_confirmed_by column exists
        col = conn.execute(sa.text(
            "SELECT column_name, is_nullable FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='projects' "
            "AND column_name='active_auth_confirmed_by'"
        )).first()
        assert col is not None, "projects.active_auth_confirmed_by column not found"
        assert col.is_nullable == "YES", "active_auth_confirmed_by should be nullable"

        # events.easm_scan_id column exists
        ecol = conn.execute(sa.text(
            "SELECT column_name, is_nullable FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='events' "
            "AND column_name='easm_scan_id'"
        )).first()
        assert ecol is not None, "events.easm_scan_id column not found"
        assert ecol.is_nullable == "YES", "events.easm_scan_id should be nullable"


def test_010_upgrade_creates_unique_dedup_constraint(live_db_009):
    """uq_easm_findings_dedup covers exactly 3 columns: project_id, bbot_event_type, canonical_target (M-4)."""
    engine, env = live_db_009

    with engine.connect() as conn:
        # Find the constraint in pg_constraint
        row = conn.execute(sa.text(
            "SELECT conname, contype "
            "FROM pg_constraint "
            "WHERE conname = 'uq_easm_findings_dedup'"
        )).first()
        assert row is not None, "uq_easm_findings_dedup constraint not found"
        assert row.contype == "u", "uq_easm_findings_dedup should be a UNIQUE constraint"

        # Check the index definition lists the three columns
        idx = conn.execute(sa.text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename = 'easm_findings' AND indexname = 'uq_easm_findings_dedup'"
        )).scalar_one_or_none()
        assert idx is not None, "uq_easm_findings_dedup index not found in pg_indexes"
        for col in ("project_id", "bbot_event_type", "canonical_target"):
            assert col in idx, f"Column '{col}' missing from uq_easm_findings_dedup index definition"


def test_010_upgrade_adds_events_easm_scan_id_with_set_null(live_db_009):
    """fk_events_easm_scan_id FK has confdeltype='n' (ON DELETE SET NULL) - L-4 closure."""
    engine, env = live_db_009

    with engine.connect() as conn:
        row = conn.execute(sa.text(
            "SELECT confdeltype "
            "FROM pg_constraint "
            "WHERE conname = 'fk_events_easm_scan_id' AND contype = 'f'"
        )).first()
        assert row is not None, "fk_events_easm_scan_id foreign key not found"
        assert row.confdeltype == "n", (
            f"Expected confdeltype='n' (SET NULL) but got '{row.confdeltype}'; "
            "L-4 closure requires ON DELETE SET NULL on events.easm_scan_id"
        )


def test_010_downgrade_drops_all_easm_artifacts(live_db_009):
    """After downgrading to 009, all EASM tables and enum types are gone."""
    engine, env = live_db_009

    r = subprocess.run(
        ["uv", "run", "alembic", "downgrade", "009_projects_and_memberships"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"alembic downgrade 009 failed:\n{r.stderr[:800]}"

    with engine.connect() as conn:
        # easm_scans table should be gone
        table_gone = conn.execute(sa.text(
            "SELECT to_regclass('public.easm_scans')"
        )).scalar_one()
        assert table_gone is None, "easm_scans table still exists after downgrade"

        # easm_findings table should be gone
        findings_gone = conn.execute(sa.text(
            "SELECT to_regclass('public.easm_findings')"
        )).scalar_one()
        assert findings_gone is None, "easm_findings table still exists after downgrade"

        # easm_scan_status enum should be gone
        enum_gone = conn.execute(sa.text(
            "SELECT 1 FROM pg_type WHERE typname = 'easm_scan_status'"
        )).scalar_one_or_none()
        assert enum_gone is None, "easm_scan_status enum still exists after downgrade"

        # easm_severity enum should be gone
        sev_gone = conn.execute(sa.text(
            "SELECT 1 FROM pg_type WHERE typname = 'easm_severity'"
        )).scalar_one_or_none()
        assert sev_gone is None, "easm_severity enum still exists after downgrade"

        # events.easm_scan_id column should be gone
        col_gone = conn.execute(sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='events' "
            "AND column_name='easm_scan_id'"
        )).first()
        assert col_gone is None, "events.easm_scan_id column still exists after downgrade"

        # projects.active_auth_confirmed_by column should be gone
        auth_gone = conn.execute(sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='projects' "
            "AND column_name='active_auth_confirmed_by'"
        )).first()
        assert auth_gone is None, "projects.active_auth_confirmed_by column still exists after downgrade"


def test_010_upgrade_idempotent_across_runs(live_db_009):
    """upgrade -> downgrade -> upgrade succeeds (idempotent DO-block for enums)."""
    engine, env = live_db_009

    # Already at 009 from previous test - upgrade to 010 again
    r = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "010_easm"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"alembic re-upgrade 010 failed:\n{r.stderr[:800]}"

    with engine.connect() as conn:
        # Verify tables are back
        exists = conn.execute(sa.text(
            "SELECT to_regclass('public.easm_scans')"
        )).scalar_one()
        assert exists == "easm_scans", "easm_scans table missing after re-upgrade"

        # Verify easm_findings dedup constraint is back
        row = conn.execute(sa.text(
            "SELECT conname FROM pg_constraint WHERE conname = 'uq_easm_findings_dedup'"
        )).first()
        assert row is not None, "uq_easm_findings_dedup constraint missing after re-upgrade"

        # Verify SET NULL FK is back
        fk_row = conn.execute(sa.text(
            "SELECT confdeltype FROM pg_constraint "
            "WHERE conname = 'fk_events_easm_scan_id' AND contype = 'f'"
        )).first()
        assert fk_row is not None, "fk_events_easm_scan_id missing after re-upgrade"
        assert fk_row.confdeltype == "n", "fk_events_easm_scan_id should be SET NULL after re-upgrade"

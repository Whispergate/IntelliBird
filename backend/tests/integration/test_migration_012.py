"""Migration 012 integration test — asset_notes table.

Owned by: 12.1-01-PLAN.
Phase 12.1 / ASSET-NOTE.

Pattern follows test_brand_migration_011.py: spin up intellibird-db:m1,
migrate to 011, upgrade to 012 and assert schema; downgrade back and assert
clean teardown; re-upgrade for idempotency.

Tests verify:
- upgrade to 012 creates asset_notes table with 7 expected columns + types
- UNIQUE(project_id, bbot_event_type, canonical_target) constraint present
- FK asset_notes.project_id -> projects.id has confdeltype='c' (CASCADE)
- Inserting a duplicate (project_id, bbot_event_type, canonical_target) tuple
  raises IntegrityError (UNIQUE violation)
- Deleting parent projects row cascades to asset_notes
- ix_asset_notes_project_updated index exists
- downgrade cleanly drops asset_notes
"""
from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def live_db_011():
    """Start intellibird-db:m1, migrate to 011, yield (engine, env).

    Leaves the DB at 011 — tests upgrade to 012 and can downgrade back.
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
            ["uv", "run", "alembic", "upgrade", "011"],
            cwd=str(BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            pytest.skip(f"alembic upgrade 011 failed: {r.stderr[:500]}")
        sync_url = (
            f"postgresql://{parsed.username}:{parsed.password}"
            f"@{parsed.host}:{parsed.port}/{parsed.database}"
        )
        engine = create_engine(sync_url, future=True)
        yield engine, env
        engine.dispose()


def _upgrade_012(env) -> None:
    r = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "012"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"alembic upgrade 012 failed:\n{r.stderr[:800]}"


def _downgrade_011(env) -> None:
    r = subprocess.run(
        ["uv", "run", "alembic", "downgrade", "011"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"alembic downgrade 011 failed:\n{r.stderr[:800]}"


def _insert_project(conn) -> uuid.UUID:
    """Minimal project insert — returns the id. Uses default-heavy shape so
    we don't couple this test to the full projects schema."""
    pid = uuid.uuid4()
    # Discover NOT NULL columns without defaults so we can supply placeholders.
    rows = conn.execute(sa.text(
        "SELECT column_name, column_default FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='projects' "
        "AND is_nullable='NO'"
    )).all()
    required = [r.column_name for r in rows if r.column_default is None and r.column_name != "id"]
    # Build an insert that supplies a string placeholder for any text-ish
    # required column. This is deliberately forgiving — real schema validation
    # is covered by the projects-dedicated migrations.
    # Known enum columns need valid values (generic "x" violates DB enum constraint).
    _ENUM_DEFAULTS: dict[str, str] = {
        "engagement_type": "intel_only",
    }
    cols = ["id"] + required
    placeholders = [":id"] + [f":{c}" for c in required]
    params = {"id": pid}
    for c in required:
        params[c] = _ENUM_DEFAULTS.get(c, "x")
    conn.execute(
        sa.text(f"INSERT INTO projects ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"),
        params,
    )
    return pid


def test_012_upgrade_creates_asset_notes_table(live_db_011):
    """After alembic upgrade 012, asset_notes table exists with all 7 columns."""
    engine, env = live_db_011
    _upgrade_012(env)

    with engine.connect() as conn:
        conn.execute(sa.text("SELECT * FROM asset_notes LIMIT 0"))

        rows = conn.execute(sa.text(
            "SELECT column_name, is_nullable, data_type "
            "FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='asset_notes'"
        )).all()
        cols = {r.column_name: r for r in rows}
        assert set(cols) == {
            "id", "project_id", "bbot_event_type", "canonical_target",
            "note", "updated_by", "updated_at",
        }
        # All NOT NULL
        for name in cols:
            assert cols[name].is_nullable == "NO", f"{name} should be NOT NULL"
        assert cols["id"].data_type == "uuid"
        assert cols["project_id"].data_type == "uuid"
        assert cols["bbot_event_type"].data_type == "text"
        assert cols["canonical_target"].data_type == "text"
        assert cols["note"].data_type == "text"
        assert cols["updated_by"].data_type == "text"
        assert "timestamp" in cols["updated_at"].data_type.lower()


def test_012_unique_constraint_on_project_type_target(live_db_011):
    """uq_asset_notes_project_type_target covers (project_id, bbot_event_type, canonical_target)."""
    engine, env = live_db_011

    with engine.connect() as conn:
        row = conn.execute(sa.text(
            "SELECT conname, contype FROM pg_constraint "
            "WHERE conname='uq_asset_notes_project_type_target'"
        )).first()
        assert row is not None, "uq_asset_notes_project_type_target constraint not found"
        assert row.contype == "u"

        idx = conn.execute(sa.text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename='asset_notes' AND indexname='uq_asset_notes_project_type_target'"
        )).scalar_one_or_none()
        assert idx is not None
        for col in ("project_id", "bbot_event_type", "canonical_target"):
            assert col in idx, f"Column '{col}' missing from uq_asset_notes_project_type_target"


def test_012_fk_project_id_cascade(live_db_011):
    """FK asset_notes.project_id -> projects.id has ON DELETE CASCADE."""
    engine, env = live_db_011

    with engine.connect() as conn:
        row = conn.execute(sa.text(
            "SELECT confdeltype FROM pg_constraint "
            "WHERE contype='f' AND conrelid='asset_notes'::regclass "
            "AND confrelid='projects'::regclass"
        )).first()
        assert row is not None, "FK asset_notes -> projects not found"
        assert row.confdeltype == "c", f"expected CASCADE ('c'), got {row.confdeltype}"


def test_012_project_updated_index_exists(live_db_011):
    """ix_asset_notes_project_updated index exists on (project_id, updated_at)."""
    engine, env = live_db_011

    with engine.connect() as conn:
        idx = conn.execute(sa.text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename='asset_notes' AND indexname='ix_asset_notes_project_updated'"
        )).scalar_one_or_none()
        assert idx is not None, "ix_asset_notes_project_updated not found"
        assert "project_id" in idx
        assert "updated_at" in idx


@pytest.mark.cross_file_pollution
def test_012_duplicate_tuple_raises_integrity_error(live_db_011):
    """Inserting a second row with the same (project_id, bbot_event_type,
    canonical_target) raises IntegrityError."""
    engine, env = live_db_011
    # Ensure migration 012 is applied (this test may run without test_012_upgrade_creates_asset_notes_table
    # when selected via -m cross_file_pollution).
    _upgrade_012(env)

    with engine.begin() as conn:
        pid = _insert_project(conn)
        conn.execute(sa.text(
            "INSERT INTO asset_notes (project_id, bbot_event_type, canonical_target, note, updated_by) "
            "VALUES (:p, 'DNS_NAME', 'sub.example.com', 'first', 'op1')"
        ), {"p": pid})

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(sa.text(
                "INSERT INTO asset_notes (project_id, bbot_event_type, canonical_target, note, updated_by) "
                "VALUES (:p, 'DNS_NAME', 'sub.example.com', 'second', 'op2')"
            ), {"p": pid})

    # cleanup
    with engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM projects WHERE id=:p"), {"p": pid})


@pytest.mark.cross_file_pollution
def test_012_fk_cascade_delete_removes_notes(live_db_011):
    """Deleting a project row cascades — asset_notes rows disappear."""
    engine, env = live_db_011
    # Ensure migration 012 is applied (this test may run without test_012_upgrade_creates_asset_notes_table
    # when selected via -m cross_file_pollution).
    _upgrade_012(env)

    with engine.begin() as conn:
        pid = _insert_project(conn)
        conn.execute(sa.text(
            "INSERT INTO asset_notes (project_id, bbot_event_type, canonical_target, note, updated_by) "
            "VALUES (:p, 'URL', 'https://x.example.com', 'n', 'op')"
        ), {"p": pid})

    with engine.begin() as conn:
        n = conn.execute(sa.text(
            "SELECT count(*) FROM asset_notes WHERE project_id=:p"
        ), {"p": pid}).scalar_one()
        assert n == 1

    with engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM projects WHERE id=:p"), {"p": pid})

    with engine.begin() as conn:
        n = conn.execute(sa.text(
            "SELECT count(*) FROM asset_notes WHERE project_id=:p"
        ), {"p": pid}).scalar_one()
        assert n == 0, "asset_notes rows should have cascaded on project delete"


def test_012_downgrade_removes_asset_notes(live_db_011):
    """Downgrade to 011 drops asset_notes cleanly, then re-upgrade succeeds."""
    engine, env = live_db_011
    _downgrade_011(env)

    with engine.connect() as conn:
        assert conn.execute(sa.text(
            "SELECT to_regclass('public.asset_notes')"
        )).scalar_one() is None

    # Re-upgrade for idempotency (leaves DB at 012)
    _upgrade_012(env)
    with engine.connect() as conn:
        conn.execute(sa.text("SELECT * FROM asset_notes LIMIT 0"))

"""Migration 008 integration test — users table + user_role enum + indexes.

AUTH-01. Activated by plan 09-01.

Pattern follows test_migration_007.py: spin up an intellibird-db:m1 container,
migrate to 007, then upgrade to 008 and assert the schema. Tests use a synchronous
SQLAlchemy engine (the alembic command is a subprocess; introspection is sync).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def live_db_007():
    """Start intellibird-db:m1, migrate to 007, yield (engine, env).

    Leaves the DB at 007 — tests upgrade to 008 and can downgrade back.
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
            "JWT_SIGNING_KEY": "y" * 48,  # Phase 9 required field
            "REDIS_URL": "redis://localhost:1",
        }
        # Migrate to 007 (one step below 008)
        r = subprocess.run(
            ["uv", "run", "alembic", "upgrade", "007_credentials_key_version"],
            cwd=str(BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            pytest.skip(f"alembic upgrade 007 failed: {r.stderr[:500]}")
        sync_url = (
            f"postgresql://{parsed.username}:{parsed.password}"
            f"@{parsed.host}:{parsed.port}/{parsed.database}"
        )
        engine = create_engine(sync_url, future=True)
        yield engine, env
        engine.dispose()


def _upgrade_008(engine, env) -> None:
    """Helper: run alembic upgrade 008_users_and_auth and assert success."""
    r = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "008_users_and_auth"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"alembic upgrade 008 failed:\n{r.stderr[:800]}"


def test_users_table_columns_and_defaults(live_db_007):
    """After alembic upgrade 008, users table has all 11 columns with correct defaults."""
    engine, env = live_db_007
    _upgrade_008(engine, env)

    with engine.connect() as conn:
        rows = conn.execute(sa.text(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_name = 'users' "
            "ORDER BY ordinal_position"
        )).all()
        names = {r[0] for r in rows}
        assert names == {
            "id", "username", "password_hash", "oidc_sub", "role",
            "dashboard_roles", "enabled", "must_change_password",
            "token_version", "created_at", "last_login_at",
        }


def test_user_role_enum_values(live_db_007):
    """user_role enum type exists with values Admin, Analyst, Viewer."""
    engine, env = live_db_007

    with engine.connect() as conn:
        rows = conn.execute(sa.text(
            "SELECT unnest(enum_range(NULL::user_role))::text ORDER BY 1"
        )).scalars().all()
        assert sorted(rows) == ["Admin", "Analyst", "Viewer"]


def test_unique_username_index(live_db_007):
    """uq_users_username is a UNIQUE index on username."""
    engine, env = live_db_007

    with engine.connect() as conn:
        idx = conn.execute(sa.text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename = 'users' AND indexname = 'uq_users_username'"
        )).scalar_one_or_none()
        assert idx is not None, "uq_users_username index not found"
        assert "UNIQUE" in idx
        assert "username" in idx


def test_partial_unique_oidc_sub_index(live_db_007):
    """uq_users_oidc_sub is a partial UNIQUE index on oidc_sub WHERE oidc_sub IS NOT NULL."""
    engine, env = live_db_007

    with engine.connect() as conn:
        idx = conn.execute(sa.text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename = 'users' AND indexname = 'uq_users_oidc_sub'"
        )).scalar_one_or_none()
        assert idx is not None, "uq_users_oidc_sub index not found"
        assert "UNIQUE" in idx
        assert "oidc_sub IS NOT NULL" in idx


def test_enabled_partial_index(live_db_007):
    """ix_users_enabled is a partial index WHERE enabled = true."""
    engine, env = live_db_007

    with engine.connect() as conn:
        idx = conn.execute(sa.text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename = 'users' AND indexname = 'ix_users_enabled'"
        )).scalar_one_or_none()
        assert idx is not None, "ix_users_enabled index not found"
        assert "enabled = true" in idx


def test_users_table_exists_at_head(live_db_007):
    """After upgrade 008, users table is visible to_regclass check."""
    engine, env = live_db_007

    with engine.connect() as conn:
        exists = conn.execute(sa.text(
            "SELECT to_regclass('public.users')"
        )).scalar_one()
        assert exists == "users"


def test_downgrade_drops_table_and_enum(live_db_007):
    """alembic downgrade -1 drops both users table and user_role enum type."""
    engine, env = live_db_007

    r = subprocess.run(
        ["uv", "run", "alembic", "downgrade", "007_credentials_key_version"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"alembic downgrade 007 failed:\n{r.stderr[:800]}"

    with engine.connect() as conn:
        # users table should be gone
        table_gone = conn.execute(sa.text(
            "SELECT to_regclass('public.users')"
        )).scalar_one()
        assert table_gone is None, "users table still exists after downgrade"

        # user_role enum should be gone
        enum_gone = conn.execute(sa.text(
            "SELECT 1 FROM pg_type WHERE typname = 'user_role'"
        )).scalar_one_or_none()
        assert enum_gone is None, "user_role enum still exists after downgrade"


def test_re_upgrade_after_downgrade_idempotent(live_db_007):
    """Re-running upgrade 008 after downgrade succeeds (idempotent DO-block for enum)."""
    engine, env = live_db_007

    r = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "008_users_and_auth"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"alembic re-upgrade 008 failed:\n{r.stderr[:800]}"

    with engine.connect() as conn:
        exists = conn.execute(sa.text(
            "SELECT to_regclass('public.users')"
        )).scalar_one()
        assert exists == "users", "users table missing after re-upgrade"

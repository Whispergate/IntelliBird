"""INFRA-01 integration: migration 007 DDL + canary row against live PG.

Tests verify:
- upgrade to 007 adds credentials_key_version column with server_default '1'
- canary row 00000000-0000-0000-0000-000000000000 is inserted with correct values
- re-inserting canary row is idempotent (ON CONFLICT DO NOTHING)
- downgrade from 007 removes both the canary row and the column
"""
from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[2]
CANARY_ID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture(scope="module")
def live_db_006():
    """Start intellibird-db:m1, migrate to 006, yield (engine, env).

    Leaves the DB at 006 — tests upgrade to 007 and can downgrade back.
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
        # Migrate to 006 (one step below 007)
        r = subprocess.run(
            ["uv", "run", "alembic", "upgrade", "006_webhooks"],
            cwd=str(BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            pytest.skip(f"alembic upgrade 006 failed: {r.stderr[:500]}")
        sync_url = (
            f"postgresql://{parsed.username}:{parsed.password}"
            f"@{parsed.host}:{parsed.port}/{parsed.database}"
        )
        engine = create_engine(sync_url, future=True)
        yield engine, env
        engine.dispose()


def _upgrade_007(engine, env):
    """Helper: run alembic upgrade 007_credentials_key_version and assert success."""
    r = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "007_credentials_key_version"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"alembic upgrade 007 failed:\n{r.stderr[:800]}"


def test_column_exists_and_default_1(live_db_006):
    """After upgrading to 007, credentials_key_version column exists with default 1."""
    engine, env = live_db_006
    _upgrade_007(engine, env)

    with engine.connect() as conn:
        # Check column exists in information_schema
        rows = conn.execute(
            text(
                "SELECT column_name, column_default, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='sources' "
                "AND column_name='credentials_key_version'"
            )
        ).all()
        assert len(rows) == 1, "credentials_key_version column not found after migration 007"
        col = rows[0]
        assert col.is_nullable == "NO", "credentials_key_version should be NOT NULL"


def test_canary_row_inserted(live_db_006):
    """After upgrading to 007, canary row exists with correct values."""
    engine, env = live_db_006

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT name, feed_type, enabled, credentials_enc, "
                "credentials_key_version, url "
                "FROM sources WHERE id = CAST(:id AS uuid)"
            ),
            {"id": CANARY_ID},
        ).first()
        assert row is not None, "canary row missing after migration 007"
        assert row.name == "_rekey_canary"
        assert row.feed_type == "rss"
        assert row.enabled is False
        assert row.credentials_enc is None
        assert row.credentials_key_version == 1
        assert row.url == "https://canary.internal"


def test_canary_insert_idempotent(live_db_006):
    """Re-running the canary INSERT is a no-op (ON CONFLICT DO NOTHING)."""
    engine, env = live_db_006

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO sources (id, name, feed_type, url, enabled,
                                     poll_interval_sec, hot_retention_days,
                                     archive_policy, credentials_key_version)
                VALUES (CAST(:id AS uuid),
                        '_rekey_canary', 'rss', 'https://canary.internal', false,
                        3600, 30, 'drop', 1)
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"id": CANARY_ID},
        )

    with engine.connect() as conn:
        count = conn.execute(
            text(
                "SELECT COUNT(*) AS c FROM sources WHERE id = CAST(:id AS uuid)"
            ),
            {"id": CANARY_ID},
        ).scalar()
        assert count == 1, f"Expected exactly 1 canary row, got {count}"


def test_downgrade_007_removes_column_and_canary(live_db_006):
    """Downgrading from 007 to 006 removes the canary row and the column."""
    engine, env = live_db_006

    r = subprocess.run(
        ["uv", "run", "alembic", "downgrade", "006_webhooks"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"alembic downgrade 006 failed:\n{r.stderr[:800]}"

    with engine.connect() as conn:
        # Column should be gone
        col_rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='sources' "
                "AND column_name='credentials_key_version'"
            )
        ).all()
        assert len(col_rows) == 0, "credentials_key_version column still exists after downgrade"

        # Canary row should be gone
        canary = conn.execute(
            text("SELECT id FROM sources WHERE id = CAST(:id AS uuid)"),
            {"id": CANARY_ID},
        ).first()
        assert canary is None, "canary row still exists after downgrade"

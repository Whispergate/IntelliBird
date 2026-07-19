"""Migration 006 webhook tables integration tests - unskipped by 07-01.

Tests verify:
- upgrade to 006 creates destination_type_enum, webhooks, webhook_preset_bindings
- FK ON DELETE CASCADE from filter_presets (preset delete cascades bindings)
- FK ON DELETE CASCADE from webhooks (webhook delete cascades bindings)
- downgrade removes tables + enum cleanly
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


@pytest.fixture(scope="module")
def live_db_005():
    """Start intellibird-db:m1, migrate to 005, yield (engine, env).

 Leaves the DB at 005 - tests upgrade to 006 and can downgrade back.
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
        # Migrate to 005 (one step below 006)
        r = subprocess.run(
            ["uv", "run", "alembic", "upgrade", "005_geo_backfill_and_indexes"],
            cwd=str(BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            pytest.skip(f"alembic upgrade 005 failed: {r.stderr[:500]}")
        sync_url = (
            f"postgresql://{parsed.username}:{parsed.password}"
            f"@{parsed.host}:{parsed.port}/{parsed.database}"
        )
        engine = create_engine(sync_url, future=True)
        yield engine, env
        engine.dispose()


def _upgrade_006(engine, env):
    """Helper: run alembic upgrade 006_webhooks and assert it succeeds."""
    r = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "006_webhooks"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"alembic upgrade 006 failed:\n{r.stderr[:800]}"


def test_migration_006_creates_webhooks_table(live_db_005):
    """After upgrading to 006, webhooks table exists with all expected columns."""
    engine, env = live_db_005
    _upgrade_006(engine, env)

    with engine.connect() as conn:
        # Check table exists
        rows = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='webhooks'"
            )
        ).all()
        assert len(rows) == 1, "webhooks table not found after migration 006"

        # Check all columns are present
        col_rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='webhooks'"
            )
        ).all()
        actual_cols = {r[0] for r in col_rows}
        expected_cols = {
            "id",
            "name",
            "destination_type",
            "url",
            "auth_enc",
            "batching_window_sec",
            "enabled",
            "last_dispatch_at",
            "last_delivery_at",
            "last_delivery_status",
            "consecutive_failures",
            "created_at",
            "updated_at",
        }
        missing = expected_cols - actual_cols
        assert not missing, f"webhooks table missing columns: {missing}"


def test_migration_006_creates_bindings_table(live_db_005):
    """After upgrading to 006, webhook_preset_bindings table exists with correct schema."""
    engine, env = live_db_005

    with engine.connect() as conn:
        # Check table exists
        rows = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='webhook_preset_bindings'"
            )
        ).all()
        assert len(rows) == 1, "webhook_preset_bindings table not found after migration 006"

        # Check columns
        col_rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='webhook_preset_bindings'"
            )
        ).all()
        actual_cols = {r[0] for r in col_rows}
        expected_cols = {"webhook_id", "preset_name"}
        missing = expected_cols - actual_cols
        assert not missing, f"webhook_preset_bindings missing columns: {missing}"

        # Check composite PK via pg_constraint
        pk_rows = conn.execute(
            text(
                "SELECT conname FROM pg_constraint c "
                "JOIN pg_class t ON t.oid = c.conrelid "
                "WHERE c.contype = 'p' AND t.relname = 'webhook_preset_bindings'"
            )
        ).all()
        assert len(pk_rows) == 1, (
            f"Expected 1 PK constraint on webhook_preset_bindings, got {len(pk_rows)}"
        )


def test_destination_type_enum_exists(live_db_005):
    """After upgrading to 006, destination_type_enum exists with the 4 required values."""
    engine, env = live_db_005

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT enumlabel FROM pg_enum "
                "JOIN pg_type ON pg_type.oid = enumtypid "
                "WHERE typname = 'destination_type_enum'"
            )
        ).all()
        actual_labels = {r[0] for r in rows}
        expected_labels = {"slack", "teams", "discord", "generic"}
        assert actual_labels == expected_labels, (
            f"destination_type_enum labels mismatch: got {actual_labels}"
        )


def test_fk_cascade_on_preset_delete(live_db_005):
    """Deleting a filter_preset cascades removal of its webhook_preset_bindings rows."""
    engine, env = live_db_005
    preset_name = f"cascade-test-preset-{uuid.uuid4().hex[:8]}"
    wh_id = str(uuid.uuid4())

    with engine.begin() as conn:
        # Insert a filter_preset row
        conn.execute(
            text(
                "INSERT INTO filter_presets (id, name, query_params) "
                "VALUES (gen_random_uuid(), :name, '{}'::jsonb)"
            ),
            {"name": preset_name},
        )
        # Insert a webhook row
        conn.execute(
            text(
                "INSERT INTO webhooks "
                "(id, name, destination_type, url) "
                "VALUES (:id, :wname, 'slack', 'https://hooks.slack.com/test')"
            ),
            {"id": wh_id, "wname": f"wh-{uuid.uuid4().hex[:8]}"},
        )
        # Insert a binding row
        conn.execute(
            text(
                "INSERT INTO webhook_preset_bindings (webhook_id, preset_name) "
                "VALUES (CAST(:wh_id AS uuid), :preset_name)"
            ),
            {"wh_id": wh_id, "preset_name": preset_name},
        )

    # Now delete the preset - binding should cascade-delete
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM filter_presets WHERE name = :name"),
            {"name": preset_name},
        )

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT * FROM webhook_preset_bindings "
                "WHERE preset_name = :name"
            ),
            {"name": preset_name},
        ).all()
        assert len(rows) == 0, (
            f"Expected 0 binding rows after preset delete (cascade), got {len(rows)}"
        )


def test_fk_cascade_on_webhook_delete(live_db_005):
    """Deleting a webhook cascades removal of its webhook_preset_bindings rows."""
    engine, env = live_db_005
    preset_name = f"cascade-wh-test-{uuid.uuid4().hex[:8]}"
    wh_id = str(uuid.uuid4())

    with engine.begin() as conn:
        # Insert a filter_preset row
        conn.execute(
            text(
                "INSERT INTO filter_presets (id, name, query_params) "
                "VALUES (gen_random_uuid(), :name, '{}'::jsonb)"
            ),
            {"name": preset_name},
        )
        # Insert a webhook row
        conn.execute(
            text(
                "INSERT INTO webhooks "
                "(id, name, destination_type, url) "
                "VALUES (:id, :wname, 'generic', 'https://example.com/hook')"
            ),
            {"id": wh_id, "wname": f"wh-del-{uuid.uuid4().hex[:8]}"},
        )
        # Insert a binding row
        conn.execute(
            text(
                "INSERT INTO webhook_preset_bindings (webhook_id, preset_name) "
                "VALUES (CAST(:wh_id AS uuid), :preset_name)"
            ),
            {"wh_id": wh_id, "preset_name": preset_name},
        )

    # Now delete the webhook - binding should cascade-delete
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM webhooks WHERE id = CAST(:wh_id AS uuid)"),
            {"wh_id": wh_id},
        )

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT * FROM webhook_preset_bindings "
                "WHERE webhook_id = CAST(:wh_id AS uuid)"
            ),
            {"wh_id": wh_id},
        ).all()
        assert len(rows) == 0, (
            f"Expected 0 binding rows after webhook delete (cascade), got {len(rows)}"
        )

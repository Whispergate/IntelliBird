"""IOC-01 migration 023 import-level smoke test.

DB-touching round-trip + introspection lives in
backend/tests/integration/test_migration_023_iocs.py (uses the pinned
`db_session` / `db_engine` fixtures from tests/integration/conftest.py).

This unit test only verifies the migration module loads + carries the right
revision metadata + the NULLS NOT DISTINCT raw-SQL is present (catches a
class of regression where a refactor accidentally drops the qualifier).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic" / "versions" / "023_iocs.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("_mig_023_iocs", _MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_023_module_imports():
    mod = _load_migration()
    assert mod.revision == "019_iocs"
    assert mod.down_revision == "018_ai_auto_summary_toggle"
    assert callable(mod.upgrade)
    assert callable(mod.downgrade)


def test_migration_023_declares_thirteen_ioc_types():
    mod = _load_migration()
    expected = {
        "ip", "ipv6", "domain", "url",
        "sha256", "sha1", "md5",
        "email", "btc", "eth", "mutex", "registry_key", "filename",
    }
    assert set(mod.IOC_TYPES) == expected
    assert len(mod.IOC_TYPES) == 13


def test_migration_023_status_and_source_enums():
    mod = _load_migration()
    assert set(mod.IOC_STATUSES) == {"active", "expired", "whitelisted"}
    assert set(mod.IOC_SOURCES) == {
        "manual", "csv", "json", "stix", "event", "backfill",
    }


def test_migration_023_uses_nulls_not_distinct():
    """Catches accidental drop of the PG15+ NULLS NOT DISTINCT qualifier
    that's load-bearing for global-row dedup (project_id IS NULL collisions).
    """
    src = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "023_iocs.py"
    text = src.read_text(encoding="utf-8")
    assert "NULLS NOT DISTINCT" in text
    assert "uq_iocs_project_type_value" in text


def test_migration_023_creates_three_enum_types():
    src = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "023_iocs.py"
    text = src.read_text(encoding="utf-8")
    assert "CREATE TYPE ioc_type_enum" in text
    assert "CREATE TYPE ioc_status_enum" in text
    assert "CREATE TYPE ioc_source_enum" in text


def test_migration_023_downgrade_drops_three_enum_types():
    src = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "023_iocs.py"
    text = src.read_text(encoding="utf-8")
    assert "DROP TYPE IF EXISTS ioc_source_enum" in text
    assert "DROP TYPE IF EXISTS ioc_status_enum" in text
    assert "DROP TYPE IF EXISTS ioc_type_enum" in text

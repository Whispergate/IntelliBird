"""Unit tests for migration 003 (archive_policy enum + silent_failure_count).

All tests run offline — no live database required. Monkeypatching alembic.op
is used to inspect the exact sequence of DDL operations emitted by upgrade()
and downgrade().
"""
from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock, call, patch

import sqlalchemy as sa
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_migration():
    """Import the migration module, bypassing any cached version."""
    mod_name = "alembic.versions.v003_archive_policy"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location(
        mod_name,
        pathlib.Path(__file__).parents[3]
        / "alembic" / "versions" / "003_archive_policy.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Test 1 — revision IDs
# ---------------------------------------------------------------------------

def test_migration_revision_ids():
    mod = _load_migration()
    assert mod.revision == "0003_archive_policy"
    assert mod.down_revision == "0002_dedup_and_cve_details"


# ---------------------------------------------------------------------------
# Test 2 — upgrade creates enum idempotently
# ---------------------------------------------------------------------------

def test_upgrade_creates_enum_idempotently():
    mod = _load_migration()
    execute_calls = []

    with patch("alembic.op.execute", side_effect=lambda s: execute_calls.append(s)), \
         patch("alembic.op.add_column"):
        mod.upgrade()

    assert len(execute_calls) >= 1, "op.execute should be called at least once"
    combined = " ".join(str(c) for c in execute_calls)
    assert "CREATE TYPE archive_policy_enum" in combined
    assert "EXCEPTION WHEN duplicate_object THEN NULL" in combined


# ---------------------------------------------------------------------------
# Test 3 — upgrade adds archive_policy column
# ---------------------------------------------------------------------------

def test_upgrade_adds_archive_policy_column():
    mod = _load_migration()
    add_column_calls = []

    def capture_add_column(table, column):
        add_column_calls.append((table, column))

    with patch("alembic.op.execute"), \
         patch("alembic.op.add_column", side_effect=capture_add_column):
        mod.upgrade()

    # Find the archive_policy call
    archive_call = next(
        (tbl, col) for tbl, col in add_column_calls if col.name == "archive_policy"
    )
    assert archive_call is not None, "add_column for archive_policy not found"
    tbl, col = archive_call
    assert tbl == "sources"
    assert col.nullable is False
    # server_default stores the arg as a string or ColumnDefault
    sd = col.server_default
    sd_arg = sd.arg if hasattr(sd, "arg") else str(sd)
    assert sd_arg == "drop"
    # Enum values
    assert isinstance(col.type, sa.Enum)
    assert set(col.type.enums) == {"keep", "drop", "move-to-cold"}


# ---------------------------------------------------------------------------
# Test 4 — upgrade adds silent_failure_count column
# ---------------------------------------------------------------------------

def test_upgrade_adds_silent_failure_count_column():
    mod = _load_migration()
    add_column_calls = []

    def capture_add_column(table, column):
        add_column_calls.append((table, column))

    with patch("alembic.op.execute"), \
         patch("alembic.op.add_column", side_effect=capture_add_column):
        mod.upgrade()

    silent_call = next(
        (tbl, col) for tbl, col in add_column_calls if col.name == "silent_failure_count"
    )
    assert silent_call is not None, "add_column for silent_failure_count not found"
    tbl, col = silent_call
    assert tbl == "sources"
    assert col.nullable is False
    assert isinstance(col.type, sa.Integer)
    sd = col.server_default
    sd_arg = sd.arg if hasattr(sd, "arg") else str(sd)
    assert sd_arg == "0"


# ---------------------------------------------------------------------------
# Test 5 — downgrade drops columns in reverse order then drops enum type
# ---------------------------------------------------------------------------

def test_downgrade_drops_columns_in_reverse_order():
    mod = _load_migration()
    operations = []

    def capture_drop_column(table, column):
        operations.append(("drop_column", table, column))

    def capture_execute(sql):
        operations.append(("execute", str(sql)))

    with patch("alembic.op.drop_column", side_effect=capture_drop_column), \
         patch("alembic.op.execute", side_effect=capture_execute):
        mod.downgrade()

    drop_ops = [op for op in operations if op[0] == "drop_column"]
    exec_ops = [op for op in operations if op[0] == "execute"]

    assert len(drop_ops) == 2, f"Expected 2 drop_column calls, got {len(drop_ops)}"
    assert drop_ops[0] == ("drop_column", "sources", "silent_failure_count"), \
        "silent_failure_count must be dropped first"
    assert drop_ops[1] == ("drop_column", "sources", "archive_policy"), \
        "archive_policy must be dropped second"

    assert len(exec_ops) >= 1
    assert any("DROP TYPE IF EXISTS archive_policy_enum" in op[1] for op in exec_ops), \
        "Expected DROP TYPE IF EXISTS archive_policy_enum in execute calls"

    # Verify drop_columns precede the DROP TYPE execute
    last_drop_idx = max(operations.index(op) for op in drop_ops)
    type_drop_idx = next(
        i for i, op in enumerate(operations)
        if op[0] == "execute" and "DROP TYPE IF EXISTS archive_policy_enum" in op[1]
    )
    assert last_drop_idx < type_drop_idx, \
        "Both columns must be dropped before the enum type is dropped"


# ---------------------------------------------------------------------------
# Test 6 — Source ORM exposes archive_policy column
# ---------------------------------------------------------------------------

def test_source_orm_exposes_archive_policy_column():
    from app.models.sources import Source

    assert hasattr(Source, "archive_policy"), "Source.archive_policy attribute missing"
    col = Source.__table__.c["archive_policy"]
    assert col.nullable is False
    sd = col.server_default
    sd_arg = sd.arg if hasattr(sd, "arg") else str(sd)
    assert sd_arg == "drop"


# ---------------------------------------------------------------------------
# Test 7 — Source ORM exposes silent_failure_count column
# ---------------------------------------------------------------------------

def test_source_orm_exposes_silent_failure_count_column():
    from app.models.sources import Source

    assert hasattr(Source, "silent_failure_count"), "Source.silent_failure_count attribute missing"
    col = Source.__table__.c["silent_failure_count"]
    assert col.nullable is False
    sd = col.server_default
    sd_arg = sd.arg if hasattr(sd, "arg") else str(sd)
    assert sd_arg == "0"

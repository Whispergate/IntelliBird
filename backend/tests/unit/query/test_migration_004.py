"""Tests for Alembic migration 004 — FIL-04 (filter_presets), FIL-05 (search_tsv + GIN).

Uses importlib.util to load the migration file by path so the leading-digit
filename (004_fts_and_presets.py) does not break Python import.
"""
from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

# ---------------------------------------------------------------------------
# Loader helper
# ---------------------------------------------------------------------------

_MIG_PATH = (
    Path(__file__).resolve().parents[3]
    / "alembic"
    / "versions"
    / "004_fts_and_presets.py"
)


def _load_migration():
    """Load 004_fts_and_presets as a module object."""
    spec = importlib.util.spec_from_file_location("mig_004", _MIG_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Revision chain
# ---------------------------------------------------------------------------


def test_revision_id() -> None:
    """revision string is 004_fts_and_presets."""
    mod = _load_migration()
    assert mod.revision == "004_fts_and_presets"


def test_down_revision_chains_to_003() -> None:
    """down_revision must point at 0003_archive_policy (leading zero matches existing chain)."""
    mod = _load_migration()
    assert mod.down_revision == "0003_archive_policy"


# ---------------------------------------------------------------------------
# upgrade() DDL shape
# ---------------------------------------------------------------------------


def test_upgrade_creates_search_tsv_column() -> None:
    """upgrade() must emit the GENERATED ALWAYS AS STORED tsvector column."""
    mod = _load_migration()
    src = inspect.getsource(mod.upgrade)
    assert "search_tsv" in src, "search_tsv column name missing from upgrade()"
    assert "GENERATED ALWAYS AS" in src, "GENERATED ALWAYS AS missing from upgrade()"
    assert "STORED" in src, "STORED keyword missing from upgrade()"


def test_upgrade_creates_gin_index() -> None:
    """upgrade() must create a GIN index named ix_events_search_tsv."""
    mod = _load_migration()
    src = inspect.getsource(mod.upgrade)
    assert "ix_events_search_tsv" in src, "GIN index name missing from upgrade()"
    assert "GIN" in src or "gin" in src.lower(), "USING GIN missing from upgrade()"


def test_upgrade_creates_filter_presets_table() -> None:
    """upgrade() must create filter_presets table with required columns."""
    mod = _load_migration()
    src = inspect.getsource(mod.upgrade)
    assert "filter_presets" in src, "filter_presets table name missing from upgrade()"
    # name and query_params must be present in any case
    assert "name text NOT NULL UNIQUE" in src or "name text UNIQUE NOT NULL" in src, (
        "filter_presets.name column definition missing"
    )
    assert "query_params jsonb NOT NULL" in src.lower() or "query_params jsonb NOT NULL" in src, (
        "filter_presets.query_params column definition missing"
    )


# ---------------------------------------------------------------------------
# downgrade() DDL shape
# ---------------------------------------------------------------------------


def test_downgrade_drops_in_reverse_order() -> None:
    """downgrade() must DROP table, index, and column — all three present."""
    mod = _load_migration()
    src = inspect.getsource(mod.downgrade)
    assert "DROP TABLE IF EXISTS filter_presets" in src, (
        "downgrade() missing DROP TABLE filter_presets"
    )
    assert "DROP INDEX IF EXISTS ix_events_search_tsv" in src, (
        "downgrade() missing DROP INDEX ix_events_search_tsv"
    )
    assert "DROP COLUMN IF EXISTS search_tsv" in src, (
        "downgrade() missing DROP COLUMN search_tsv"
    )

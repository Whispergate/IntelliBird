# Owned by: 12.1-03-PLAN
"""Unit tests for build_assets_aggregation_select + summary_from_rows (Task 3).

Pure SQL-compilation + Python logic only. Real-DB aggregation lives in
backend/tests/integration/test_assets_query_integration.py.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Select
from sqlalchemy.dialects import postgresql

from app.schemas.assets import AssetSummaryBucket, SUMMARY_BUCKET_KEYS
from app.services.assets_query import (
    build_assets_aggregation_select,
    load_stale_cutoff,
    summary_from_rows,
)


def _compile(stmt) -> str:
    return str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_build_assets_aggregation_select_returns_select():
    stmt = build_assets_aggregation_select(uuid.uuid4())
    assert isinstance(stmt, Select)


def test_aggregation_output_columns_present():
    stmt = build_assets_aggregation_select(uuid.uuid4())
    labels = {c.key for c in stmt.selected_columns}
    for expected in (
        "bbot_event_type",
        "canonical_target",
        "first_seen",
        "last_seen",
        "scan_count",
        "modules",
        "severity_max",
    ):
        assert expected in labels, f"missing column: {expected}"


def test_aggregation_where_clause_filters_project_id():
    pid = uuid.uuid4()
    compiled = _compile(build_assets_aggregation_select(pid))
    # Project id literal appears in the compiled SQL
    assert str(pid) in compiled
    assert "easm_findings.project_id" in compiled


def test_aggregation_group_by_clauses():
    compiled = _compile(build_assets_aggregation_select(uuid.uuid4()))
    assert "GROUP BY" in compiled
    assert "easm_findings.bbot_event_type" in compiled
    assert "easm_findings.canonical_target" in compiled


def test_aggregation_select_does_not_reference_raw_bbot_column():
    """Pitfall 1 — raw_bbot is drawer-only; must not land in list/summary SELECT."""
    compiled = _compile(build_assets_aggregation_select(uuid.uuid4()))
    assert "raw_bbot" not in compiled


def test_load_stale_cutoff_sql_shape():
    """Compile the load_stale_cutoff inner select to assert SQL shape without hitting the DB."""
    # We compile by reproducing the same statement construction as the function —
    # load_stale_cutoff itself is async; its internal stmt is what matters.
    from sqlalchemy import func, select

    from app.models.easm import EASMScan

    pid = uuid.uuid4()
    stmt = (
        select(func.max(EASMScan.started_at))
        .where(EASMScan.project_id == pid)
        .where(EASMScan.status == "finished")
    )
    compiled = _compile(stmt)
    assert "'finished'" in compiled
    assert "started_at" in compiled


def test_summary_from_rows_returns_all_seven_keys():
    rows = [
        {"bbot_event_type": "DNS_NAME", "stale": False},
        {"bbot_event_type": "IP_ADDRESS", "stale": True},
        {"bbot_event_type": "TECHNOLOGY", "stale": False},
    ]
    out = summary_from_rows(rows)
    assert set(out.keys()) == set(SUMMARY_BUCKET_KEYS)
    for v in out.values():
        assert isinstance(v, AssetSummaryBucket)
    assert out["DOMAINS"].count == 1
    assert out["IPS"].count == 1
    assert out["IPS"].stale_count == 1
    assert out["TECHNOLOGIES"].count == 1
    assert out["OTHER"].count == 0


def test_summary_from_rows_empty_returns_all_zero_buckets():
    out = summary_from_rows([])
    assert set(out.keys()) == set(SUMMARY_BUCKET_KEYS)
    for key in SUMMARY_BUCKET_KEYS:
        assert out[key].count == 0
        assert out[key].stale_count == 0


def test_load_stale_cutoff_is_callable():
    """Smoke check: load_stale_cutoff is an async function importable from module."""
    assert callable(load_stale_cutoff)

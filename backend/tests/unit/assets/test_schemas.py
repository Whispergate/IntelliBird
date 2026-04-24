# Owned by: 12.1-02-PLAN
"""Schema contract tests for /api/projects/{id}/assets.

Verifies the 10 locked behaviours from 12.1-02-PLAN §tasks/task 1/behavior.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError


def _valid_asset_id(event_type: str = "DNS_NAME", target: str = "example.com") -> str:
    return hashlib.sha256(f"{event_type}|{target}".encode()).hexdigest()


def _row_fixture(**overrides):
    base = {
        "asset_id": _valid_asset_id(),
        "bbot_event_type": "DNS_NAME",
        "canonical_target": "example.com",
        "scope": "in_scope",
        "first_seen": datetime(2026, 4, 1, tzinfo=timezone.utc),
        "last_seen": datetime(2026, 4, 20, tzinfo=timezone.utc),
        "scan_count": 3,
        "modules": ["subdomains", "dnsx"],
        "stale": False,
        "severity_max": None,
    }
    base.update(overrides)
    return base


# Behaviour 1: importable
def test_top_level_imports():
    from app.schemas.assets import (  # noqa: F401
        AssetDetail,
        AssetExportFormat,
        AssetNotePatch,
        AssetRow,
        AssetScope,
        AssetSummary,
    )


# Behaviour 2: AssetScope is StrEnum with exactly {in_scope, out_of_scope, unscoped}
def test_asset_scope_values_locked():
    from app.schemas.assets import AssetScope

    assert set(AssetScope) == {
        AssetScope.IN_SCOPE,
        AssetScope.OUT_OF_SCOPE,
        AssetScope.UNSCOPED,
    }
    assert AssetScope.IN_SCOPE.value == "in_scope"
    assert AssetScope.OUT_OF_SCOPE.value == "out_of_scope"
    assert AssetScope.UNSCOPED.value == "unscoped"
    with pytest.raises(ValueError):
        AssetScope("foo")


# Behaviour 3: AssetExportFormat enum exactly {csv, json}
def test_asset_export_format_values_locked():
    from app.schemas.assets import AssetExportFormat

    assert set(AssetExportFormat) == {AssetExportFormat.CSV, AssetExportFormat.JSON}
    assert AssetExportFormat.CSV.value == "csv"
    assert AssetExportFormat.JSON.value == "json"
    with pytest.raises(ValueError):
        AssetExportFormat("xml")


# Behaviour 4: AssetRow accepts a complete dict with required fields
def test_asset_row_validates_complete_dict():
    from app.schemas.assets import AssetRow, AssetScope

    row = AssetRow.model_validate(_row_fixture())
    assert row.bbot_event_type == "DNS_NAME"
    assert row.canonical_target == "example.com"
    assert row.scope == AssetScope.IN_SCOPE
    assert row.scan_count == 3
    assert row.modules == ["subdomains", "dnsx"]
    assert row.stale is False
    assert row.severity_max is None
    assert len(row.asset_id) == 64


# Behaviour 5: asset_id rejects non-hex / wrong-length
def test_asset_row_rejects_malformed_asset_id():
    from app.schemas.assets import AssetRow

    with pytest.raises(ValidationError):
        AssetRow.model_validate(_row_fixture(asset_id="not-hex"))
    with pytest.raises(ValidationError):
        AssetRow.model_validate(_row_fixture(asset_id="a" * 63))
    with pytest.raises(ValidationError):
        AssetRow.model_validate(_row_fixture(asset_id="A" * 64))  # uppercase rejected
    with pytest.raises(ValidationError):
        AssetRow.model_validate(_row_fixture(asset_id="g" * 64))  # non-hex char


# Behaviour 6: AssetNotePatch empty OK, >10_000 rejected, missing rejected
def test_asset_note_patch_bounds():
    from app.schemas.assets import AssetNotePatch

    # empty string allowed — operator clearing a note
    assert AssetNotePatch.model_validate({"note": ""}).note == ""

    # exact 10_000 char limit — allowed
    assert AssetNotePatch.model_validate({"note": "x" * 10_000}).note == "x" * 10_000

    # 10_001 chars — rejected
    with pytest.raises(ValidationError):
        AssetNotePatch.model_validate({"note": "x" * 10_001})

    # missing note field — rejected
    with pytest.raises(ValidationError):
        AssetNotePatch.model_validate({})


# Behaviour 7: AssetDetail = AssetRow + findings + promoted_events + note
def test_asset_detail_composition():
    from app.schemas.assets import AssetDetail

    payload = {
        **_row_fixture(),
        "findings": [],
        "promoted_events": [],
        "note": None,
    }
    detail = AssetDetail.model_validate(payload)
    assert detail.findings == []
    assert detail.promoted_events == []
    assert detail.note is None
    # inherits AssetRow fields
    assert detail.bbot_event_type == "DNS_NAME"
    assert detail.canonical_target == "example.com"


# Behaviour 8: AssetSummary has {buckets: dict[str, AssetSummaryBucket]} and 7 canonical bucket keys
def test_asset_summary_shape_and_canonical_keys():
    from app.schemas.assets import (
        SUMMARY_BUCKET_KEYS,
        AssetSummary,
        AssetSummaryBucket,
    )

    assert SUMMARY_BUCKET_KEYS == (
        "DOMAINS",
        "IPS",
        "OPEN_PORTS",
        "URLS",
        "TECHNOLOGIES",
        "IDENTITIES",
        "OTHER",
    )
    assert len(SUMMARY_BUCKET_KEYS) == 7

    buckets = {
        key: AssetSummaryBucket(count=i, stale_count=0)
        for i, key in enumerate(SUMMARY_BUCKET_KEYS)
    }
    summary = AssetSummary.model_validate({"buckets": buckets})
    assert set(summary.buckets.keys()) == set(SUMMARY_BUCKET_KEYS)
    assert summary.buckets["DOMAINS"].count == 0
    assert summary.buckets["OTHER"].count == 6


# Behaviour 9: AssetFinding carries locked drawer fields
def test_asset_finding_fields():
    import uuid

    from app.schemas.assets import AssetFinding

    payload = {
        "id": uuid.uuid4(),
        "scan_id": uuid.uuid4(),
        "scan_started_at": datetime(2026, 4, 20, tzinfo=timezone.utc),
        "module": "subdomains",
        "lifecycle_status": "new",
        "severity": "medium",
        "first_seen": datetime(2026, 4, 1, tzinfo=timezone.utc),
        "last_seen": datetime(2026, 4, 20, tzinfo=timezone.utc),
        "raw_bbot": {"event_type": "DNS_NAME", "data": "example.com"},
    }
    finding = AssetFinding.model_validate(payload)
    assert finding.module == "subdomains"
    assert finding.lifecycle_status == "new"
    assert finding.severity == "medium"
    assert finding.raw_bbot == {"event_type": "DNS_NAME", "data": "example.com"}

    # severity optional, raw_bbot optional
    minimal = {**payload, "severity": None, "raw_bbot": None}
    f2 = AssetFinding.model_validate(minimal)
    assert f2.severity is None
    assert f2.raw_bbot is None


# Behaviour 10: AssetListResponse = {items, total, limit, offset}
def test_asset_list_response_shape():
    from app.schemas.assets import AssetListResponse, AssetRow

    row = AssetRow.model_validate(_row_fixture())
    resp = AssetListResponse.model_validate(
        {"items": [row], "total": 1, "limit": 50, "offset": 0}
    )
    assert resp.total == 1
    assert resp.limit == 50
    assert resp.offset == 0
    assert len(resp.items) == 1

    # negative offset rejected
    with pytest.raises(ValidationError):
        AssetListResponse.model_validate(
            {"items": [], "total": 0, "limit": 50, "offset": -1}
        )
    # limit > 500 rejected
    with pytest.raises(ValidationError):
        AssetListResponse.model_validate(
            {"items": [], "total": 0, "limit": 501, "offset": 0}
        )

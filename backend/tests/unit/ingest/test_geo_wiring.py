"""_persist_event geo wiring tests --02 (MAP-05).

Tests verify that _persist_event resolves geo coordinates from raw_stix
when the worker has not pre-populated them, and that pre-existing coords
are respected (no redundant resolution).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import uuid
from datetime import datetime, timezone

import pytest


# ---------------------------------------------------------------------------
# Helper - minimal valid row dict (no geo columns set)
# ---------------------------------------------------------------------------

def _make_row(*, raw_stix=None, geo_lat=None, geo_lon=None):
    row = {
        "id": uuid.uuid4(),
        "stix_type": "indicator",
        "source_id": uuid.uuid4(),
        "observed_at": datetime.now(timezone.utc),
        "content_hash": str(uuid.uuid4()),
        "raw_stix": raw_stix,
    }
    if geo_lat is not None:
        row["geo_lat"] = geo_lat
    if geo_lon is not None:
        row["geo_lon"] = geo_lon
    return row


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_persist_event_populates_geo_from_stix_location():
    """_persist_event calls resolve_geo and writes lat/lon/country_code into the row."""
    raw_stix = {
        "type": "bundle",
        "objects": [
            {
                "type": "location",
                "latitude": 48.85,
                "longitude": 2.35,
                "country": "FR",
            }
        ],
    }
    row = _make_row(raw_stix=raw_stix)

    session = MagicMock()
    # Capture the values dict passed to pg_insert.values
    captured_values: dict = {}



    def fake_pg_insert(table):
        stmt_mock = MagicMock()
        conflict_mock = MagicMock()
        conflict_mock.return_value = conflict_mock  # on_conflict_do_nothing chains

        def capture_values(**kw):
            captured_values.update(kw)
            stmt_mock.on_conflict_do_nothing = conflict_mock
            return stmt_mock

        stmt_mock.values = capture_values
        return stmt_mock

    with patch("app.ingest.normalise.pg_insert", fake_pg_insert):
        from app.ingest import normalise
        normalise._persist_event(session, row)

    assert captured_values.get("geo_lat") == pytest.approx(48.85)
    assert captured_values.get("geo_lon") == pytest.approx(2.35)
    assert captured_values.get("country_code") == "FR"


def test_persist_event_preserves_existing_geo():
    """If geo_lat and geo_lon are already set, resolve_geo MUST NOT be called."""
    raw_stix = {
        "type": "bundle",
        "objects": [
            {
                "type": "location",
                "latitude": 51.5,
                "longitude": -0.1,
                "country": "GB",
            }
        ],
    }
    row = _make_row(raw_stix=raw_stix, geo_lat=10.0, geo_lon=20.0)

    session = MagicMock()

    def _should_not_be_called(*_args, **_kwargs):
        raise AssertionError("resolve_geo was called despite pre-populated geo columns")


    def fake_pg_insert(table):
        stmt_mock = MagicMock()
        conflict_mock = MagicMock()
        conflict_mock.return_value = conflict_mock

        def capture_values(**kw):
            stmt_mock.on_conflict_do_nothing = conflict_mock
            return stmt_mock

        stmt_mock.values = capture_values
        return stmt_mock

    with patch("app.ingest.normalise.pg_insert", fake_pg_insert):
        with patch("app.services.geo.resolve_geo", _should_not_be_called):
            from app.ingest import normalise
            # Reset module-level import cache to force re-evaluation
            normalise._persist_event(session, row)
    # No AssertionError raised - test passes


def test_persist_event_none_raw_stix():
    """If raw_stix is None, resolve_geo returns (None, None, None) and geo columns are not injected."""
    row = _make_row(raw_stix=None)

    session = MagicMock()
    captured_values: dict = {}

    def fake_pg_insert(table):
        stmt_mock = MagicMock()
        conflict_mock = MagicMock()
        conflict_mock.return_value = conflict_mock

        def capture_values(**kw):
            captured_values.update(kw)
            stmt_mock.on_conflict_do_nothing = conflict_mock
            return stmt_mock

        stmt_mock.values = capture_values
        return stmt_mock

    with patch("app.ingest.normalise.pg_insert", fake_pg_insert):
        with patch("app.services.geo.resolve_geo", return_value=(None, None, None)):
            from app.ingest import normalise
            normalise._persist_event(session, row)

    # geo columns must NOT be present in the row dict (left untouched)
    assert "geo_lat" not in captured_values
    assert "geo_lon" not in captured_values

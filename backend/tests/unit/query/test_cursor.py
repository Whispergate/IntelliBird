"""Tests for cursor encode/decode - FIL-01."""
from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone

import pytest

from app.services.events_query import (
    CursorError,
    decode_cursor,
    decode_fts_cursor,
    encode_cursor,
    encode_fts_cursor,
)


def test_encode_decode_roundtrip():
    ts = datetime(2025, 9, 15, 12, 30, tzinfo=timezone.utc)
    eid = uuid.uuid4()
    c = encode_cursor(ts, eid)
    ts2, eid2 = decode_cursor(c)
    assert ts2 == ts
    assert eid2 == eid


def test_encode_strips_padding():
    ts = datetime(2025, 9, 15, 12, 30, tzinfo=timezone.utc)
    eid = uuid.uuid4()
    c = encode_cursor(ts, eid)
    assert not c.endswith("=")


def test_decode_invalid_base64_raises():
    with pytest.raises(CursorError):
        decode_cursor("not!valid!base64!@#$")


def test_decode_missing_separator_raises():
    bad = base64.urlsafe_b64encode(b"no-separator").decode().rstrip("=")
    with pytest.raises(CursorError):
        decode_cursor(bad)


def test_decode_bad_uuid_raises():
    bad = base64.urlsafe_b64encode(b"2025-09-15T12:30:00+00:00|not-a-uuid").decode().rstrip("=")
    with pytest.raises(CursorError):
        decode_cursor(bad)


def test_decode_restores_missing_padding():
    # Deliberately hand-built cursor missing trailing '='
    ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    eid = uuid.uuid4()
    c = encode_cursor(ts, eid)
    # Double-check decode works with any padding state
    ts2, eid2 = decode_cursor(c)
    assert (ts2, eid2) == (ts, eid)


def test_fts_cursor_roundtrip():
    ts = datetime(2025, 9, 15, 12, 30, tzinfo=timezone.utc)
    eid = uuid.uuid4()
    c = encode_fts_cursor(0.12345678, ts, eid)
    r2, ts2, eid2 = decode_fts_cursor(c)
    assert abs(r2 - 0.12345678) < 1e-9
    assert ts2 == ts
    assert eid2 == eid


def test_fts_cursor_preserves_rank_precision():
    r1 = 0.00012345
    ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    eid = uuid.uuid4()
    c = encode_fts_cursor(r1, ts, eid)
    r2, _, _ = decode_fts_cursor(c)
    assert f"{r2:.8f}" == f"{r1:.8f}"


def test_fts_cursor_invalid_parts_raises():
    bad = base64.urlsafe_b64encode(b"only|two").decode().rstrip("=")
    with pytest.raises(CursorError):
        decode_fts_cursor(bad)


def test_fts_cursor_invalid_rank_raises():
    bad = base64.urlsafe_b64encode(b"not-a-number|2025-01-01T00:00:00+00:00|123").decode().rstrip("=")
    with pytest.raises(CursorError):
        decode_fts_cursor(bad)

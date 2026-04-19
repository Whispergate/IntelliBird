"""Webhook dispatcher tests — unskipped by 07-03.

Strategy: pure-function tests using in-process stubs.
- FakeRedis: dict-backed stub that implements the Redis methods used by the dispatcher
 (llen, rpush, lrange, set, get, expire, delete).
- FakeSession: minimal SQLAlchemy session stub for _record_delivery_result /
 _advance_cursor tests that only call session.execute.
- httpx: monkeypatched via module-level attribute replacement.
- time.sleep: monkeypatched to capture call args.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers / stubs
# ---------------------------------------------------------------------------

class FakeRedis:
    """Minimal Redis stub covering all methods used by the dispatcher."""

    def __init__(self) -> None:
        self._lists: dict[str, list[bytes]] = {}
        self._strings: dict[str, bytes] = {}

    # list ops
    def llen(self, key: str) -> int:
        return len(self._lists.get(key, []))

    def rpush(self, key: str, *values: Any) -> int:
        bucket = self._lists.setdefault(key, [])
        for v in values:
            bucket.append(v.encode() if isinstance(v, str) else v)
        return len(bucket)

    def lrange(self, key: str, start: int, end: int) -> list[bytes]:
        bucket = self._lists.get(key, [])
        # Redis lrange is inclusive on both ends; end=-1 means last element
        if end == -1:
            end = len(bucket) - 1
        return bucket[start : end + 1]

    # string ops
    def set(self, key: str, value: Any) -> None:
        self._strings[key] = value.encode() if isinstance(value, str) else value

    def get(self, key: str) -> bytes | None:
        return self._strings.get(key)

    def expire(self, key: str, ttl: int) -> None:
        pass  # not simulated

    def delete(self, *keys: str) -> None:
        for k in keys:
            self._lists.pop(k, None)
            self._strings.pop(k, None)


def _make_webhook(
    *,
    id: str | None = None,
    destination_type: str = "generic",
    url: str = "https://example.com/hook",
    auth_enc: str | None = None,
    batching_window_sec: int = 300,
    enabled: bool = True,
    last_dispatch_at: datetime | None = None,
    consecutive_failures: int = 0,
) -> MagicMock:
    wh = MagicMock()
    wh.id = uuid.UUID(id) if id else uuid.uuid4()
    wh.destination_type = destination_type
    wh.url = url
    wh.auth_enc = auth_enc
    wh.batching_window_sec = batching_window_sec
    wh.enabled = enabled
    wh.last_dispatch_at = last_dispatch_at
    wh.consecutive_failures = consecutive_failures
    return wh


def _make_event(
    *,
    id: str | None = None,
    title: str = "Test event",
    observed_at: str = "2026-01-01T12:00:00+00:00",
) -> dict:
    return {
        "id": id or str(uuid.uuid4()),
        "observed_at": observed_at,
        "fetched_at": "2026-01-01T12:01:00+00:00",
        "source_id": None,
        "source_name": "TestFeed",
        "source_type": "rss",
        "stix_id": None,
        "stix_type": "indicator",
        "title": title,
        "description": "A test event",
        "tlp": "clear",
        "tags": [],
        "attack_techniques": [],
        "archived": False,
        "visibility": "shared",
        "geo_lat": None,
        "geo_lon": None,
    }


def _make_preset(name: str = "test-preset") -> MagicMock:
    preset = MagicMock()
    preset.name = name
    preset.query_params = {"tag": None, "tlp": None}
    return preset


# ---------------------------------------------------------------------------
# Import dispatcher under test (lazy, after env is set — tests don't need DB)
# ---------------------------------------------------------------------------

import importlib
import os
os.environ.setdefault("SECRET_KEY", "a" * 34)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import app.services.webhook_dispatcher as disp


# ===========================================================================
# TestBatching
# ===========================================================================

class TestBatching:
    def test_first_event_fires_immediately(self, monkeypatch):
        """: when Redis list is empty, events are pushed and dispatch fires immediately."""
        wh = _make_webhook()
        r = FakeRedis()
        event = _make_event()
        preset = _make_preset()
        session = MagicMock()

        drain_calls = []
        monkeypatch.setattr(
            disp,
            "_drain_and_dispatch",
            lambda *a, **kw: drain_calls.append(a),
        )
        monkeypatch.setattr(
            disp,
            "_fetch_matching_events",
            lambda *a, **kw: [event],
        )

        # Bind a preset via session
        bindings_result = MagicMock()
        bindings_result.scalars.return_value.all.return_value = [preset]
        session.execute.return_value = bindings_result

        disp._process_webhook(wh, session, r)

        # Should have called _drain_and_dispatch once
        assert len(drain_calls) == 1
        # Redis list should contain the event
        batch_key = f"wh-batch:{wh.id}"
        assert r.llen(batch_key) == 1

    def test_subsequent_events_accumulate(self, monkeypatch):
        """: when Redis list already has items and window not closed, only accumulate."""
        wh = _make_webhook(batching_window_sec=300)
        r = FakeRedis()
        now = datetime.now(timezone.utc)
        event = _make_event()
        preset = _make_preset()
        session = MagicMock()

        # Pre-populate Redis: existing item + recent window start
        batch_key = f"wh-batch:{wh.id}"
        ts_key = f"wh-batch-ts:{wh.id}"
        r.rpush(batch_key, json.dumps(_make_event()))
        r.set(ts_key, now.isoformat())  # window started NOW → not yet expired

        drain_calls = []
        monkeypatch.setattr(
            disp,
            "_drain_and_dispatch",
            lambda *a, **kw: drain_calls.append(a),
        )
        monkeypatch.setattr(
            disp,
            "_fetch_matching_events",
            lambda *a, **kw: [event],
        )

        bindings_result = MagicMock()
        bindings_result.scalars.return_value.all.return_value = [preset]
        session.execute.return_value = bindings_result

        disp._process_webhook(wh, session, r)

        # Window not closed → no dispatch
        assert len(drain_calls) == 0
        # New event was appended
        assert r.llen(batch_key) == 2

    def test_window_close_drains(self, monkeypatch):
        """When batching window has elapsed, _drain_and_dispatch fires."""
        wh = _make_webhook(batching_window_sec=300)
        r = FakeRedis()
        event = _make_event()
        preset = _make_preset()
        session = MagicMock()

        # Window started 301s ago
        batch_key = f"wh-batch:{wh.id}"
        ts_key = f"wh-batch-ts:{wh.id}"
        r.rpush(batch_key, json.dumps(_make_event()))
        old_ts = (datetime.now(timezone.utc) - timedelta(seconds=301)).isoformat()
        r.set(ts_key, old_ts)

        drain_calls = []
        monkeypatch.setattr(
            disp,
            "_drain_and_dispatch",
            lambda *a, **kw: drain_calls.append(a),
        )
        monkeypatch.setattr(
            disp,
            "_fetch_matching_events",
            lambda *a, **kw: [event],
        )

        bindings_result = MagicMock()
        bindings_result.scalars.return_value.all.return_value = [preset]
        session.execute.return_value = bindings_result

        disp._process_webhook(wh, session, r)

        assert len(drain_calls) == 1

    def test_null_cursor_uses_24h_lookback(self, monkeypatch):
        """: NULL cursor → observed_from = now - 24h (within 1s tolerance)."""
        captured_params = []

        def fake_build_events_query(params, role):
            captured_params.append(params)
            return MagicMock()  # stmt that session.execute can handle

        monkeypatch.setattr(disp, "build_events_query", fake_build_events_query)

        session = MagicMock()
        # session.execute(stmt).scalars.all -> []
        session.execute.return_value.scalars.return_value.all.return_value = []

        before = datetime.now(timezone.utc)
        disp._fetch_matching_events(session, {}, last_dispatch_at=None)
        after = datetime.now(timezone.utc)

        assert len(captured_params) == 1
        observed_from = captured_params[0].observed_from
        expected_floor = before - timedelta(hours=24) - timedelta(seconds=1)
        expected_ceil = after - timedelta(hours=24) + timedelta(seconds=1)
        assert expected_floor <= observed_from <= expected_ceil


# ===========================================================================
# TestRetry
# ===========================================================================

class TestRetry:
    def test_retries_30_60_120_seconds(self, monkeypatch):
        """: 3 attempts → sleep called with 30, 60 between attempts (not after last)."""
        sleep_calls: list[int] = []
        monkeypatch.setattr(disp.time, "sleep", lambda n: sleep_calls.append(n))

        call_count = 0

        class FakeClient:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def post(self, url, json, headers):
                nonlocal call_count
                call_count += 1
                raise disp.httpx.TimeoutException("timeout")

        monkeypatch.setattr(disp.httpx, "Client", lambda **kw: FakeClient())

        ok, err = disp._post_with_retry("https://example.com", {}, {})

        assert not ok
        assert err == "timeout"
        assert call_count == 3
        # 2 sleeps between 3 attempts: [30, 60]; no sleep after last attempt
        assert sleep_calls == [30, 60]

    def test_max_3_attempts(self, monkeypatch):
        """: at most 3 attempts, no 4th."""
        monkeypatch.setattr(disp.time, "sleep", lambda n: None)

        attempt_count = 0

        class FakeClient:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def post(self, url, json, headers):
                nonlocal attempt_count
                attempt_count += 1
                resp = MagicMock()
                resp.status_code = 500
                return resp

        monkeypatch.setattr(disp.httpx, "Client", lambda **kw: FakeClient())

        ok, err = disp._post_with_retry("https://example.com", {}, {})

        assert not ok
        assert err == "http_500"
        assert attempt_count == 3

    def test_auto_disable_at_5_consecutive_failures(self):
        """: webhook.consecutive_failures=4 + failure → enabled=false in UPDATE."""
        wh = _make_webhook(consecutive_failures=4)
        session = MagicMock()

        disp._record_delivery_result(session, wh, ok=False, err="http_500")

        # Find the execute call with the UPDATE
        assert session.execute.called
        call_args = session.execute.call_args
        stmt = call_args[0][0]  # first positional arg is the text obj
        params = call_args[0][1]  # second positional arg is the params dict

        # cf should be 5, disable should be True
        assert params["cf"] == 5
        assert params["disable"] is True


# ===========================================================================
# Cursor tests
# ===========================================================================

def test_cursor_stays_on_failure(monkeypatch):
    """: on delivery failure, _advance_cursor is NOT called."""
    wh = _make_webhook(consecutive_failures=0)
    r = FakeRedis()
    session = MagicMock()
    preset = _make_preset()

    # Pre-populate Redis with one event
    batch_key = f"wh-batch:{wh.id}"
    event = _make_event()
    r.rpush(batch_key, json.dumps(event))

    advance_calls = []
    monkeypatch.setattr(
        disp,
        "_advance_cursor",
        lambda s, wh_, ts: advance_calls.append((s, wh_, ts)),
    )
    monkeypatch.setattr(
        disp,
        "_post_with_retry",
        lambda url, payload, headers: (False, "http_500"),
    )
    monkeypatch.setattr(disp, "_record_delivery_result", lambda *a, **kw: None)

    disp._drain_and_dispatch(wh, r, session, preset)

    assert advance_calls == [], "cursor must NOT advance on failure"


def test_cursor_advances_on_success(monkeypatch):
    """: on delivery success, _advance_cursor IS called with max observed_at."""
    wh = _make_webhook(consecutive_failures=0)
    r = FakeRedis()
    session = MagicMock()
    preset = _make_preset()

    observed = "2026-01-15T10:00:00+00:00"
    batch_key = f"wh-batch:{wh.id}"
    r.rpush(batch_key, json.dumps(_make_event(observed_at=observed)))

    advance_calls: list[tuple] = []
    monkeypatch.setattr(
        disp,
        "_advance_cursor",
        lambda s, wh_, ts: advance_calls.append((s, wh_, ts)),
    )
    monkeypatch.setattr(
        disp,
        "_post_with_retry",
        lambda url, payload, headers: (True, None),
    )
    monkeypatch.setattr(disp, "_record_delivery_result", lambda *a, **kw: None)

    disp._drain_and_dispatch(wh, r, session, preset)

    assert len(advance_calls) == 1
    # The cursor timestamp should be the event's observed_at
    _, _, cursor_ts = advance_calls[0]
    assert cursor_ts == datetime.fromisoformat(observed)


def test_event_matching_reuses_build_events_query(monkeypatch):
    """: _fetch_matching_events calls build_events_query with dashboard_roles=None."""
    spy_calls: list[tuple] = []

    def spy_build_events_query(params, dashboard_roles):
        spy_calls.append((params, dashboard_roles))
        return MagicMock()

    monkeypatch.setattr(disp, "build_events_query", spy_build_events_query)

    session = MagicMock()
    session.execute.return_value.scalars.return_value.all.return_value = []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    disp._fetch_matching_events(session, {}, last_dispatch_at=cutoff)

    assert len(spy_calls) == 1
    _, dashboard_roles_passed = spy_calls[0]
    assert dashboard_roles_passed is None, f"Expected dashboard_roles=None but got {dashboard_roles_passed!r}"


def test_dedup_across_bound_presets(monkeypatch):
    """: same event matched by 2 presets → appears ONCE in Redis batch."""
    wh = _make_webhook()
    r = FakeRedis()
    session = MagicMock()
    preset_a = _make_preset("preset-a")
    preset_b = _make_preset("preset-b")

    shared_event_id = str(uuid.uuid4())
    shared_event = _make_event(id=shared_event_id)

    # Both presets return the same event
    monkeypatch.setattr(
        disp,
        "_fetch_matching_events",
        lambda *a, **kw: [shared_event],
    )

    drain_calls = []
    monkeypatch.setattr(
        disp,
        "_drain_and_dispatch",
        lambda *a, **kw: drain_calls.append(a),
    )

    # session returns two presets
    bindings_result = MagicMock()
    bindings_result.scalars.return_value.all.return_value = [preset_a, preset_b]
    session.execute.return_value = bindings_result

    disp._process_webhook(wh, session, r)

    batch_key = f"wh-batch:{wh.id}"
    items_in_redis = r.lrange(batch_key, 0, -1)
    assert len(items_in_redis) == 1, (
        f"Expected 1 deduplicated event in Redis but found {len(items_in_redis)}"
    )

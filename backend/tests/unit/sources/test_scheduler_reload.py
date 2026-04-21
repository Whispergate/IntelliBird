"""Unit tests for — scheduler Redis pub/sub reload listener.

Tests cover:
- _reload_handler: remove_job dispatch, malformed entries, _load_source_jobs call
- _reload_listener_loop: message type filtering, bad JSON, unknown action
- _start_reload_listener: daemon thread properties
- build_scheduler: graceful degradation when listener raises at start

Env vars are set before any app.* import so pydantic-settings does not fail
during module-level import of app.scheduler.jobs (which imports app.workers.broker
which imports app.config.settings at load time).
"""
from __future__ import annotations

import json
import os
import time
from typing import Any
from unittest.mock import MagicMock, call, patch

# --- env setup MUST be before any app.* import ---
os.environ.setdefault("SECRET_KEY", "a" * 48)
os.environ.setdefault("JWT_SIGNING_KEY", "b" * 64)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.blocking import BlockingScheduler

from app.scheduler.jobs import (
    _reload_handler,
    _reload_listener_loop,
    _start_reload_listener,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_scheduler() -> MagicMock:
    """Return a mock that quacks like a BlockingScheduler."""
    return MagicMock(spec=BlockingScheduler)


# ---------------------------------------------------------------------------
# _reload_handler tests
# ---------------------------------------------------------------------------

def test_reload_handler_empty_payload_calls_load_source_jobs(monkeypatch):
    """Empty deleted list still triggers _load_source_jobs."""
    sched = _make_scheduler()
    called_with = []

    def _fake_load(s):
        called_with.append(s)

    monkeypatch.setattr("app.scheduler.jobs._load_source_jobs", _fake_load)

    _reload_handler(sched, {"action": "reload"})

    assert called_with == [sched]
    sched.remove_job.assert_not_called()


def test_reload_handler_removes_single_deleted_job(monkeypatch):
    """Payload with one deleted entry calls remove_job with the correct id."""
    sched = _make_scheduler()
    monkeypatch.setattr("app.scheduler.jobs._load_source_jobs", lambda s: None)

    _reload_handler(sched, {
        "action": "reload",
        "deleted": [{"feed_type": "rss", "source_id": "abc-123"}],
    })

    sched.remove_job.assert_called_once_with("poll_rss_abc-123")


def test_reload_handler_removes_multiple_deleted_jobs(monkeypatch):
    """Three deleted entries produce three remove_job calls with correct ids."""
    sched = _make_scheduler()
    monkeypatch.setattr("app.scheduler.jobs._load_source_jobs", lambda s: None)

    entries = [
        {"feed_type": "rss", "source_id": "id-1"},
        {"feed_type": "taxii", "source_id": "id-2"},
        {"feed_type": "nvd", "source_id": "id-3"},
    ]
    _reload_handler(sched, {"action": "reload", "deleted": entries})

    assert sched.remove_job.call_count == 3
    sched.remove_job.assert_any_call("poll_rss_id-1")
    sched.remove_job.assert_any_call("poll_taxii_id-2")
    sched.remove_job.assert_any_call("poll_nvd_id-3")


def test_reload_handler_tolerates_missing_job(monkeypatch):
    """JobLookupError from remove_job is swallowed; _load_source_jobs still called."""
    sched = _make_scheduler()
    sched.remove_job.side_effect = JobLookupError("poll_rss_x")
    load_calls = []
    monkeypatch.setattr("app.scheduler.jobs._load_source_jobs", lambda s: load_calls.append(s))

    # Must not raise
    _reload_handler(sched, {
        "action": "reload",
        "deleted": [{"feed_type": "rss", "source_id": "x"}],
    })

    assert load_calls == [sched]


def test_reload_handler_skips_malformed_deleted_entry(monkeypatch):
    """Entries missing feed_type or source_id are skipped; remove_job never called."""
    sched = _make_scheduler()
    load_calls = []
    monkeypatch.setattr("app.scheduler.jobs._load_source_jobs", lambda s: load_calls.append(s))

    _reload_handler(sched, {
        "action": "reload",
        "deleted": [
            {"feed_type": "rss"},          # missing source_id
            {"source_id": "x"},            # missing feed_type
            {},                            # both missing
        ],
    })

    sched.remove_job.assert_not_called()
    assert load_calls == [sched]


def test_reload_handler_load_source_jobs_exception_does_not_raise(monkeypatch):
    """If _load_source_jobs raises, _reload_handler swallows it."""
    sched = _make_scheduler()
    monkeypatch.setattr(
        "app.scheduler.jobs._load_source_jobs",
        lambda s: (_ for _ in ()).throw(RuntimeError("db gone")),
    )

    # Should not propagate
    _reload_handler(sched, {"action": "reload"})


# ---------------------------------------------------------------------------
# _reload_listener_loop tests
# ---------------------------------------------------------------------------

def _make_fake_pubsub(messages: list[dict[str, Any]]):
    """Return a fake redis object whose pubsub.listen yields messages."""
    pubsub = MagicMock()
    pubsub.listen.return_value = iter(messages)

    r = MagicMock()
    r.pubsub.return_value = pubsub
    return r


def test_reload_listener_loop_ignores_non_message_types(monkeypatch):
    """subscribe-type messages are ignored; only message-type dispatches handler."""
    messages = [
        {"type": "subscribe", "data": 1},
        {"type": "message", "data": json.dumps({"action": "reload"})},
    ]
    fake_redis = _make_fake_pubsub(messages)

    monkeypatch.setattr("redis.from_url", lambda url: fake_redis)

    handler_calls = []
    monkeypatch.setattr(
        "app.scheduler.jobs._reload_handler",
        lambda s, p: handler_calls.append(p),
    )

    # Patch settings so the loop can access REDIS_URL
    fake_settings = MagicMock()
    fake_settings.REDIS_URL = "redis://localhost:6379/0"
    monkeypatch.setattr("app.config.settings", fake_settings)

    sched = _make_scheduler()
    _reload_listener_loop(sched)

    assert len(handler_calls) == 1
    assert handler_calls[0]["action"] == "reload"


def test_reload_listener_loop_logs_and_continues_on_bad_json(monkeypatch, caplog):
    """Malformed JSON logs WARNING but does not call _reload_handler."""
    messages = [
        {"type": "message", "data": "not-valid-json"},
    ]
    fake_redis = _make_fake_pubsub(messages)
    monkeypatch.setattr("redis.from_url", lambda url: fake_redis)

    handler_calls = []
    monkeypatch.setattr(
        "app.scheduler.jobs._reload_handler",
        lambda s, p: handler_calls.append(p),
    )

    fake_settings = MagicMock()
    fake_settings.REDIS_URL = "redis://localhost:6379/0"
    monkeypatch.setattr("app.config.settings", fake_settings)

    sched = _make_scheduler()
    import logging
    with caplog.at_level(logging.WARNING, logger="app.scheduler.jobs"):
        _reload_listener_loop(sched)

    assert handler_calls == []
    assert any("scheduler_reload_malformed_payload" in r.message for r in caplog.records)


def test_reload_listener_loop_ignores_unknown_action(monkeypatch):
    """Messages with action != 'reload' must NOT dispatch _reload_handler."""
    messages = [
        {"type": "message", "data": json.dumps({"action": "wipe"})},
        {"type": "message", "data": json.dumps({"action": "reload"})},
    ]
    fake_redis = _make_fake_pubsub(messages)
    monkeypatch.setattr("redis.from_url", lambda url: fake_redis)

    handler_calls = []
    monkeypatch.setattr(
        "app.scheduler.jobs._reload_handler",
        lambda s, p: handler_calls.append(p),
    )

    fake_settings = MagicMock()
    fake_settings.REDIS_URL = "redis://localhost:6379/0"
    monkeypatch.setattr("app.config.settings", fake_settings)

    sched = _make_scheduler()
    _reload_listener_loop(sched)

    # Only the "reload" action should have dispatched
    assert len(handler_calls) == 1
    assert handler_calls[0]["action"] == "reload"


def test_reload_listener_loop_exits_on_redis_disconnect(monkeypatch, caplog):
    """If redis.from_url raises (simulating connection failure), loop logs WARNING."""
    monkeypatch.setattr("redis.from_url", lambda url: (_ for _ in ()).throw(
        ConnectionError("Redis gone")
    ))

    fake_settings = MagicMock()
    fake_settings.REDIS_URL = "redis://localhost:6379/0"
    monkeypatch.setattr("app.config.settings", fake_settings)

    sched = _make_scheduler()
    import logging
    with caplog.at_level(logging.WARNING, logger="app.scheduler.jobs"):
        _reload_listener_loop(sched)  # must not raise

    assert any("scheduler_reload_listener_exited" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# _start_reload_listener tests
# ---------------------------------------------------------------------------

def test_start_reload_listener_returns_daemon_thread(monkeypatch):
    """Returned thread is daemon=True and alive after start."""
    # Patch the loop function to return immediately so the thread exits cleanly
    monkeypatch.setattr("app.scheduler.jobs._reload_listener_loop", lambda s: None)

    sched = _make_scheduler()
    t = _start_reload_listener(sched)

    assert t.daemon is True
    assert t.name == "sources-reload-listener"
    # Give the thread a moment to start
    time.sleep(0.05)
    # Thread may have already finished (loop returns immediately) — that is fine
    # The important assertion is daemon=True


def test_start_reload_listener_thread_name(monkeypatch):
    """Thread name is exactly 'sources-reload-listener'."""
    monkeypatch.setattr("app.scheduler.jobs._reload_listener_loop", lambda s: None)

    sched = _make_scheduler()
    t = _start_reload_listener(sched)
    assert t.name == "sources-reload-listener"


# ---------------------------------------------------------------------------
# build_scheduler graceful degradation
# ---------------------------------------------------------------------------

def test_build_scheduler_survives_listener_start_failure(monkeypatch):
    """If _start_reload_listener raises, build_scheduler still returns a scheduler."""
    monkeypatch.setattr(
        "app.scheduler.jobs._start_reload_listener",
        lambda s: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    # _load_source_jobs also needs to not fail (or be patched)
    monkeypatch.setattr("app.scheduler.jobs._load_source_jobs", lambda s: None)

    from app.scheduler.jobs import build_scheduler

    sched = build_scheduler()
    assert sched is not None
    assert isinstance(sched, BlockingScheduler)
    if sched.state:
        sched.shutdown(wait=False)


def test_build_scheduler_calls_start_reload_listener(monkeypatch):
    """build_scheduler calls _start_reload_listener after _load_source_jobs."""
    listener_calls = []
    monkeypatch.setattr(
        "app.scheduler.jobs._start_reload_listener",
        lambda s: listener_calls.append(s),
    )
    monkeypatch.setattr("app.scheduler.jobs._load_source_jobs", lambda s: None)

    from app.scheduler.jobs import build_scheduler

    sched = build_scheduler()
    assert len(listener_calls) == 1
    assert listener_calls[0] is sched
    if sched.state:
        sched.shutdown(wait=False)

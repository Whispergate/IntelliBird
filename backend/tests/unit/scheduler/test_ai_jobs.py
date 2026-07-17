"""Unit tests for register_ai_jobs APScheduler wiring — AI-06, AI-07, SCR-04.

Covers:
  - test_register_ai_jobs_adds_three_jobs: exactly 3 add_job calls with correct ids
  - test_digest_cron_06_utc: ai_digest_all trigger is CronTrigger hour=6, minute=0, UTC
  - test_suggestion_expiry_cron_01_utc: ai_suggestion_expiry trigger is hour=1, minute=0, UTC
  - test_nightly_rerank_cron_02_utc: ai_nightly_rerank trigger is hour=2, minute=0, UTC
"""
from __future__ import annotations

import os

# Set env vars before any app module imports.
os.environ.setdefault("SECRET_KEY", "a" * 32 + "deadbeef")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SIGNING_KEY", "b" * 64)

from unittest.mock import MagicMock, call
from apscheduler.triggers.cron import CronTrigger

import pytest


def _make_mock_scheduler():
    """Return a mock scheduler that records add_job calls."""
    scheduler = MagicMock()
    scheduler.add_job = MagicMock()
    return scheduler


def test_register_ai_jobs_adds_three_jobs():
    """register_ai_jobs registers exactly three APScheduler jobs."""
    from app.scheduler.ai_jobs import register_ai_jobs

    scheduler = _make_mock_scheduler()
    register_ai_jobs(scheduler)

    assert scheduler.add_job.call_count == 3, (
        f"Expected 3 add_job calls, got {scheduler.add_job.call_count}"
    )

    # Verify ids.
    job_ids = {c.kwargs.get("id") or c[0][2] for c in scheduler.add_job.call_args_list}
    # Extract id keyword arg from each call.
    call_ids = set()
    for c in scheduler.add_job.call_args_list:
        kwargs = c[1] if c[1] else {}
        call_ids.add(kwargs.get("id"))

    assert "ai_digest_all" in call_ids, f"ai_digest_all not found in {call_ids}"
    assert "ai_suggestion_expiry" in call_ids, f"ai_suggestion_expiry not found in {call_ids}"
    assert "ai_nightly_rerank" in call_ids, f"ai_nightly_rerank not found in {call_ids}"


def test_digest_cron_06_utc():
    """Daily digest job is scheduled at 06:00 UTC."""
    from app.scheduler.ai_jobs import register_ai_jobs

    scheduler = _make_mock_scheduler()
    register_ai_jobs(scheduler)

    # Find the call for ai_digest_all.
    digest_call = None
    for c in scheduler.add_job.call_args_list:
        if c[1].get("id") == "ai_digest_all":
            digest_call = c
            break

    assert digest_call is not None, "ai_digest_all job not registered"

    # Second positional arg is the trigger.
    trigger = digest_call[0][1]  # (func, trigger, ...) positional
    assert isinstance(trigger, CronTrigger), f"Expected CronTrigger, got {type(trigger)}"

    # Extract hour/minute fields from CronTrigger.
    field_map = {f.name: f for f in trigger.fields}
    assert str(field_map["hour"]) == "6", f"Expected hour=6, got {field_map['hour']}"
    assert str(field_map["minute"]) == "0", f"Expected minute=0, got {field_map['minute']}"


def test_suggestion_expiry_cron_01_utc():
    """Suggestion expiry job is scheduled at 01:00 UTC."""
    from app.scheduler.ai_jobs import register_ai_jobs

    scheduler = _make_mock_scheduler()
    register_ai_jobs(scheduler)

    expiry_call = None
    for c in scheduler.add_job.call_args_list:
        if c[1].get("id") == "ai_suggestion_expiry":
            expiry_call = c
            break

    assert expiry_call is not None, "ai_suggestion_expiry job not registered"

    trigger = expiry_call[0][1]
    assert isinstance(trigger, CronTrigger), f"Expected CronTrigger, got {type(trigger)}"

    field_map = {f.name: f for f in trigger.fields}
    assert str(field_map["hour"]) == "1", f"Expected hour=1, got {field_map['hour']}"
    assert str(field_map["minute"]) == "0", f"Expected minute=0, got {field_map['minute']}"


def test_nightly_rerank_cron_02_utc():
    """Nightly AI rerank job is scheduled at 02:00 UTC."""
    from app.scheduler.ai_jobs import register_ai_jobs

    scheduler = _make_mock_scheduler()
    register_ai_jobs(scheduler)

    rerank_call = None
    for c in scheduler.add_job.call_args_list:
        if c[1].get("id") == "ai_nightly_rerank":
            rerank_call = c
            break

    assert rerank_call is not None, "ai_nightly_rerank job not registered"

    trigger = rerank_call[0][1]
    assert isinstance(trigger, CronTrigger), f"Expected CronTrigger, got {type(trigger)}"

    field_map = {f.name: f for f in trigger.fields}
    assert str(field_map["hour"]) == "2", f"Expected hour=2, got {field_map['hour']}"
    assert str(field_map["minute"]) == "0", f"Expected minute=0, got {field_map['minute']}"

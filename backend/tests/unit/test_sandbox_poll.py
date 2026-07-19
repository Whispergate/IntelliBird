"""
SANDBOX-03 - poll actor self-reschedules on incomplete; writes sandbox_reports on complete; timeout after 30 attempts.
Implemented in: backend/app/workers/sandbox.py
"""
import pytest


@pytest.mark.xfail(reason="not yet implemented -")
def test_poll_reschedules_when_provider_returns_none():
    """If provider.poll() returns None (still running), actor re-queues itself with next backoff delay."""
    raise NotImplementedError


@pytest.mark.xfail(reason="not yet implemented -")
def test_poll_writes_complete_on_success():
    """When provider.poll() returns a SandboxReport, status flips to 'complete' and report_json is written."""
    raise NotImplementedError


@pytest.mark.xfail(reason="not yet implemented -")
def test_poll_marks_timeout_after_30_attempts():
    """After MAX_POLL_ATTEMPTS=30 with None each time, status is set to 'timeout'."""
    raise NotImplementedError

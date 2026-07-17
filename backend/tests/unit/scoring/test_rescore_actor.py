"""Unit tests for the rescore_project Dramatiq actor — SCR-02.

These tests verify:
  1. The actor is registered on the ``scoring`` queue with the correct options.
  2. Sending a message creates a Dramatiq Message with the correct queue_name.
  3. Calling the actor body directly with an invalid UUID raises ValueError immediately.

DB integration (actual rescore_project_events execution) is deferred to plan 15-07
where the API trigger and integration fixtures land.
"""
from __future__ import annotations

import os

# Pydantic-settings singleton loads at import time — bootstrap required env vars
# before any app.* import to prevent ValidationError at collection time.
os.environ.setdefault("SECRET_KEY", "x" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "y" * 64)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

import dramatiq
import pytest
from dramatiq.brokers.stub import StubBroker

# Import the module-under-test once after env vars are set.
from app.workers.scoring import rescore_project


# ---------------------------------------------------------------------------
# Module-level fixture: switch to StubBroker for send tests.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _stub_broker():
    """Replace the global Dramatiq broker with a StubBroker for the test run.

    The actor is re-bound to the stub broker so .send() enqueues locally.
    """
    stub = StubBroker()
    stub.declare_queue("scoring")
    dramatiq.set_broker(stub)
    # Re-bind the actor to the new broker so .send() routes to our stub.
    rescore_project.broker = stub
    yield stub
    # Restore the actor to a clean state after test (no global RedisBroker reconnect).
    dramatiq.set_broker(StubBroker())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_rescore_project_actor_registered_on_scoring_queue() -> None:
    """rescore_project actor declares queue_name='scoring' and max_retries=2."""
    assert rescore_project.queue_name == "scoring", (
        f"Expected queue_name='scoring', got {rescore_project.queue_name!r}"
    )
    assert rescore_project.options.get("max_retries") == 2, (
        f"Expected max_retries=2, got {rescore_project.options.get('max_retries')!r}"
    )


def test_rescore_project_send_enqueues_to_scoring_queue(_stub_broker: StubBroker) -> None:
    """rescore_project.send() places exactly one message in the 'scoring' queue."""
    rescore_project.send("00000000-0000-0000-0000-000000000001")

    queue = _stub_broker.queues.get("scoring")
    assert queue is not None, "scoring queue was not declared"
    assert queue.qsize() == 1, (
        f"Expected 1 message in scoring queue, got {queue.qsize()}"
    )


def test_rescore_project_handles_invalid_uuid() -> None:
    """Calling the actor body directly with a non-UUID string raises ValueError."""
    with pytest.raises(ValueError):
        rescore_project("not-a-uuid")

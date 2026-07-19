"""webhook_dispatch_tick Dramatiq actor - HOOK-02, HOOK-07, HOOK-08.

: max_retries=0 - we own the retry policy inline (30/60/120s with
cursor-advance semantics). Dramatiq middleware retry would re-queue the
whole tick and potentially double-dispatch.

: the actor body is wrapped in run_dispatch_tick's broad
try/except so Dramatiq never re-queues on uncaught exceptions even when
max_retries=0.
"""
from __future__ import annotations

import dramatiq
import structlog

from app.services.webhook_dispatcher import run_dispatch_tick

log = structlog.get_logger(__name__)


@dramatiq.actor(queue_name="webhooks", max_retries=0)
def webhook_dispatch_tick(_token: str = "tick") -> None:
    """Fired every 60s by APScheduler.."""
    log.info("webhook_dispatch_tick_actor_fired")
    run_dispatch_tick()

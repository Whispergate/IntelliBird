"""Fire-and-forget Redis pub/sub publisher — signals scheduler to reload source jobs.

Consumers: Plan 02 CRUD router (POST/PATCH/DELETE handlers).
Listener:  Plan 06 scheduler listener (app.scheduler.jobs, daemon thread).

Pitfall 8: DELETE payloads must include {feed_type, source_id} so the listener
can call scheduler.remove_job() on the orphaned APScheduler job.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import redis as redis_lib

from app.config import settings

logger = logging.getLogger(__name__)

RELOAD_CHANNEL: str = "intellibird:sources:changed"


def publish_sources_changed(
    action: str = "reload",
    *,
    deleted: list[dict[str, Any]] | None = None,
) -> None:
    """Publish a sources-changed event. Fire-and-forget — never raises."""
    payload: dict[str, Any] = {"action": action}
    if deleted:
        payload["deleted"] = deleted
    try:
        r = redis_lib.from_url(settings.REDIS_URL)
        try:
            r.publish(RELOAD_CHANNEL, json.dumps(payload))
        finally:
            r.close()
    except Exception as e:  # noqa: BLE001 — deliberate fire-and-forget
        logger.warning(
            "source_events_publish_failed channel=%s action=%s error=%s",
            RELOAD_CHANNEL, action, e,
        )

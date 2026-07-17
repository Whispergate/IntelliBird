"""Dramatiq broker — Redis. Imported by workers and by the api admin endpoint.

IMPORTANT: `app.config` is imported INSIDE `_build_broker` so that a bare
`import app.workers.broker` (used e.g. by smoke tests and by's api
startup wiring) does not hard-require `app.config` at module-load time.
Plans 03 and 04 run in the same wave and their execution order is
undefined; this keeps module import order-free.
"""
from __future__ import annotations

import dramatiq
from dramatiq.brokers.redis import RedisBroker

_broker: RedisBroker | None = None


def _build_broker() -> RedisBroker:
    global _broker
    if _broker is None:
        from app.config import settings  # imported lazily — see module docstring
        _broker = RedisBroker(url=settings.REDIS_URL)
        dramatiq.set_broker(_broker)
    return _broker


def get_broker() -> RedisBroker:
    """Public accessor — builds the broker on first call."""
    return _build_broker()


# Configure JSON logging at dramatiq worker startup (SYS-04). The dramatiq
# CLI imports this module before any actor runs; configure_logging wipes
# the root handlers + installs the structlog ProcessorFormatter bridge so
# stdlib logging.getLogger(__name__) in rss.py / nvd.py / taxii.py produces
# JSON lines, matching the api's RequestLogMiddleware output.
from app.logging import configure_logging  # noqa: E402
configure_logging()

# Eagerly build + set broker BEFORE actor modules import. Dramatiq CLI loads
# this module and expects the global broker set at module-load time; otherwise
# @dramatiq.actor registrations bind to the default (localhost Redis) broker.
_build_broker()

# Register actor modules — decorators now bind to the configured RedisBroker.
from app.workers import bootstrap  # noqa: E402,F401
from app.workers import rss  # noqa: E402,F401
from app.workers import nvd  # noqa: E402,F401
from app.workers import taxii  # noqa: E402,F401
from app.services import geo_backfill  # noqa: E402,F401 — MAP-05 maintenance actor
from app.workers import webhook_dispatcher_actor  # noqa: E402,F401 — HOOK-02
# Register EASM actors
from app.workers import easm  # noqa: E402,F401
# Register Brand Protection actor (BRP-02)
from app.workers import brand  # noqa: E402,F401
# Register Scoring rescore actor (SCR-02)
from app.workers import scoring  # noqa: E402,F401
# Register AI actors (AI-02,AI-06,AI-07 + AI-08) — ai queue
from app.workers import ai  # noqa: E402,F401
# Register TIBER report export actor (TIBER-03) — reports queue
from app.workers import reports  # noqa: E402,F401
# Register IOC actors (IOC-07) — ingest queue
from app.workers import iocs as _iocs_actor  # noqa: E402,F401
# Register dark-web collection actors (DARK-01..07) — darkweb queue
from app.workers import tor_html as _tor_html_actor  # noqa: E402,F401
from app.workers import paste as _paste_actor  # noqa: E402,F401
from app.workers import telegram as _telegram_actor  # noqa: E402,F401
# Register Sandbox + YARA actors (SANDBOX-02..05, YARA-02) — sandbox queue
from app.workers import sandbox as _sandbox_actor  # noqa: E402,F401

"""structlog configuration — JSON lines for production.

Call configure_logging() once at process startup. Downstream code uses:
    import structlog
    log = structlog.get_logger(__name__)
    log.info("event_name", key=value, ...)

Stdlib `logging.getLogger(__name__)` records (from feed workers, SQLAlchemy,
uvicorn, etc.) are bridged through the same JSON processor chain via
`structlog.stdlib.ProcessorFormatter` so every log line is machine-parseable JSON.
"""
from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Set up stdlib logging + structlog with unified JSON rendering.

    Bridges stdlib `logging` records through structlog's processor chain so
    worker modules using `logging.getLogger(__name__)` (rss/nvd/taxii) produce
    the same JSON line shape as `structlog.get_logger(__name__)`. SYS-04.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Shared processor chain for BOTH structlog loggers AND stdlib bridge.
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            # ProcessorFormatter.wrap_for_formatter tells ProcessorFormatter
            # to finish the render when the record arrives via stdlib. For
            # native structlog calls it's a pass-through to JSONRenderer below.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # stdlib handler renders all records (structlog-originated + plain stdlib)
    # through shared_processors then JSONRenderer.
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    # Wipe any handlers installed by a previous configure call (e.g. uvicorn)
    root.handlers[:] = [handler]
    root.setLevel(log_level)

"""FastAPI application factory for IntelliBird M1 api service.

Startup sequence:
  1. app.config.settings is imported at module load → pydantic validator
     rejects placeholder SECRET_KEY (plan 04) before any socket opens.
  2. configure_logging() sets structlog JSON output.
  3. Log a prominent HOST-binding banner (D-18). If HOST != 127.0.0.1,
     the log line is ERROR level so operators notice.
  4. /healthz responds 200 so docker compose healthcheck passes.
"""
from __future__ import annotations

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.logging import configure_logging
from app.middleware.request_log import RequestLogMiddleware
from app.routers.admin.attack import router as admin_attack_router
from app.routers.admin.sources import router as admin_sources_router
from app.routers.admin.source_templates import router as admin_source_templates_router
from app.routers.admin.webhooks import router as admin_webhooks_router
from app.routers.events import router as events_router
from app.routers.graph import router as graph_router
from app.routers.presets import router as presets_router
from app.routers.system import router as system_router
from app.routers.tags import router as tags_router
from app.workers import broker as _broker  # noqa: F401 — registers actors

configure_logging()
log = structlog.get_logger(__name__)


def _startup_bind_banner() -> None:
    if settings.HOST == "127.0.0.1":
        log.info("startup_bind_loopback", host=settings.HOST, port=settings.PORT)
    else:
        log.error(
            "startup_bind_non_loopback",
            host=settings.HOST, port=settings.PORT,
            warning=(
                "IntelliBird M1 exposed beyond loopback and has NO AUTHENTICATION. "
                "For trusted internal networks only. Auth lands in M2."
            ),
        )


def create_app() -> FastAPI:
    _startup_bind_banner()

    app = FastAPI(
        title="IntelliBird API",
        version="0.1.0",
        description=(
            "IntelliBird M1 — self-hosted team/SOC threat intelligence platform. "
            "Aggregates cyber and world-event feeds into Red/Blue team dashboards."
        ),
        openapi_tags=[
            {"name": "events", "description": "Intel event list, detail, and filters"},
            {"name": "tags", "description": "Free-text tag mutation on events"},
            {"name": "presets", "description": "Saved filter presets"},
            {"name": "graph", "description": "ATT&CK graph traversal for events"},
            {"name": "admin", "description": "Source registry and feed management"},
            {"name": "webhooks", "description": "Outbound webhook alerts (Slack/Teams/Discord/Generic)"},
        ],
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    # RequestLogMiddleware added AFTER CORSMiddleware so it is the outermost
    # wrapper (Starlette insert(0) means last-added = first-to-run = outermost).
    app.add_middleware(RequestLogMiddleware)

    app.include_router(system_router)
    app.include_router(admin_attack_router)
    app.include_router(admin_sources_router, prefix="/api")
    app.include_router(admin_source_templates_router, prefix="/api")
    app.include_router(admin_webhooks_router, prefix="/api")
    app.include_router(events_router, prefix="/api")
    app.include_router(tags_router, prefix="/api")
    app.include_router(presets_router, prefix="/api")
    app.include_router(graph_router, prefix="/api")

    return app


app = create_app()

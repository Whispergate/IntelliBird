"""FastAPI application factory for IntelliBird api service.

Startup sequence:
 1. app.config.settings is imported at module load → pydantic validator
    rejects placeholder SECRET_KEY before any socket opens.
 2. configure_logging sets structlog JSON output.
 3. Log a prominent HOST-binding banner. If HOST != 127.0.0.1,
    the log line is ERROR level so operators notice.
 4. FastAPI lifespan runs _run_startup_decrypt_check — canary seed/verify.
 5. AuthMiddleware stub sits between CORSMiddleware and RequestLogMiddleware.
 6. /healthz responds 200 so docker compose healthcheck passes.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Literal

import structlog
from cryptography.exceptions import InvalidTag
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

import app.state as _app_state
from app.config import settings
from app.crypto import decrypt_credentials, encrypt_credentials
from app.database import async_session_factory
from app.logging import configure_logging
from app.middleware.auth import AuthMiddleware
from app.middleware.request_log import RequestLogMiddleware
from app.models.sources import Source
from app.routers.admin.attack import router as admin_attack_router
from app.routers.admin.maintenance import router as admin_maintenance_router
from app.routers.admin.monitoring import router as admin_monitoring_router
from app.routers.admin.rekey import router as admin_rekey_router
from app.routers.admin.setup import router as admin_setup_router
from app.routers.admin.users import router as admin_users_router
from app.routers.ai import router as ai_router
from app.routers.attack import router as attack_router
from app.routers.admin.ai_health import router as admin_ai_health_router
from app.routers.admin.ai_jobs import router as admin_ai_jobs_router
from app.routers.assets import router as assets_router
from app.routers.auth import router as auth_router
from app.routers.admin.sources import router as admin_sources_router
from app.routers.admin.source_templates import router as admin_source_templates_router
from app.routers.admin.webhooks import router as admin_webhooks_router
from app.routers.events import router as events_router
from app.routers.graph import router as graph_router
from app.routers.graph import projects_graph_router
from app.routers.presets import router as presets_router
from app.routers.easm import router as easm_router
from app.routers.easm import safelist_router as easm_safelist_router
from app.routers.brand import router as brand_router
from app.routers.projects import router as projects_router
from app.routers.projects import compare_router as projects_compare_router
from app.routers.system import router as system_router
from app.routers.tags import router as tags_router
from app.routers.tiber import router as tiber_router
from app.workers import broker as _broker  # noqa: F401 — registers actors

configure_logging()
log = structlog.get_logger(__name__)

CANARY_ID: str = "00000000-0000-0000-0000-000000000000"
CANARY_PLAINTEXT: dict = {"canary": "intellibird-v1"}


def _startup_bind_banner() -> None:
    if settings.HOST == "127.0.0.1":
        log.info("startup_bind_loopback", host=settings.HOST, port=settings.PORT)
    else:
        log.error(
            "startup_bind_non_loopback",
            host=settings.HOST, port=settings.PORT,
            warning=(
                "IntelliBird exposed beyond loopback and has NO AUTHENTICATION. "
                "For trusted internal networks only. Auth lands in Phase 9."
            ),
        )


def _startup_auth_banner() -> None:
    """Log AUTH_ENABLED state + presence of JWT_SIGNING_KEY + SSO_ISSUER_URL at startup.

    Never logs the key itself — only boolean "configured" indicators.
    """
    sso_configured = bool(settings.SSO_ISSUER_URL and settings.SSO_CLIENT_ID)
    log.info(
        "startup_auth_status",
        auth_enabled=settings.AUTH_ENABLED,
        jwt_signing_key_len=len(settings.JWT_SIGNING_KEY),
        sso_configured=sso_configured,
        sso_issuer_present=bool(settings.SSO_ISSUER_URL),
    )


async def _run_startup_decrypt_check() -> Literal["ok", "failed", "unknown"]:
    """Canary-based decrypt sanity check — INFRA-03.

    The canary row (id=CANARY_ID) is inserted by migration 007 with
    credentials_enc=NULL. First startup after the migration seeds the blob;
    subsequent startups verify round-trip under the current SECRET_KEY.
    """
    try:
        async with async_session_factory() as session:
            row = (
                await session.execute(
                    select(Source).where(Source.id == uuid.UUID(CANARY_ID))
                )
            ).scalar_one_or_none()
            if row is None:
                log.warning(
                    "startup_decrypt_check_skipped",
                    reason="canary_row_missing",
                )
                return "unknown"
            if row.credentials_enc is None:
                # First startup after migration 007 — seed the blob.
                row.credentials_enc = encrypt_credentials(
                    settings.SECRET_KEY, CANARY_PLAINTEXT
                )
                await session.commit()
                log.info("startup_canary_seeded")
                return "ok"
            try:
                creds = decrypt_credentials(settings.SECRET_KEY, row.credentials_enc)
            except (InvalidTag, Exception) as exc:
                log.critical(
                    "startup_decrypt_check_failed",
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                return "failed"
            if creds != CANARY_PLAINTEXT:
                log.critical(
                    "startup_decrypt_check_wrong_plaintext",
                    got_keys=sorted(creds.keys()),
                )
                return "failed"
            log.info("startup_decrypt_check_ok")
            return "ok"
    except Exception as exc:  # DB unreachable, etc.
        log.critical(
            "startup_decrypt_check_exception",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return "failed"


@asynccontextmanager
async def lifespan(fastapi_instance: FastAPI):
    _app_state.decrypt_check = await _run_startup_decrypt_check()
    yield
    # no teardown


def create_app() -> FastAPI:
    _startup_bind_banner()
    _startup_auth_banner()  # NEW — AUTH-03

    fastapi_app = FastAPI(
        title="IntelliBird API",
        version="0.1.0",
        description=(
            "IntelliBird self-hosted team/SOC threat intelligence platform. "
            "Aggregates cyber and world-event feeds into Red/Blue team dashboards."
        ),
        openapi_tags=[
            {"name": "events", "description": "Intel event list, detail, and filters"},
            {"name": "tags", "description": "Free-text tag mutation on events"},
            {"name": "presets", "description": "Saved filter presets"},
            {"name": "graph", "description": "ATT&CK graph traversal for events"},
            {"name": "admin", "description": "Source registry and feed management"},
            {"name": "webhooks", "description": "Outbound webhook alerts"},
            {"name": "system", "description": "Healthz + system status"},
        ],
        lifespan=lifespan,
    )

    # ORDER: last add_middleware = outermost = first to run on request.
    # Desired outer→inner: RequestLog → Auth → CORS → route.
    # Call order: CORS, Auth, RequestLog (RequestLog MUST be last/outermost).
    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    fastapi_app.add_middleware(AuthMiddleware)
    fastapi_app.add_middleware(RequestLogMiddleware)

    fastapi_app.include_router(system_router)
    fastapi_app.include_router(admin_attack_router)
    fastapi_app.include_router(admin_sources_router, prefix="/api")
    fastapi_app.include_router(admin_source_templates_router, prefix="/api")
    fastapi_app.include_router(admin_webhooks_router, prefix="/api")
    fastapi_app.include_router(admin_rekey_router, prefix="/api")
    fastapi_app.include_router(admin_setup_router, prefix="/api")
    fastapi_app.include_router(admin_users_router, prefix="/api")
    fastapi_app.include_router(admin_monitoring_router, prefix="/api")
    fastapi_app.include_router(admin_maintenance_router, prefix="/api")
    fastapi_app.include_router(auth_router, prefix="/api")
    fastapi_app.include_router(events_router, prefix="/api")
    fastapi_app.include_router(tags_router, prefix="/api")
    fastapi_app.include_router(presets_router, prefix="/api")
    fastapi_app.include_router(graph_router, prefix="/api")
    # projects_graph_router MUST be registered before projects_router so /api/projects/{id}/graph
    # resolves on the graph router, not on the projects_router's /{project_id} catchall.
    fastapi_app.include_router(projects_graph_router, prefix="/api")
    # compare_router MUST be registered before projects_router so /api/projects/compare
    # resolves on compare_router first, not on projects_router's /{project_id} catchall.
    fastapi_app.include_router(projects_compare_router, prefix="/api")
    fastapi_app.include_router(projects_router, prefix="/api")
    # EASM: safelist_router before easm_router — /api/easm/safelist must not collide
    # with /api/projects/.../easm/... path (no collision, but consistent with Phase 10
    # compare_router-before-projects_router ordering for sibling routers).
    fastapi_app.include_router(easm_safelist_router, prefix="/api")
    fastapi_app.include_router(easm_router, prefix="/api")
    fastapi_app.include_router(brand_router, prefix="/api")
    fastapi_app.include_router(attack_router, prefix="/api")
    fastapi_app.include_router(ai_router, prefix="/api")
    fastapi_app.include_router(admin_ai_health_router, prefix="/api")
    fastapi_app.include_router(admin_ai_jobs_router, prefix="/api")
    # Assets router has absolute prefix baked in (/api/projects/{id}/assets)
    fastapi_app.include_router(assets_router)
    # TIBER report generation router — absolute prefix /api/projects/{id}/tiber
    fastapi_app.include_router(tiber_router)

    return fastapi_app


app = create_app()

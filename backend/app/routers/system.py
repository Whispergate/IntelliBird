"""GET /healthz and GET /api/system/status — FN signal source + INFRA-03/04."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

import app.state
from app.config import settings

VERSION = "0.1.0"

DECRYPT_FAILED_WARNING = (
    "Encrypted source credentials cannot be read under the current SECRET_KEY. "
    "Run POST /api/admin/rekey-credentials with REKEY_FROM_SECRET set to the "
    "previous key."
)

router = APIRouter()


class HealthzResponse(BaseModel):
    status: str


class SystemStatusResponse(BaseModel):
    auth_enabled: bool
    host: str
    host_loopback_only: bool
    version: str
    warning: str | None
    decrypt_check: Literal["ok", "failed", "unknown"] = "unknown"


@router.get("/healthz", response_model=HealthzResponse, tags=["system"])
def healthz() -> HealthzResponse:
    return HealthzResponse(status="ok")


@router.get("/api/system/status", response_model=SystemStatusResponse, tags=["system"])
def get_status() -> SystemStatusResponse:
    loopback = settings.HOST == "127.0.0.1"
    decrypt_state = app.state.decrypt_check

    # Precedence: decrypt failure takes priority over loopback warning.
    if decrypt_state == "failed":
        warning: str | None = DECRYPT_FAILED_WARNING
    elif not loopback:
        warning = (
            "This IntelliBird instance is exposed beyond loopback and has "
            "NO AUTHENTICATION — for trusted internal networks only. "
            "Auth lands in Phase 9."
        )
    else:
        warning = None

    return SystemStatusResponse(
        auth_enabled=settings.AUTH_ENABLED,
        host=settings.HOST,
        host_loopback_only=loopback,
        version=VERSION,
        warning=warning,
        decrypt_check=decrypt_state,
    )

"""GET /healthz and GET /api/system/status — FN signal source + INFRA-03/04."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.state
from app.config import settings
from app.database import get_session
from app.models.users import User

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


class SetupStatusResponse(BaseModel):
    setup_token_set: bool
    user_count: int


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


@router.get(
    "/api/system/setup-status",
    response_model=SetupStatusResponse,
    tags=["system"],
)
async def get_setup_status(
    db: AsyncSession = Depends(get_session),
) -> SetupStatusResponse:
    """Pre-auth probe for the /setup UI — exposes SETUP_TOKEN presence and
    user count so the first-admin form knows whether to render or redirect.
    """
    user_count = int((await db.execute(select(func.count(User.id)))).scalar_one())
    return SetupStatusResponse(
        setup_token_set=bool(settings.SETUP_TOKEN),
        user_count=user_count,
    )

"""GET /healthz and GET /api/system/status — FND-04 signal source."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings

VERSION = "0.1.0"

router = APIRouter()


class HealthzResponse(BaseModel):
    status: str


class SystemStatusResponse(BaseModel):
    auth_enabled: bool
    host: str
    host_loopback_only: bool
    version: str
    warning: str | None


@router.get("/healthz", response_model=HealthzResponse, tags=["system"])
def healthz() -> HealthzResponse:
    return HealthzResponse(status="ok")


@router.get("/api/system/status", response_model=SystemStatusResponse, tags=["system"])
def get_status() -> SystemStatusResponse:
    loopback = settings.HOST == "127.0.0.1"
    warning = None
    if not loopback:
        warning = (
            "This IntelliBird instance is exposed beyond loopback and has "
            "NO AUTHENTICATION — for trusted internal networks only. "
            "Auth lands in M2."
        )
    return SystemStatusResponse(
        auth_enabled=False,
        host=settings.HOST,
        host_loopback_only=loopback,
        version=VERSION,
        warning=warning,
    )

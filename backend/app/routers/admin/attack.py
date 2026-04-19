"""POST /admin/attack/refresh — on-demand ATT&CK catalog refresh.

AUTH-02 (Phase 9): endpoint guarded by Depends(require_admin).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from app.middleware.auth import require_admin
from app.security.jwt import AuthUser
from app.workers import broker as _broker  # noqa: F401 — registers actor
from app.workers.bootstrap import bootstrap_attack

router = APIRouter(prefix="/admin/attack", tags=["admin"])


class RefreshResponse(BaseModel):
    enqueued: bool
    message_id: str | None


@router.post("/refresh", status_code=status.HTTP_202_ACCEPTED,
             response_model=RefreshResponse)
def refresh_attack(
    _admin: AuthUser = Depends(require_admin),
) -> RefreshResponse:
    """Enqueue the ATT&CK bootstrap actor. Returns 202 Accepted."""
    msg = bootstrap_attack.send()
    return RefreshResponse(enqueued=True, message_id=getattr(msg, "message_id", None))

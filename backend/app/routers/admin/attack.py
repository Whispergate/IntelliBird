"""POST /admin/attack/refresh — on-demand ATT&CK catalog refresh (unauth in M1)."""
from __future__ import annotations

from fastapi import APIRouter, status
from pydantic import BaseModel

from app.workers import broker as _broker  # noqa: F401 — registers actor
from app.workers.bootstrap import bootstrap_attack

router = APIRouter(prefix="/admin/attack", tags=["admin"])


class RefreshResponse(BaseModel):
    enqueued: bool
    message_id: str | None


@router.post("/refresh", status_code=status.HTTP_202_ACCEPTED,
             response_model=RefreshResponse)
def refresh_attack() -> RefreshResponse:
    """Enqueue the ATT&CK bootstrap actor. Returns 202 Accepted.

    Unauthenticated in M1 (CONTEXT D-13). M2 adds the auth dependency.
    """
    msg = bootstrap_attack.send()
    return RefreshResponse(enqueued=True, message_id=getattr(msg, "message_id", None))

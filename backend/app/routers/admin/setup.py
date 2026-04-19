"""POST /api/admin/setup — first-admin bootstrap, SETUP_TOKEN-gated (pre-auth).

AUTH-01.

Mirrors backend/app/routers/admin/rekey.py: same X-Setup-Token header gate so the operator
flow is identical. Endpoint is pre-auth (EXEMPT_PATHS in AuthMiddleware).

Idempotency: returns 409 when any user already exists — the "/setup" UI page also renders the
already-complete state when this 409 fires.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models.users import User
from app.schemas.users import SetupRequest, SetupResponse
from app.security.passwords import hash_password

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


def _require_setup_token(
    x_setup_token: str | None = Header(default=None, alias="X-Setup-Token"),
) -> None:
    """Identical gate to rekey.py — symmetric operator UX."""
    if not settings.SETUP_TOKEN or x_setup_token != settings.SETUP_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing setup token",
        )


@router.post(
    "/setup",
    response_model=SetupResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        403: {"description": "Invalid or missing X-Setup-Token"},
        409: {"description": "Setup already complete — a user already exists"},
        422: {"description": "Body validation failure (password < 12 chars)"},
    },
)
async def setup_first_admin(
    body: SetupRequest,
    _: None = Depends(_require_setup_token),
    db: AsyncSession = Depends(get_session),
) -> SetupResponse:
    # Idempotency: any existing user blocks setup.
    count = (await db.execute(select(func.count(User.id)))).scalar_one()
    if int(count) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="setup_already_complete",
        )

    u = User(
        username=body.username,
        password_hash=hash_password(body.password),
        oidc_sub=None,
        role="Admin",
        dashboard_roles=["red", "blue"],
        enabled=True,
        must_change_password=False,
        token_version=0,
    )
    db.add(u)
    try:
        await db.commit()
        await db.refresh(u)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="username_exists",
        )

    log.info("admin_setup_completed", user_id=str(u.id), username=u.username)
    return SetupResponse(
        id=str(u.id),
        username=u.username,
        role=u.role,
        dashboard_roles=list(u.dashboard_roles or []),
        must_change_password=u.must_change_password,
    )

"""POST/GET/PATCH /api/admin/users + POST /api/admin/users/{id}/unlock.

AUTH-01, AUTH-02. Every endpoint guarded by Depends(require_admin).

Admin-created users always start with:
  password_hash = hash_password(body.initial_password)
  must_change_password = True   (forces /change-password on first login)
  enabled = True
  token_version = 0
  oidc_sub = NULL  (local account)

Admin role implicitly gets dashboard_roles=[red,blue] — enforced on both create and update.

Disabling a user (enabled=false) bumps token_version — every outstanding access+refresh
token for that user fails the middleware token_version check on next request. Also clears
Redis lockout keys so a re-enable doesn't inherit a stale lock.
"""
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.middleware.auth import require_admin
from app.models.users import User
from app.schemas.users import UserCreate, UserResponse, UserUpdate
from app.security.jwt import AuthUser
from app.security.lockout import admin_unlock, is_locked
from app.security.passwords import hash_password

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/admin/users", tags=["admin"])


async def _redis_client():
    import redis.asyncio as aioredis
    return aioredis.from_url(settings.REDIS_URL)


def _normalise_admin_dashboards(role: str, dashboard_roles: list[str]) -> list[str]:
    """Admin always gets both dashboards regardless of body input (CONTEXT.md)."""
    if role == "Admin":
        return ["red", "blue"]
    return list(dashboard_roles)


async def _hydrate(u: User, locked: bool) -> UserResponse:
    return UserResponse(
        id=str(u.id),
        username=u.username,
        role=u.role,
        dashboard_roles=list(u.dashboard_roles or []),
        enabled=bool(u.enabled),
        must_change_password=bool(u.must_change_password),
        locked=locked,
        last_login_at=u.last_login_at,
        created_at=u.created_at,
    )


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(
    body: UserCreate,
    _admin: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> UserResponse:
    dashboards = _normalise_admin_dashboards(body.role, body.dashboard_roles)
    u = User(
        username=body.username,
        password_hash=hash_password(body.initial_password),
        oidc_sub=None,
        role=body.role,
        dashboard_roles=dashboards,
        enabled=True,
        must_change_password=True,
        token_version=0,
    )
    db.add(u)
    try:
        await db.commit()
        await db.refresh(u)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="username_exists")
    log.info("admin_user_created", user_id=str(u.id), username=u.username, role=u.role)
    return await _hydrate(u, locked=False)


@router.get("", response_model=list[UserResponse])
async def list_users(
    _admin: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> list[UserResponse]:
    rows = (await db.execute(
        select(User).order_by(User.created_at.desc())
    )).scalars().all()

    redis = await _redis_client()
    try:
        result: list[UserResponse] = []
        for u in rows:
            locked, _ = await is_locked(redis, u.username)
            result.append(await _hydrate(u, locked=locked))
        return result
    finally:
        await redis.aclose()


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    _admin: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> UserResponse:
    u = (await db.execute(
        select(User).where(User.id == user_id)
    )).scalar_one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="user_not_found")

    if body.role is not None:
        u.role = body.role

    if body.dashboard_roles is not None:
        u.dashboard_roles = list(body.dashboard_roles)

    # Admin always ends up with both — applied after both explicit updates above.
    u.dashboard_roles = _normalise_admin_dashboards(u.role, u.dashboard_roles or [])

    if body.enabled is not None and body.enabled != u.enabled:
        u.enabled = body.enabled
        # Disabling: bump token_version -> all outstanding tokens invalidated.
        if body.enabled is False:
            u.token_version = (u.token_version or 0) + 1
            redis = await _redis_client()
            try:
                await admin_unlock(redis, u.username)
            finally:
                await redis.aclose()

    await db.commit()
    await db.refresh(u)

    redis = await _redis_client()
    try:
        locked, _ = await is_locked(redis, u.username)
    finally:
        await redis.aclose()

    log.info(
        "admin_user_updated",
        user_id=str(u.id),
        role=u.role,
        enabled=u.enabled,
    )
    return await _hydrate(u, locked=locked)


@router.post("/{user_id}/unlock", status_code=204)
async def unlock_user(
    user_id: uuid.UUID,
    _admin: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    u = (await db.execute(
        select(User).where(User.id == user_id)
    )).scalar_one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="user_not_found")
    redis = await _redis_client()
    try:
        await admin_unlock(redis, u.username)
    finally:
        await redis.aclose()
    log.info("admin_user_unlocked", user_id=str(u.id), username=u.username)

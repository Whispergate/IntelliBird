"""MISP config CRUD router - MISP-01.

Endpoints at /api/projects/{project_id}/misp (Lead+ role required):
  GET    /                → MispConfigRead | 404
  PUT    /                → MispConfigRead (upsert: create or full replace)
  PATCH  /                → MispConfigRead (partial update)
  DELETE /                → 204
  POST   /test-connection → MispTestConnectionResponse
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crypto import encrypt_credentials
from app.database import get_session
from app.middleware.auth import require_auth
from app.models.misp import MispConfig
from app.schemas.misp import (
    MispConfigCreate,
    MispConfigRead,
    MispConfigUpdate,
    MispTestConnectionRequest,
    MispTestConnectionResponse,
)
from app.security.jwt import AuthUser

log = logging.getLogger(__name__)

router = APIRouter(tags=["misp"])

_LEAD_RANK = 3  # PROJECT_ROLE_RANK["Lead"]


# ---------------------------------------------------------------------------
# RBAC helpers
# ---------------------------------------------------------------------------


def _is_lead_or_above(user: AuthUser) -> bool:
    """Return True when user has Lead+ on any project, or is a global Admin."""
    if user.role == "Admin":
        return True
    pm: dict[str, int] = getattr(user, "project_memberships", None) or {}
    return any(rank >= _LEAD_RANK for rank in pm.values())


def _require_lead_or_above(user: AuthUser = Depends(require_auth)) -> AuthUser:
    if not _is_lead_or_above(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient_role")
    return user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_read(cfg: MispConfig) -> MispConfigRead:
    """Convert ORM row to response schema, masking the encrypted API key."""
    return MispConfigRead(
        id=cfg.id,
        project_id=cfg.project_id,
        url=cfg.url,
        pull_tags=cfg.pull_tags or [],
        push_types=cfg.push_types or [],
        enabled=cfg.enabled,
        ssl_verify=cfg.ssl_verify,
        api_key_masked="***",
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/misp",
    response_model=MispConfigRead,
    summary="Get MISP config for project",
)
async def get_misp_config(
    project_id: uuid.UUID,
    user: AuthUser = Depends(_require_lead_or_above),
    db: AsyncSession = Depends(get_session),
) -> MispConfigRead:
    result = await db.execute(
        select(MispConfig).where(MispConfig.project_id == project_id)
    )
    cfg = result.scalar_one_or_none()
    if cfg is None:
        raise HTTPException(status_code=404, detail="misp_config_not_found")
    return _to_read(cfg)


@router.put(
    "/projects/{project_id}/misp",
    response_model=MispConfigRead,
    summary="Create or replace MISP config (upsert)",
)
async def upsert_misp_config(
    project_id: uuid.UUID,
    body: MispConfigCreate,
    user: AuthUser = Depends(_require_lead_or_above),
    db: AsyncSession = Depends(get_session),
) -> MispConfigRead:
    api_key_enc = encrypt_credentials(settings.SECRET_KEY, {"api_key": body.api_key})

    result = await db.execute(
        select(MispConfig).where(MispConfig.project_id == project_id)
    )
    cfg = result.scalar_one_or_none()

    if cfg is None:
        cfg = MispConfig(
            project_id=project_id,
            url=str(body.url),
            api_key_enc=api_key_enc,
            pull_tags=body.pull_tags,
            push_types=body.push_types,
            enabled=body.enabled,
            ssl_verify=body.ssl_verify,
        )
        db.add(cfg)
    else:
        cfg.url = str(body.url)
        cfg.api_key_enc = api_key_enc
        cfg.pull_tags = body.pull_tags
        cfg.push_types = body.push_types
        cfg.enabled = body.enabled
        cfg.ssl_verify = body.ssl_verify

    await db.commit()
    await db.refresh(cfg)
    return _to_read(cfg)


@router.patch(
    "/projects/{project_id}/misp",
    response_model=MispConfigRead,
    summary="Partial update MISP config",
)
async def patch_misp_config(
    project_id: uuid.UUID,
    body: MispConfigUpdate,
    user: AuthUser = Depends(_require_lead_or_above),
    db: AsyncSession = Depends(get_session),
) -> MispConfigRead:
    result = await db.execute(
        select(MispConfig).where(MispConfig.project_id == project_id)
    )
    cfg = result.scalar_one_or_none()
    if cfg is None:
        raise HTTPException(status_code=404, detail="misp_config_not_found")

    if body.url is not None:
        cfg.url = str(body.url)
    if body.api_key is not None:
        cfg.api_key_enc = encrypt_credentials(settings.SECRET_KEY, {"api_key": body.api_key})
    if body.pull_tags is not None:
        cfg.pull_tags = body.pull_tags
    if body.push_types is not None:
        cfg.push_types = body.push_types
    if body.enabled is not None:
        cfg.enabled = body.enabled
    if body.ssl_verify is not None:
        cfg.ssl_verify = body.ssl_verify

    await db.commit()
    await db.refresh(cfg)
    return _to_read(cfg)


@router.delete(
    "/projects/{project_id}/misp",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Delete MISP config for project",
)
async def delete_misp_config(
    project_id: uuid.UUID,
    user: AuthUser = Depends(_require_lead_or_above),
    db: AsyncSession = Depends(get_session),
) -> None:
    result = await db.execute(
        select(MispConfig).where(MispConfig.project_id == project_id)
    )
    cfg = result.scalar_one_or_none()
    if cfg is None:
        raise HTTPException(status_code=404, detail="misp_config_not_found")
    await db.delete(cfg)
    await db.commit()


@router.post(
    "/projects/{project_id}/misp/test-connection",
    response_model=MispTestConnectionResponse,
    summary="Test MISP connectivity without persisting credentials",
)
async def test_misp_connection(
    project_id: uuid.UUID,
    body: MispTestConnectionRequest,
    user: AuthUser = Depends(_require_lead_or_above),
) -> MispTestConnectionResponse:
    """Ping the MISP instance using provided URL + API key. Credentials NOT persisted."""
    import asyncio  # noqa: PLC0415

    try:
        from pymisp import PyMISP  # noqa: PLC0415

        def _ping() -> dict:
            misp = PyMISP(
                url=body.url,
                key=body.api_key,
                ssl=body.ssl_verify,
            )
            version = misp.get_version()  # type: ignore[attr-defined]
            return version

        result = await asyncio.to_thread(_ping)
        version_str = result.get("version", "unknown") if isinstance(result, dict) else str(result)
        return MispTestConnectionResponse(ok=True, version=version_str)
    except Exception as exc:  # noqa: BLE001
        log.warning("misp_test_connection_failed url=%s error=%s", body.url, exc)
        return MispTestConnectionResponse(ok=False, error=str(exc))

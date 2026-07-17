"""Filter preset CRUD — FIL-04 / PRJ-01 M-6 enforcement.

Endpoints:
 GET /api/presets → list[FilterPresetResponse]  (membership-filtered)
 POST /api/presets → 201 FilterPresetResponse (project_id required; 422 if absent)
 GET /api/presets/{name} → FilterPresetResponse (404 if absent)
 PUT /api/presets/{name} → FilterPresetResponse (upsert; Contributor+ on project)
 DELETE /api/presets/{name} → 204 (404 if absent; Contributor+ on project)

changes:
- POST requires project_id in body; 422 on absence (PRJ-01 / M-6 enforcement)
- GET list filters by user project memberships + LEGACY_PROJECT_ID visibility
- PUT/DELETE require Contributor+ on the preset's project
- require_auth added to all endpoints (was unguarded legacy)

Note: asyncpg rejects :param::type cast syntax — CAST(:param AS jsonb) used throughout
(deviation discovered in-01, applied here proactively).
"""
from __future__ import annotations

import json
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.middleware.auth import require_auth
from app.models.filter_presets import FilterPreset
from app.models.projects import LEGACY_PROJECT_ID, ProjectMembership, ProjectRole
from app.schemas.presets import (
    PRESET_NAME_REGEX,  # noqa: F401 — re-exported for convenience
    FilterPresetResponse,
    PresetCreate,
    PresetUpsert,
)
from app.security.jwt import AuthUser
from app.security.project_membership import check_project_membership

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/presets", tags=["presets"])

_NAME_PATH_REGEX = r"^[a-z0-9_-]{1,64}$"


async def _visible_project_ids(user: AuthUser, db: AsyncSession) -> set[uuid.UUID] | None:
    """Return the set of project UUIDs visible to `user`, or None if Admin (unrestricted).

    Non-Admin sees: their project memberships (from JWT claim) + LEGACY_PROJECT_ID.
    When pm_truncated=True, falls back to a DB query to obtain the full membership list.
    """
    if user.role == "Admin":
        return None  # unrestricted

    visible: set[uuid.UUID] = {LEGACY_PROJECT_ID}
    visible.update(uuid.UUID(pid) for pid in user.project_memberships.keys())

    if user.pm_truncated:
        # JWT claim was truncated — widen via DB query
        rows = (await db.execute(
            select(ProjectMembership.project_id).where(
                ProjectMembership.user_sub == user.id
            )
        )).scalars().all()
        visible.update(rows)

    return visible


@router.get("", response_model=list[FilterPresetResponse])
async def list_presets(
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> list[FilterPresetResponse]:
    """Return filter presets visible to the caller (membership-filtered)."""
    stmt = select(FilterPreset).order_by(FilterPreset.name)
    visible = await _visible_project_ids(user, db)
    if visible is not None:
        stmt = stmt.where(FilterPreset.project_id.in_(visible))
    rows = (await db.execute(stmt)).scalars().all()
    return [FilterPresetResponse.model_validate(r) for r in rows]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=FilterPresetResponse,
)
async def create_preset(
    payload: PresetCreate,
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> FilterPresetResponse:
    """Create a new named filter preset.

 Returns 409 Conflict if the name already exists.
 Name must match ^[a-z0-9_-]{1,64}$ (enforced by Pydantic; DB CHECK is defence-in-depth).
 Requires at least Contributor role on the target project (PRJ-01).
"""
    # Contributor+ membership check on the target project
    await check_project_membership(user, db, payload.project_id, ProjectRole.Contributor)

    try:
        result = await db.execute(
            text(
                "INSERT INTO filter_presets (name, project_id, query_params) "
                "VALUES (:name, :project_id, CAST(:params AS jsonb)) "
                "RETURNING id, name, project_id, query_params, created_at, updated_at"
            ),
            {
                "name": payload.name,
                "project_id": str(payload.project_id),
                "params": json.dumps(payload.query_params),
            },
        )
        row = result.one()
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"preset name {payload.name!r} already exists",
        )

    log.info("preset_created", name=payload.name, project_id=str(payload.project_id))
    return FilterPresetResponse(
        id=row[0],
        name=row[1],
        project_id=row[2],
        query_params=row[3],
        created_at=row[4],
        updated_at=row[5],
    )


@router.get("/{name}", response_model=FilterPresetResponse)
async def get_preset(
    name: str = Path(..., pattern=_NAME_PATH_REGEX),
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> FilterPresetResponse:
    """Fetch a single preset by name. 404 if not found or not visible to caller."""
    row = (
        await db.execute(select(FilterPreset).where(FilterPreset.name == name))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="preset not found")

    # Visibility check (non-Admin must be able to see the project)
    visible = await _visible_project_ids(user, db)
    if visible is not None and row.project_id not in visible:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="preset not found")

    return FilterPresetResponse.model_validate(row)


@router.put("/{name}", response_model=FilterPresetResponse)
async def upsert_preset(
    payload: PresetUpsert,
    name: str = Path(..., pattern=_NAME_PATH_REGEX),
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> FilterPresetResponse:
    """Upsert a named preset (create if absent, replace query_params if present).

 If the preset already exists: Contributor+ check on the existing row's project.
 If creating via upsert: payload.project_id is used (defaults to LEGACY_PROJECT_ID
 when absent — backward compat for integration tests).

: ON CONFLICT DO UPDATE must explicitly set updated_at = now
 because the column default only fires on INSERT, not on UPDATE.
 created_at is preserved across updates (not included in SET clause).
"""
    # Determine the target project_id
    existing = (
        await db.execute(select(FilterPreset).where(FilterPreset.name == name))
    ).scalar_one_or_none()

    if existing is not None:
        # Update path: require Contributor+ on the preset's current project
        await check_project_membership(user, db, existing.project_id, ProjectRole.Contributor)
        target_project_id = existing.project_id  # project moves not allowed via upsert
    else:
        # Insert path: use payload.project_id or fall back to LEGACY_PROJECT_ID
        target_project_id = payload.project_id if payload.project_id is not None else LEGACY_PROJECT_ID
        await check_project_membership(user, db, target_project_id, ProjectRole.Contributor)

    result = await db.execute(
        text(
            "INSERT INTO filter_presets (name, project_id, query_params) "
            "VALUES (:name, :project_id, CAST(:params AS jsonb)) "
            "ON CONFLICT (name) DO UPDATE "
            "  SET query_params = EXCLUDED.query_params, "
            "      updated_at   = now() "
            "RETURNING id, name, project_id, query_params, created_at, updated_at"
        ),
        {"name": name, "project_id": str(target_project_id), "params": json.dumps(payload.query_params)},
    )
    row = result.one()
    await db.commit()
    log.info("preset_upserted", name=name)
    return FilterPresetResponse(
        id=row[0],
        name=row[1],
        project_id=row[2],
        query_params=row[3],
        created_at=row[4],
        updated_at=row[5],
    )


@router.delete(
    "/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_preset(
    name: str = Path(..., pattern=_NAME_PATH_REGEX),
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> Response:
    """Delete a preset by name.

 Returns 204 on success, 404 if not found.
 Requires at least Contributor role on the preset's project (PRJ-01).
 response_class=Response avoids FastAPI 204/None body serialisation bug.
"""
    row = (
        await db.execute(select(FilterPreset).where(FilterPreset.name == name))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="preset not found")

    # Contributor+ check on the preset's project
    await check_project_membership(user, db, row.project_id, ProjectRole.Contributor)

    await db.execute(
        text("DELETE FROM filter_presets WHERE name = :name"),
        {"name": name},
    )
    await db.commit()
    log.info("preset_deleted", name=name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""Filter preset CRUD — FIL-04.

Endpoints:
  GET    /api/presets         → list[FilterPresetResponse]
  POST   /api/presets         → 201 FilterPresetResponse (409 on duplicate name)
  GET    /api/presets/{name}  → FilterPresetResponse (404 if absent)
  PUT    /api/presets/{name}  → FilterPresetResponse (upsert; updated_at bumped — Pitfall 8)
  DELETE /api/presets/{name}  → 204 (404 if absent)

Note: asyncpg rejects :param::type cast syntax — CAST(:param AS jsonb) used throughout
(deviation discovered in plan 04-01, applied here proactively).
"""
from __future__ import annotations

import json

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.filter_presets import FilterPreset
from app.schemas.presets import (
    PRESET_NAME_REGEX,  # noqa: F401 — re-exported for convenience
    FilterPresetResponse,
    PresetCreate,
    PresetUpsert,
)

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/presets", tags=["presets"])

_NAME_PATH_REGEX = r"^[a-z0-9_-]{1,64}$"


@router.get("", response_model=list[FilterPresetResponse])
async def list_presets(
    db: AsyncSession = Depends(get_session),
) -> list[FilterPresetResponse]:
    """Return all saved filter presets ordered by name."""
    rows = (
        await db.execute(select(FilterPreset).order_by(FilterPreset.name))
    ).scalars().all()
    return [FilterPresetResponse.model_validate(r) for r in rows]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=FilterPresetResponse,
)
async def create_preset(
    payload: PresetCreate,
    db: AsyncSession = Depends(get_session),
) -> FilterPresetResponse:
    """Create a new named filter preset.

    Returns 409 Conflict if the name already exists.
    Name must match ^[a-z0-9_-]{1,64}$ (enforced by Pydantic; DB CHECK is defence-in-depth).
    """
    try:
        result = await db.execute(
            text(
                "INSERT INTO filter_presets (name, query_params) "
                "VALUES (:name, CAST(:params AS jsonb)) "
                "RETURNING id, name, query_params, created_at, updated_at"
            ),
            {"name": payload.name, "params": json.dumps(payload.query_params)},
        )
        row = result.one()
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"preset name {payload.name!r} already exists",
        )

    log.info("preset_created", name=payload.name)
    return FilterPresetResponse(
        id=row[0],
        name=row[1],
        query_params=row[2],
        created_at=row[3],
        updated_at=row[4],
    )


@router.get("/{name}", response_model=FilterPresetResponse)
async def get_preset(
    name: str = Path(..., pattern=_NAME_PATH_REGEX),
    db: AsyncSession = Depends(get_session),
) -> FilterPresetResponse:
    """Fetch a single preset by name. 404 if not found."""
    row = (
        await db.execute(select(FilterPreset).where(FilterPreset.name == name))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="preset not found")
    return FilterPresetResponse.model_validate(row)


@router.put("/{name}", response_model=FilterPresetResponse)
async def upsert_preset(
    payload: PresetUpsert,
    name: str = Path(..., pattern=_NAME_PATH_REGEX),
    db: AsyncSession = Depends(get_session),
) -> FilterPresetResponse:
    """Upsert a named preset (create if absent, replace query_params if present).

    Pitfall 8: ON CONFLICT DO UPDATE must explicitly set updated_at = now()
    because the column default only fires on INSERT, not on UPDATE.
    created_at is preserved across updates (not included in SET clause).
    """
    result = await db.execute(
        text(
            "INSERT INTO filter_presets (name, query_params) "
            "VALUES (:name, CAST(:params AS jsonb)) "
            "ON CONFLICT (name) DO UPDATE "
            "  SET query_params = EXCLUDED.query_params, "
            "      updated_at   = now() "
            "RETURNING id, name, query_params, created_at, updated_at"
        ),
        {"name": name, "params": json.dumps(payload.query_params)},
    )
    row = result.one()
    await db.commit()
    log.info("preset_upserted", name=name)
    return FilterPresetResponse(
        id=row[0],
        name=row[1],
        query_params=row[2],
        created_at=row[3],
        updated_at=row[4],
    )


@router.delete(
    "/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_preset(
    name: str = Path(..., pattern=_NAME_PATH_REGEX),
    db: AsyncSession = Depends(get_session),
) -> Response:
    """Delete a preset by name.

    Returns 204 on success, 404 if not found.
    response_class=Response avoids FastAPI 204/None body serialisation bug (Phase 3 Plan 02 fix).
    """
    result = await db.execute(
        text("DELETE FROM filter_presets WHERE name = :name RETURNING name"),
        {"name": name},
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="preset not found")
    await db.commit()
    log.info("preset_deleted", name=name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""Admin Maintenance Window CRUD — H-7.

Endpoints:
  POST   /api/admin/maintenance-window          — Create a new window (201)
  GET    /api/admin/maintenance-window          — List all windows
  GET    /api/admin/maintenance-window/active   — Active window or 404
  DELETE /api/admin/maintenance-window/{id}     — Delete window (204)

All endpoints require Admin role. end_at REQUIRED and must be after start_at.
Scope: global — one active window suppresses ALL monitoring alerts.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.middleware.auth import require_admin
from app.security.jwt import AuthUser

router = APIRouter(prefix="/admin/maintenance-window", tags=["admin"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CreateWindow(BaseModel):
    """Request body for POST /api/admin/maintenance-window."""

    start_at: datetime
    end_at: datetime
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _end_after_start(self) -> "CreateWindow":
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self


class WindowResponse(BaseModel):
    """Response shape for maintenance window rows."""

    id: str
    start_at: datetime
    end_at: datetime
    reason: str | None
    created_by_user_id: str | None
    created_at: datetime


# ---------------------------------------------------------------------------
# POST /api/admin/maintenance-window
# ---------------------------------------------------------------------------


@router.post("", status_code=201)
async def create_window(
    payload: CreateWindow,
    current_user: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Create a new maintenance window.

    Returns 201 with the created window id. Admin only.
    """
    window_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO maintenance_windows "
            "(id, start_at, end_at, reason, created_by_user_id) "
            "VALUES (:id, :start_at, :end_at, :reason, :user_id)"
        ),
        {
            "id": str(window_id),
            "start_at": payload.start_at,
            "end_at": payload.end_at,
            "reason": payload.reason,
            "user_id": str(current_user.id) if current_user.id else None,
        },
    )
    await db.commit()
    return {"id": str(window_id)}


# ---------------------------------------------------------------------------
# GET /api/admin/maintenance-window/active  (MUST be before /{id})
# ---------------------------------------------------------------------------


@router.get("/active")
async def get_active_window(
    _admin: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Return the currently active maintenance window, or 404 if none.

    An active window satisfies: now() BETWEEN start_at AND end_at.
    """
    result = await db.execute(
        text(
            "SELECT id, start_at, end_at, reason, created_by_user_id, created_at "
            "FROM maintenance_windows "
            "WHERE now() BETWEEN start_at AND end_at "
            "ORDER BY start_at "
            "LIMIT 1"
        )
    )
    row = result.mappings().fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="no_active_maintenance_window")
    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# GET /api/admin/maintenance-window
# ---------------------------------------------------------------------------


@router.get("")
async def list_windows(
    _admin: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> list[dict]:
    """List all maintenance windows (active + future + past), newest first."""
    result = await db.execute(
        text(
            "SELECT id, start_at, end_at, reason, created_by_user_id, created_at "
            "FROM maintenance_windows "
            "ORDER BY start_at DESC"
        )
    )
    return [_row_to_dict(row) for row in result.mappings().all()]


# ---------------------------------------------------------------------------
# DELETE /api/admin/maintenance-window/{window_id}
# ---------------------------------------------------------------------------


@router.delete("/{window_id}", status_code=204)
async def delete_window(
    window_id: uuid.UUID,
    _admin: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> Response:
    """Delete a maintenance window by ID. Returns 204 No Content."""
    result = await db.execute(
        text(
            "DELETE FROM maintenance_windows WHERE id = :wid RETURNING id"
        ),
        {"wid": str(window_id)},
    )
    if result.fetchone() is None:
        raise HTTPException(status_code=404, detail="maintenance_window_not_found")
    await db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row) -> dict:
    """Convert a mappings row to a plain dict with ISO datetime strings."""
    return {
        "id": str(row["id"]),
        "start_at": row["start_at"].isoformat() if row["start_at"] else None,
        "end_at": row["end_at"].isoformat() if row["end_at"] else None,
        "reason": row["reason"],
        "created_by_user_id": (
            str(row["created_by_user_id"]) if row["created_by_user_id"] else None
        ),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }

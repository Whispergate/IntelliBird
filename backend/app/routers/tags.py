"""PATCH /api/events/{event_id}/tags - FIL-03."""
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.events import Event
from app.schemas.tags import TagPatchRequest, TagPatchResponse

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/events", tags=["tags"])


@router.patch("/{event_id}/tags", response_model=TagPatchResponse)
async def patch_event_tags(
    event_id: uuid.UUID,
    body: TagPatchRequest,
    db: AsyncSession = Depends(get_session),
) -> TagPatchResponse:
    """Add/remove free-text tags on an event.

 - Input tags are lowercased server-side before validation and storage.
 - Any invalid tag (after lowercasing) in add OR remove → 422 (whole request rejected).
 - Re-adding an existing tag is a no-op; removing an absent tag is a no-op (idempotent).
 - Response: sorted tag array after the operation.
 - 404 if event_id not found (visibility not gated in M1 - auth deferred to M2).
"""
    # Composite-PK aware lookup - NOT session.get (: composite PK on hypertable)
    row = (
        await db.execute(select(Event).where(Event.id == event_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="event not found")

    # Read-modify-write: COALESCE(tags, '{}') - handle NULL tags column
    current: set[str] = set(row.tags or [])
    add_set: set[str] = set(body.add)
    remove_set: set[str] = set(body.remove)

    # Track actual delta counts for structured log
    actually_added = add_set - current
    actually_removed = remove_set & current

    new_tags = sorted((current - remove_set) | add_set)

    # Atomic UPDATE via raw SQL - SQLAlchemy ARRAY assignment has dialect quirks with asyncpg
    await db.execute(
        text("UPDATE events SET tags = :tags WHERE id = :eid"),
        {"tags": new_tags, "eid": str(event_id)},
    )
    await db.commit()

    log.info(
        "tags_patched",
        event_id=str(event_id),
        added_count=len(actually_added),
        removed_count=len(actually_removed),
        total_tags=len(new_tags),
    )
    return TagPatchResponse(tags=new_tags)

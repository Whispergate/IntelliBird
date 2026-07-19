"""Admin audit log REST API - AUDIT-03.

Endpoints:
  GET /api/admin/audit   cursor-based paginated audit log (Admin only)

Query params:
  user_sub        filter by user_sub
  resource_type   filter by resource_type
  action          filter by action
  from_dt         filter audit_log.time >= from_dt (default: now - 30 days)
  to_dt           filter audit_log.time <= to_dt (default: now)
  limit           max rows per page (default: 100)
  cursor          ISO timestamp string of last row's time (keyset pagination)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.middleware.auth import require_admin
from app.models.audit import AuditLog
from app.schemas.actors import AuditLogListResponse
from app.security.jwt import AuthUser

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=AuditLogListResponse)
async def list_audit_log(
    db: Annotated[AsyncSession, Depends(get_session)],
    _admin: AuthUser = Depends(require_admin),
    user_sub: str | None = Query(default=None, description="Filter by user_sub."),
    resource_type: str | None = Query(default=None, description="Filter by resource_type."),
    action: str | None = Query(default=None, description="Filter by action verb."),
    from_dt: datetime | None = Query(default=None, description="Start of date range (inclusive). Default: now - 30 days."),
    to_dt: datetime | None = Query(default=None, description="End of date range (inclusive). Default: now."),
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = Query(
        default=None,
        description="ISO timestamp string of last row's time - cursor-based pagination.",
    ),
) -> AuditLogListResponse:
    """Admin-only paginated audit log.

    Cursor pagination on (time DESC, id DESC) for hypertable efficiency.
    Returns next_cursor as ISO timestamp of the last item in the page.
    """
    now = datetime.now(timezone.utc)
    if from_dt is None:
        from_dt = now - timedelta(days=30)
    if to_dt is None:
        to_dt = now

    conditions = [
        AuditLog.time >= from_dt,
        AuditLog.time <= to_dt,
    ]

    if user_sub is not None:
        conditions.append(AuditLog.user_sub == user_sub)
    if resource_type is not None:
        conditions.append(AuditLog.resource_type == resource_type)
    if action is not None:
        conditions.append(AuditLog.action == action)

    # Cursor: (time, id) keyset pagination (time DESC, id DESC)
    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor)
            if cursor_dt.tzinfo is None:
                cursor_dt = cursor_dt.replace(tzinfo=timezone.utc)
            conditions.append(AuditLog.time < cursor_dt)
        except ValueError:
            pass  # malformed cursor → ignore, start from beginning

    stmt = (
        select(AuditLog)
        .where(and_(*conditions))
        .order_by(desc(AuditLog.time), desc(AuditLog.id))
        .limit(limit + 1)
    )

    rows = list((await db.execute(stmt)).scalars().all())

    next_cursor: str | None = None
    if len(rows) > limit:
        # Encode the last item's time as the next cursor
        last = rows[limit - 1]
        next_cursor = last.time.isoformat()
        rows = rows[:limit]

    log.info(
        "audit_log_listed",
        count=len(rows),
        user_sub=user_sub,
        resource_type=resource_type,
        action=action,
    )
    return AuditLogListResponse(items=rows, next_cursor=next_cursor)  # type: ignore[arg-type]

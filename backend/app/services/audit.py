"""Service-layer audit log helper — Phase 25 / AUDIT-01.

Called inline from service functions — NOT from middleware.
Caller is responsible for committing the session after calling log_audit().

Usage::

    log_audit(
        session,
        action="create",
        resource_type="actor",
        resource_id=str(actor.id),
        user_sub=request.state.user.sub,
        request_id=getattr(request.state, "correlation_id", None),
        after={"primary_name": actor.primary_name},
    )
    await session.commit()

The function is synchronous (session.add is not a coroutine) but is designed to
be called inside async service functions — session.add() enqueues the INSERT into
the unit-of-work; the caller's await session.commit() flushes everything.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


def log_audit(
    session: AsyncSession,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    user_sub: str | None = None,
    request_id: str | None = None,
    project_id: uuid.UUID | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    """Append an AuditLog row to the session.

    Parameters
    ----------
    session:        AsyncSession — the active DB session.
    action:         Short verb, e.g. "create", "update", "delete", "approve".
    resource_type:  Entity type, e.g. "actor", "campaign", "ioc", "source".
    resource_id:    String representation of the resource PK (optional).
    user_sub:       OIDC subject claim of the acting user (None for system actions).
    request_id:     Correlation ID from request.state (optional).
    project_id:     UUID of the associated project (optional for global resources).
    before:         Snapshot of the resource state before the mutation (optional).
    after:          Snapshot of the resource state after the mutation (optional).
    """
    session.add(
        AuditLog(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            user_sub=user_sub,
            request_id=request_id,
            project_id=project_id,
            before_jsonb=before,
            after_jsonb=after,
        )
    )

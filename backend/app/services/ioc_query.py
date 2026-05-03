"""IOC cross-project scope chokepoint — Phase 22 / IOC-03 + IOC-08.

Mirrors the role of `app.services.project_scope.build_scope_predicate` for the
events table. Every SELECT against `iocs` MUST go through
`build_ioc_scope_predicate` so cross-project leakage is structurally impossible.

ACL semantics (locked in 22-CONTEXT.md §Project scoping + sharing model):

  * Admin (user.role == "Admin") — sees ALL per-project rows + ALL global rows
    (project_id IS NULL).
  * Observer / Analyst / Lead (non-admin) — sees own-project rows
    (`project_id IN (user.project_memberships)`) + ALL global rows.

The membership lookup is done against the JWT `pm` claim that the
AuthMiddleware unpacks into `AuthUser.project_memberships` (dict[str, int]
of project_id_str → role_rank). No DB hit is required — claims are the
source of truth on the request path. This matches how the events router
threads `enforce_project_query_scope` (security/project_membership.py) and
keeps the predicate sync.

`apply_default_filters()` adds the `status != 'expired'` clause used by every
list endpoint unless `?include_expired=true` is passed (per IOC-05 soft-expire).
"""
from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Select, and_, or_
from sqlalchemy.sql import ColumnElement

from app.models.iocs import IOC


def _is_admin(user: Any) -> bool:
    """Match the casing used by `app/middleware/auth.py:200` (`user.role == "Admin"`)."""
    role = getattr(user, "role", None)
    return role == "Admin"


def _member_project_ids(user: Any) -> list[uuid.UUID]:
    """Extract project ids the user is a member of from the JWT pm claim.

    The dict is `{project_id_str: role_rank_int}` — see app/security/jwt.py:54.
    Invalid UUIDs (defensive — JWT shouldn't contain them but never trust input)
    are dropped silently rather than raising, so a malformed claim cannot crash
    the read path.
    """
    pm = getattr(user, "project_memberships", None) or {}
    out: list[uuid.UUID] = []
    for pid_str in pm.keys():
        try:
            out.append(uuid.UUID(pid_str))
        except (TypeError, ValueError):
            continue
    return out


def build_ioc_scope_predicate(
    user: Any,
    project_filter: uuid.UUID | None = None,
) -> ColumnElement[bool]:
    """Cross-project ACL predicate for the iocs table.

    Args:
        user: AuthUser instance from `request.state.user` (or any object exposing
            `.role` and `.project_memberships`). When `user` is None or the
            object lacks a role, the predicate falls through to the non-admin
            branch with an empty membership list — i.e. "global rows only" —
            matching the AuthMiddleware behaviour where AUTH_ENABLED=false
            injects a stub Admin (so this branch only ever fires in tests
            that pass a bare object).
        project_filter: Optional explicit project_id from a query param. When
            set, the predicate is intersected with
            `(IOC.project_id == project_filter OR IOC.project_id IS NULL)` so
            the route still surfaces global rows alongside the requested
            per-project view.

    Returns:
        SQLAlchemy ColumnElement[bool] suitable for `.where(...)`.

    Admin examples:
        * `build_ioc_scope_predicate(admin)` → `sa.true()` (sees all + global)
        * `build_ioc_scope_predicate(admin, project_a)` →
            `IOC.project_id == project_a OR IOC.project_id IS NULL`

    Non-admin examples:
        * `build_ioc_scope_predicate(observer_a)` →
            `IOC.project_id IN ({a}) OR IOC.project_id IS NULL`
        * `build_ioc_scope_predicate(observer_a, project_b)` →
            evaluates to `(IOC.project_id IN ({a}) OR IS NULL) AND
                          (IOC.project_id == project_b OR IS NULL)`
            — observer-A asking for project_b sees only the global rows
            (the per-project intersection is empty). The route layer is free
            to additionally raise 403 when the project_filter is not in the
            user's memberships; this predicate stays consistent regardless.
    """
    if _is_admin(user):
        if project_filter is not None:
            return or_(IOC.project_id == project_filter, IOC.project_id.is_(None))
        return sa.true()

    member_ids = _member_project_ids(user)
    if member_ids:
        base: ColumnElement[bool] = or_(
            IOC.project_id.in_(member_ids), IOC.project_id.is_(None)
        )
    else:
        # No memberships → only global rows visible.
        base = IOC.project_id.is_(None)

    if project_filter is not None:
        return and_(
            base,
            or_(IOC.project_id == project_filter, IOC.project_id.is_(None)),
        )
    return base


def apply_default_filters(
    stmt: Select,
    *,
    include_expired: bool = False,
) -> Select:
    """Append the IOC-05 default-hide-expired filter unless caller opts in.

    A separate helper (rather than inlining `IOC.status != 'expired'` into the
    scope predicate) keeps two concerns separable:

      * scope predicate = WHO can see WHICH rows (security)
      * default filters = WHICH lifecycle statuses are surfaced (UX)

    Routes that explicitly filter on `status` should NOT call this helper —
    explicit `status='expired'` requests should not be silently dropped.
    """
    if not include_expired:
        stmt = stmt.where(IOC.status != "expired")
    return stmt


__all__ = ["build_ioc_scope_predicate", "apply_default_filters"]

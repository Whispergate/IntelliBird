"""require_project_membership FastAPI dependency — Phase 10 / PRJ-05.

Three-path authorization:
  1. Global Admin (user.role == 'Admin')          -> ProjectRole.Lead  (bypass; no DB query)
  2. Cached JWT claim hit (pid_str in project_memberships) -> compare rank; 403 on shortfall
  3. Claim miss + pm_truncated=true                -> DB fallback query; else 403

Claim miss + pm_truncated=false -> 403 immediately (the token was authoritatively
empty for this pid — no need to re-query the DB).

Rank ordering (RESEARCH.md §Authority Matrix):
  Observer = 1; Contributor = 2; Lead = 3

The dependency is a factory — call require_project_membership(ProjectRole.X) in a
router signature to obtain the actual dep. The resolved ProjectRole is returned
from the dep so routers can branch further on the caller's role.
"""
from __future__ import annotations

import uuid
from typing import Callable

from fastapi import Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.middleware.auth import require_auth
from app.models.projects import ProjectMembership, ProjectRole
from app.models.users import User
from app.security.jwt import AuthUser, PROJECT_ROLE_RANK, RANK_TO_ROLE


def _min_rank(min_role: ProjectRole) -> int:
    return PROJECT_ROLE_RANK[min_role.value]


def require_project_membership(min_role: ProjectRole) -> Callable:
    """Return a FastAPI dependency that enforces at least `min_role` on the project_id path param.

    Returns the resolved ProjectRole (Observer | Contributor | Lead). Raises 403 on failure.

    Global Admin bypasses the membership check entirely and returns ProjectRole.Lead.
    This is the CONTEXT.md §Project membership model "Global Admin bypass" strong default.
    """
    min_rank = _min_rank(min_role)

    async def _dep(
        project_id: uuid.UUID = Path(...),
        user: AuthUser = Depends(require_auth),
        db: AsyncSession = Depends(get_session),
    ) -> ProjectRole:
        # 1. Global Admin bypass — support and operations access without per-project
        #    binding churn. Decision locked by CONTEXT.md §Project membership model
        #    (Claude's Discretion — strong default adopted).
        if user.role == "Admin":
            return ProjectRole.Lead

        pid_str = str(project_id)

        # 2. Claim-cache hit path
        cached_rank = user.project_memberships.get(pid_str)
        if cached_rank is not None:
            if cached_rank < min_rank:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"requires at least {min_role.value}",
                )
            return ProjectRole(RANK_TO_ROLE[cached_rank])

        # 3. Claim miss: only consult DB when the token was truncated.
        if not user.pm_truncated:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="not a project member",
            )

        # DB fallback: user_sub candidates = [str(user.id), user.oidc_sub?]
        sub_candidates: list[str] = [user.id]
        # Resolve oidc_sub if present on the user row (OIDC-bound accounts).
        oidc_row = (await db.execute(
            select(User.oidc_sub).where(User.id == uuid.UUID(user.id))
        )).scalar_one_or_none()
        if oidc_row:
            sub_candidates.append(oidc_row)

        row = (await db.execute(
            select(ProjectMembership.project_role)
            .where(ProjectMembership.user_sub.in_(sub_candidates))
            .where(ProjectMembership.project_id == project_id)
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="not a project member",
            )
        resolved_rank = PROJECT_ROLE_RANK[row]
        if resolved_rank < min_rank:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"requires at least {min_role.value}",
            )
        return ProjectRole(row)

    return _dep


__all__ = ["require_project_membership", "PROJECT_ROLE_RANK"]

"""JWT encode/decode helpers — AUTH-03 + PRJ-05.

HS256 signing using settings.JWT_SIGNING_KEY. Token TTLs per CONTEXT.md:
  access  = 15 minutes  (900s)
  refresh = 7 days      (604800s)

Claim shape (access + refresh share structure except 'type'):
  { "sub": "<user UUID>", "role": "Admin"|"Analyst"|"Viewer",
    "dashboard_roles": ["red","blue"], "jti": "<UUID>",
    "iat": <unix>, "exp": <unix>, "type": "access"|"refresh",
    "token_version": <int>,
    # optional additions (omitted when caller uses legacy mint helpers):
    "pm": [[project_id_str, role_rank_int], ...],
    "pm_truncated": <bool> }

No username in claims — frontend fetches display info via GET /api/auth/me.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

import jwt as pyjwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.projects import ProjectMembership, ProjectRole

ACCESS_TOKEN_TTL_SECONDS: int = 900
REFRESH_TOKEN_TTL_SECONDS: int = 604800
ALGORITHM: str = "HS256"

TokenType = Literal["access", "refresh"]

#: Membership cutoff — >50 memberships triggers the truncation sentinel.
#: See CONTEXT.md §Project membership model: 50 memberships × ~60 bytes ≈ 3KB claim,
#: under the 8KB header limit. Above 50, client falls back to /api/auth/memberships.
PM_CUTOFF: int = 50

#: Role-to-rank for compact JWT encoding (higher int == more authority).
#: RESEARCH.md §Authority Matrix locks Observer=1, Contributor=2, Lead=3 so `>=`
#: comparisons are natural.
PROJECT_ROLE_RANK: dict[str, int] = {
    ProjectRole.Observer.value: 1,
    ProjectRole.Contributor.value: 2,
    ProjectRole.Lead.value: 3,
}
RANK_TO_ROLE: dict[int, str] = {v: k for k, v in PROJECT_ROLE_RANK.items()}


@dataclass(frozen=True)
class AuthUser:
    """Populated on request.state.user by AuthMiddleware after successful claim verify."""

    id: str
    role: str
    dashboard_roles: list[str]
    jti: str
    token_version: int
    # additions — default to empty dict / False for tokens minted legacy.
    project_memberships: dict[str, int] = field(default_factory=dict)
    pm_truncated: bool = False


def _mint(
    user_id: str,
    role: str,
    dashboard_roles: list[str],
    token_version: int,
    signing_key: str,
    token_type: TokenType,
    ttl_seconds: int,
    *,
    pm: list[list[Any]] | None = None,
    pm_truncated: bool = False,
) -> tuple[str, str]:
    """Return (encoded_token, jti). Caller stores jti for potential blocklisting.

    pm: optional list of [project_id_str, role_rank_int] pairs.
        When None, claim is omitted (preserves token shape for callers that
        do not opt into membership claims).
    pm_truncated: True when the user has >PM_CUTOFF memberships; client must
        fetch paginated /api/auth/memberships.
    """
    now = int(time.time())
    jti = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "sub": user_id,
        "role": role,
        "dashboard_roles": list(dashboard_roles),
        "jti": jti,
        "iat": now,
        "exp": now + ttl_seconds,
        "type": token_type,
        "token_version": token_version,
    }
    if pm is not None:
        payload["pm"] = pm
        payload["pm_truncated"] = pm_truncated
    return pyjwt.encode(payload, signing_key, algorithm=ALGORITHM), jti


def mint_access_token(
    user_id: str,
    role: str,
    dashboard_roles: list[str],
    token_version: int,
    signing_key: str,
) -> tuple[str, str]:
    """Return (access_token, jti). 15-minute TTL. shape — no pm claim."""
    return _mint(
        user_id,
        role,
        dashboard_roles,
        token_version,
        signing_key,
        "access",
        ACCESS_TOKEN_TTL_SECONDS,
    )


def mint_refresh_token(
    user_id: str,
    role: str,
    dashboard_roles: list[str],
    token_version: int,
    signing_key: str,
) -> tuple[str, str]:
    """Return (refresh_token, jti). 7-day TTL. shape — no pm claim."""
    return _mint(
        user_id,
        role,
        dashboard_roles,
        token_version,
        signing_key,
        "refresh",
        REFRESH_TOKEN_TTL_SECONDS,
    )


def mint_access_token_with_pm(
    user_id: str,
    role: str,
    dashboard_roles: list[str],
    token_version: int,
    signing_key: str,
    pm: list[list[Any]],
    pm_truncated: bool,
) -> tuple[str, str]:
    """Same as mint_access_token but includes project_memberships claim."""
    return _mint(
        user_id,
        role,
        dashboard_roles,
        token_version,
        signing_key,
        "access",
        ACCESS_TOKEN_TTL_SECONDS,
        pm=pm,
        pm_truncated=pm_truncated,
    )


def mint_refresh_token_with_pm(
    user_id: str,
    role: str,
    dashboard_roles: list[str],
    token_version: int,
    signing_key: str,
    pm: list[list[Any]],
    pm_truncated: bool,
) -> tuple[str, str]:
    """Same as mint_refresh_token but includes project_memberships claim."""
    return _mint(
        user_id,
        role,
        dashboard_roles,
        token_version,
        signing_key,
        "refresh",
        REFRESH_TOKEN_TTL_SECONDS,
        pm=pm,
        pm_truncated=pm_truncated,
    )


def decode_token(token: str, signing_key: str) -> dict[str, Any]:
    """Decode + verify signature + require canonical claims.

    NOTE: "pm" + "pm_truncated" are NOT in the required-claims list — they are
    optional additions; tokens minted legacy remain valid.

    Raises:
      pyjwt.ExpiredSignatureError — exp in the past.
      pyjwt.InvalidTokenError — signature failure, missing required claim, bad format.
    """
    return pyjwt.decode(
        token,
        signing_key,
        algorithms=[ALGORITHM],
        options={"require": ["exp", "sub", "jti", "type", "iat", "role", "token_version"]},
    )


async def build_membership_claim(
    session: AsyncSession,
    user_sub_candidates: list[str],
) -> tuple[list[list[Any]], bool]:
    """Fetch project_memberships for this user's sub identifiers and encode into JWT claim shape.

    user_sub_candidates: list of strings to match against project_memberships.user_sub.
      Typically [str(user.id)] for local accounts, [str(user.id), user.oidc_sub] for OIDC users.
      This covers both the local UUID sub path and the Authentik sub fallback.

    Returns (pm_pairs, truncated):
      pm_pairs: list of [project_id_str, role_rank_int], at most PM_CUTOFF entries
      truncated: True when count > PM_CUTOFF; callers should set pm=[] and signal to clients
    """
    if not user_sub_candidates:
        return ([], False)

    rows = (await session.execute(
        select(ProjectMembership.project_id, ProjectMembership.project_role)
        .where(ProjectMembership.user_sub.in_(user_sub_candidates))
        .order_by(ProjectMembership.created_at.desc())
        .limit(PM_CUTOFF + 1)
    )).all()

    if len(rows) > PM_CUTOFF:
        return ([], True)

    return (
        [[str(pid), PROJECT_ROLE_RANK[role]] for pid, role in rows],
        False,
    )

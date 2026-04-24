"""Project scope rows → BBOT target seeds + blacklist (EASM scope consumption).

Rules locked by 11-CONTEXT.md §Scope consumption:
  - active_test_scope=True is the SOLE gate for BBOT seeding (intel_scope is IGNORED)
  - Only scope_type in {domain, ip_range, as_number} produces BBOT seeds
  - exclude=True rows become --blacklist entries (never seeds)
  - keyword / service / certificate / whois rows are intel-only — never reach BBOT
  - Empty scope returns empty list; caller (router) rejects with HTTP 422 if empty

Design rationale:
  - Pure async DB reads — zero subprocess I/O, fully unit-testable
  - No per-row picker at launch time: the scan uses all active_test_scope=True rows
    of the supported types, preserving the "scope is scope" invariant from CONTEXT.md
  - intel_scope is intentionally not referenced in the WHERE clause; including it would
    violate the CONTEXT.md lock and create unexpected filtering for rows where both
    active_test_scope and intel_scope are True
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.projects import ProjectScopeRow

# ---------------------------------------------------------------------------
# Scope types that feed BBOT (M-3 closure + CONTEXT.md §Scope consumption lock)
# Intentionally excludes: keyword, service, certificate, whois (intel-only)
# ---------------------------------------------------------------------------
BBOT_SEEDING_SCOPE_TYPES: frozenset[str] = frozenset({"domain", "ip_range", "as_number"})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _format_seed(scope_type: str, value: str) -> str:  # noqa: ARG001
    """Normalise a seed value for BBOT -t arg.

    BBOT accepts raw domain names, CIDR notation, and ASN integers directly via -t.
    The scope_type parameter is accepted for future extensibility (e.g. URL prefix seeds
    would need formatting) but is currently unused for the three supported types.
    """
    return value.strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def derive_bbot_seeds(db: AsyncSession, project_id: uuid.UUID) -> list[str]:
    """Return BBOT -t arg values for a project's active-test scope.

    Filters applied:
      - project_id matches
      - active_test_scope IS True  (sole gate — intel_scope intentionally IGNORED)
      - exclude IS False           (exclude=True rows go to blacklist only)
      - scope_type IN {domain, ip_range, as_number}  (intel-only types excluded)

    Returns empty list when no matching rows exist.
    Caller (router) rejects with HTTP 422 'empty_scope' when list is empty.
    """
    stmt = (
        select(ProjectScopeRow)
        .where(
            ProjectScopeRow.project_id == project_id,
            ProjectScopeRow.active_test_scope.is_(True),
            ProjectScopeRow.exclude.is_(False),
            ProjectScopeRow.scope_type.in_(BBOT_SEEDING_SCOPE_TYPES),
        )
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_format_seed(r.scope_type, r.value) for r in rows]


async def derive_bbot_blacklist(db: AsyncSession, project_id: uuid.UUID) -> list[str]:
    """Return BBOT --blacklist values for a project's active-test exclude rows.

    Identical filter to derive_bbot_seeds EXCEPT exclude IS True (not False).
    Only scope types in BBOT_SEEDING_SCOPE_TYPES contribute to the blacklist —
    intel-only types (keyword/service/certificate/whois) are never passed to BBOT.

    Returns empty list when no matching exclude rows exist.
    """
    stmt = (
        select(ProjectScopeRow)
        .where(
            ProjectScopeRow.project_id == project_id,
            ProjectScopeRow.active_test_scope.is_(True),
            ProjectScopeRow.exclude.is_(True),
            ProjectScopeRow.scope_type.in_(BBOT_SEEDING_SCOPE_TYPES),
        )
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_format_seed(r.scope_type, r.value) for r in rows]

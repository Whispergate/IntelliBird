"""Project scope intersection SQL builder — Phase 10 / PRJ-03 + PRJ-05.

Single reusable helper used by:
  - events_query.build_events_query (intel view — /projects/[id]/intel)
  - events_query.build_fts_query (FTS variant)
  - graph_traversal.traverse_graph (per-project graph BFS)
  - project_compare (cross-project shared-event queries, plan 10-07)
  - project_export (STIX + CSV export, plan 10-07)

JSONB indicator path policy
--------------------------
STIX indicators live inside `events.raw_stix -> objects[*].pattern` as text patterns
matching the STIX 2.1 pattern grammar (examples: `[ipv4-addr:value = '1.2.3.4']`,
`[domain-name:value = 'evil.example.com']`). Phase 2 enrichment (backend/app/services/
enrichment.py) populates `events.tags` (flat text array) + `events.country_code` +
geo — but does NOT denormalise indicators into a dedicated JSONB column or top-level
array. Scope-intersection therefore extracts indicators from the STIX pattern strings
using PostgreSQL `jsonb_path_query_array` + regex substring extraction.

This path is MEDIUM confidence per 10-RESEARCH.md §Pattern 2. Phase 11 enrichment
refactor may denormalise indicators to a dedicated path (e.g. `raw_stix->'indicators'
->'ip'`); when that happens, update the three extraction clauses here and re-audit
these tests.

Per CONTEXT.md §Scope-intersection query semantics:
  ip_range  -> PostgreSQL inet `<<` containment against extracted IPv4 indicators
  domain    -> exact OR subdomain-suffix LIKE match
  keyword   -> events.search_tsv @@ plainto_tsquery('english', value)  (Phase 4 FTS reuse)
  as_number -> JSONB path to enrichment.asn + FTS fallback on "ASnnnnn"
  service / whois / certificate -> FTS fallback (Claude's Discretion; Phase 2
    enrichment does not yet expose these as dedicated columns)

Empty-set invariants:
  - No intel_scope=true rows at all -> return sa.text("false") (zero events, not all)
  - Only exclude rows present -> return sa.text("false") (no includes to subtract from)
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.events import Event
from app.models.projects import ProjectScopeRow, ProjectSource


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

async def fetch_scope_rows_intel(
    session: AsyncSession, project_id: uuid.UUID,
) -> list[ProjectScopeRow]:
    """Return scope rows where intel_scope=true. exclude=true rows included for subtraction."""
    rows = (await session.execute(
        select(ProjectScopeRow)
        .where(ProjectScopeRow.project_id == project_id)
        .where(ProjectScopeRow.intel_scope == True)  # noqa: E712
    )).scalars().all()
    return list(rows)


async def fetch_bound_sources(
    session: AsyncSession, project_id: uuid.UUID,
) -> list[uuid.UUID]:
    """Return bound source IDs, or empty list if no binding exists (all-sources-visible default)."""
    rows = (await session.execute(
        select(ProjectSource.source_id).where(ProjectSource.project_id == project_id)
    )).scalars().all()
    return list(rows)


# ---------------------------------------------------------------------------
# Per-row clause builders
# ---------------------------------------------------------------------------

def _clause_keyword(value: str) -> sa.sql.ColumnElement[bool]:
    """keyword scope -> Phase 4 FTS via events.search_tsv generated column."""
    return sa.column("search_tsv").op("@@")(
        sa.func.plainto_tsquery("english", value)
    )


def _clause_domain(value: str, index: int) -> sa.sql.ColumnElement[bool]:
    """domain scope -> exact OR subdomain-suffix LIKE match.

    Extracts domain indicators from raw_stix patterns via jsonb_path_query_array +
    regex substring. Pattern example: `[domain-name:value = 'evil.example.com']`.
    """
    return sa.text(
        "EXISTS ("
        "  SELECT 1 FROM jsonb_path_query_array("
        "    events.raw_stix, '$.objects[*].pattern'"
        "  ) AS p,"
        "  LATERAL substring(p::text from 'domain-name:value\\s*=\\s*''([^'']+)''') AS d"
        "  WHERE d IS NOT NULL AND ("
        f"     d = :dom_{index}"
        f"     OR d LIKE '%%.' || :dom_{index}"
        "  )"
        ")"
    ).bindparams(**{f"dom_{index}": value.lower()})


def _clause_ip_range(value: str, index: int) -> sa.sql.ColumnElement[bool]:
    """ip_range scope -> PostgreSQL inet `<<` containment.

    Extracts IPv4 indicators from raw_stix patterns via jsonb_path_query_array +
    regex substring. Pattern example: `[ipv4-addr:value = '10.0.0.5']`.
    CAST(:param AS cidr) form required — asyncpg rejects ::type shorthand.
    """
    return sa.text(
        "EXISTS ("
        "  SELECT 1 FROM jsonb_path_query_array("
        "    events.raw_stix, '$.objects[*].pattern'"
        "  ) AS p,"
        "  LATERAL substring(p::text from 'ipv4-addr:value\\s*=\\s*''([^'']+)''') AS ip_str"
        "  WHERE ip_str IS NOT NULL"
        f"    AND ip_str::inet << CAST(:cidr_{index} AS cidr)"
        ")"
    ).bindparams(**{f"cidr_{index}": value})


def _clause_as_number(value: str, index: int) -> sa.sql.ColumnElement[bool]:
    """as_number scope -> JSONB enrichment.asn + FTS fallback on "ASnnnnn"."""
    return sa.or_(
        sa.text(
            f"(events.raw_stix #>> '{{enrichment,asn}}') = :asn_{index}"
        ).bindparams(**{f"asn_{index}": value}),
        sa.column("search_tsv").op("@@")(
            sa.func.plainto_tsquery("english", f"AS{value}")
        ),
    )


def _clause_service_whois_cert(value: str) -> sa.sql.ColumnElement[bool]:
    """service / whois / certificate scope -> FTS fallback.

    Claude's Discretion per CONTEXT.md §Claude's Discretion §Scope-intersection SQL —
    Phase 2 enrichment does not expose dedicated columns for these types. Phase 11
    enrichment refactor may add them; update this clause when that happens.
    """
    return sa.column("search_tsv").op("@@")(
        sa.func.plainto_tsquery("english", value)
    )


def _clause_for_row(row: ProjectScopeRow, index: int) -> sa.sql.ColumnElement[bool]:
    """Dispatch to the appropriate per-type clause builder."""
    st = row.scope_type
    if st == "keyword":
        return _clause_keyword(row.value)
    if st == "domain":
        return _clause_domain(row.value, index)
    if st == "ip_range":
        return _clause_ip_range(row.value, index)
    if st == "as_number":
        return _clause_as_number(row.value, index)
    if st in ("service", "whois", "certificate"):
        return _clause_service_whois_cert(row.value)
    # Safety fallback — unknown scope_type (should be unreachable — ENUM bounded)
    return sa.text("false")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_scope_predicate(
    scope_rows: list[ProjectScopeRow],
) -> sa.sql.ColumnElement[bool]:
    """Compose UNION-of-includes minus any-exclude-match into a single SQL predicate.

    Returns sa.text("false") when the list is empty or contains only excludes — this
    is the empty-scope-empty-result invariant from CONTEXT.md §Scope-intersection
    query semantics.

    Caller must have already filtered to intel_scope=true rows (use
    fetch_scope_rows_intel). This builder does NOT re-check intel_scope.
    """
    if not scope_rows:
        return sa.text("false")

    include_clauses: list[sa.sql.ColumnElement[bool]] = []
    exclude_clauses: list[sa.sql.ColumnElement[bool]] = []
    for i, row in enumerate(scope_rows):
        clause = _clause_for_row(row, index=i)
        (exclude_clauses if row.exclude else include_clauses).append(clause)

    if not include_clauses:
        return sa.text("false")

    pred = sa.or_(*include_clauses)
    if exclude_clauses:
        # NOT wrapping each exclude clause individually (AND-of-NOTs) — this
        # avoids the SA2 TextClause._negate limitation where sa.not_(sa.or_(
        # TextClause, ...)) raises AssertionError. Semantically equivalent:
        # NOT (e1 OR e2) == (NOT e1) AND (NOT e2) (De Morgan).
        negated = [_wrap_not(c) for c in exclude_clauses]
        pred = sa.and_(pred, *negated)
    return pred


def _wrap_not(clause: sa.sql.ColumnElement[bool]) -> sa.sql.ColumnElement[bool]:
    """Negate a scope clause even when it's a raw TextClause.

    sa.not_() cannot negate TextClause directly in SQLAlchemy 2.x (TextClause._negate
    has an assertion failure). Wrap the clause in `NOT (...)` literal SQL via
    str-compiling the clause with inline bound params first via .compile(literal_binds=False).
    Since all our exclude clauses are either sa.text() or sa.column().op()() forms,
    we normalise via sa.func.bool_and over a subquery. Simpler path: rebuild as a
    SQL-level NOT against a text wrapper constructed from the clause's compiled form.

    Implementation: sa.type_coerce on the clause then wrap — but that doesn't work
    with TextClause. The reliable path is to use sa.false() operator: `clause == False`
    coerces the boolean expression. But TextClause doesn't support ==.

    Final approach: build the NOT via SQL text composition, binding the clause's
    bindparams through. We compile the clause to an unbound string and wrap.
    """
    # For ColumnElement-backed clauses (search_tsv @@ ...) sa.not_ works fine.
    # For TextClause clauses, fallback to explicit SQL composition preserving binds.
    from sqlalchemy.sql.elements import TextClause
    if isinstance(clause, TextClause):
        # Preserve bindparams: sa.text("NOT (" + existing_text + ")") with the same
        # bindparams. TextClause exposes ._bindparams (Mapping[str, BindParameter]).
        inner_sql = str(clause)
        binds = {name: bp.value for name, bp in clause._bindparams.items()}
        return sa.text(f"NOT ({inner_sql})").bindparams(**binds)
    return sa.not_(clause)


async def apply_project_filter_to_stmt(
    session: AsyncSession,
    stmt: Select,
    project_id: uuid.UUID,
) -> Select:
    """Return stmt with project + scope + bound-sources filters applied.

    Call order:
      1. WHERE events.project_id = project_id
      2. IF bound_sources is non-empty: WHERE events.source_id IN (bound_sources)
      3. WHERE <scope_predicate>

    Used by routers + compare/export helpers that want all three filters composed
    onto an existing Select. Routers typically pre-fetch + compose manually so that
    build_events_query (sync, Phase 9 contract) stays sync — apply_project_filter_
    to_stmt is an async alternative for callers that have an AsyncSession handy.
    """
    stmt = stmt.where(Event.project_id == project_id)

    bound = await fetch_bound_sources(session, project_id)
    if bound:
        stmt = stmt.where(Event.source_id.in_(bound))

    scope_rows = await fetch_scope_rows_intel(session, project_id)
    pred = build_scope_predicate(scope_rows)
    stmt = stmt.where(pred)
    return stmt

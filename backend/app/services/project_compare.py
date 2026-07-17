"""Cross-project compare service — PRJ-06.

Two-project comparison only (not N-project Venn — deferred to v2.1 per CONTEXT.md).
Returns three independent shared-entity lists capped at 500 rows each. Every
panel enforces scope-intersection via `build_scope_predicate(...)` composed into
the per-project CTE — there is no divergence in scope semantics across the three
compare surfaces.

Locked decisions (CONTEXT.md §PRJ-06, iter-1 revisions):
- 500-row cap per panel (`COMPARE_CAP`)
- Empty arrays on no-overlap (not 404)
- shared_actors uses `lower(raw_stix->>'name')` over `threat-actor` +
  `intrusion-set` stix_type events (lowercased intersection)
- shared_techniques joins `attack_technique_tags` to `events` per project
- shared_iocs parses ip / domain / hash patterns from `raw_stix.objects[*].pattern`;
  each kind runs a SEPARATE scope-guarded subquery pair (A+B) so scope semantics
  are identical to the other two panels.
"""
from __future__ import annotations

import re
import uuid
from typing import Literal, TypedDict

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.events import Event
from app.models.tags import AttackTechniqueTag
from app.services.project_scope import build_scope_predicate, fetch_scope_rows_intel

#: Per-panel row cap. CONTEXT.md §PRJ-06 "Result cap: 500 rows per table".
COMPARE_CAP: int = 500


class SharedIOC(TypedDict):
    kind: Literal["ip", "domain", "hash"]
    value: str


# ---------------------------------------------------------------------------
# shared_actors — threat-actor + intrusion-set name intersection
# ---------------------------------------------------------------------------


async def shared_actors(
    session: AsyncSession,
    project_a: uuid.UUID,
    project_b: uuid.UUID,
) -> list[str]:
    """Return lowercased actor names present in BOTH projects' events.

    Scope-intersection: both sides are filtered by `build_scope_predicate(...)`
    composed from each project's intel_scope=True rows — same semantics as
    shared_techniques / shared_iocs.
    """
    pred_a = build_scope_predicate(await fetch_scope_rows_intel(session, project_a))
    pred_b = build_scope_predicate(await fetch_scope_rows_intel(session, project_b))

    a_q = (
        select(
            sa.func.lower(Event.raw_stix["name"].astext).label("actor_name")
        )
        .where(Event.project_id == project_a)
        .where(Event.stix_type.in_(["threat-actor", "intrusion-set"]))
        .where(pred_a)
        .distinct()
    ).subquery("a_actors")

    b_q = (
        select(
            sa.func.lower(Event.raw_stix["name"].astext).label("actor_name")
        )
        .where(Event.project_id == project_b)
        .where(Event.stix_type.in_(["threat-actor", "intrusion-set"]))
        .where(pred_b)
        .distinct()
    ).subquery("b_actors")

    stmt = (
        select(a_q.c.actor_name)
        .join(b_q, a_q.c.actor_name == b_q.c.actor_name)
        .where(a_q.c.actor_name.isnot(None))
        .order_by(a_q.c.actor_name)
        .limit(COMPARE_CAP)
    )
    rows = (await session.execute(stmt)).all()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# shared_techniques — ATT&CK technique id intersection (via tag JOIN events)
# ---------------------------------------------------------------------------


async def shared_techniques(
    session: AsyncSession,
    project_a: uuid.UUID,
    project_b: uuid.UUID,
) -> list[str]:
    """Return ATT&CK technique ids tagged on events of BOTH projects.

    Uses a cross-table JOIN: attack_technique_tags -> events (via event_id) so
    per-project scope predicates apply. attack_technique_tags.event_id has NO
    foreign key to events (TimescaleDB hypertable limitation) so the JOIN is
    app-level — same pattern as cve_details.
    """
    pred_a = build_scope_predicate(await fetch_scope_rows_intel(session, project_a))
    pred_b = build_scope_predicate(await fetch_scope_rows_intel(session, project_b))

    a_q = (
        select(AttackTechniqueTag.technique_id.label("t"))
        .join(Event, Event.id == AttackTechniqueTag.event_id)
        .where(Event.project_id == project_a)
        .where(pred_a)
        .distinct()
    ).subquery("a_tech")

    b_q = (
        select(AttackTechniqueTag.technique_id.label("t"))
        .join(Event, Event.id == AttackTechniqueTag.event_id)
        .where(Event.project_id == project_b)
        .where(pred_b)
        .distinct()
    ).subquery("b_tech")

    stmt = (
        select(a_q.c.t)
        .join(b_q, a_q.c.t == b_q.c.t)
        .order_by(a_q.c.t)
        .limit(COMPARE_CAP)
    )
    rows = (await session.execute(stmt)).all()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# shared_iocs — ip/domain/hash patterns extracted from raw_stix.objects[*].pattern
# ---------------------------------------------------------------------------
#
# STIX indicators live as text patterns inside raw_stix.objects[*].pattern:
#   [ipv4-addr:value = '10.0.0.1']
#   [domain-name:value = 'evil.example.com']
#   [file:hashes.MD5 = 'd41d8cd98f00b204e9800998ecf8427e']
#
# enrichment does NOT denormalise indicators into a dedicated column or
# flat array — extraction is via jsonb_path_query_array + regex substring at
# query time. Same MEDIUM-confidence tradeoff as project_scope._clause_domain
# / _clause_ip_range; enrichment may refactor.
#
# Scope-intersection: each kind runs a full pred_a / pred_b guarded subquery
# pair so the semantics match shared_actors + shared_techniques — iter-1 revision
# closes the "IOC panel silently skipped scope predicate" gap.

# Python-side regex patterns for IOC extraction. Single quotes here (not doubled)
# because the raw_stix JSONB values read out via ->> as actual strings with
# real single quotes — we're extracting in Python, not via PG's substring(regex).
_IOC_KIND_PATTERNS: list[tuple[Literal["ip", "domain", "hash"], re.Pattern[str]]] = [
    ("ip", re.compile(r"ipv4-addr:value\s*=\s*'([^']+)'")),
    ("domain", re.compile(r"domain-name:value\s*=\s*'([^']+)'")),
    ("hash", re.compile(r"hashes\.[A-Za-z0-9-]+\s*=\s*'([^']+)'")),
]


async def _scoped_raw_stix_rows(
    session: AsyncSession,
    project_id: uuid.UUID,
    pred: sa.sql.ColumnElement[bool],
) -> list[dict]:
    """Return raw_stix JSONB for all scope-matching events in the project.

    Python-side extraction: we fetch matching events' raw_stix, then extract
    IOC values per-kind via regex in shared_iocs. This trades a larger result
    set over the wire (COMPARE_CAP bounds the output but all matching rows
    come back pre-filter) for a much simpler SQL shape — jsonb_path_query_array
    requires a jsonpath-typed second argument, which is awkward to bind safely
    from the SA2 text() / literal_column() path. Scope-predicate enforcement
    stays on the SQL side where it belongs.
    """
    stmt = (
        select(Event.raw_stix)
        .where(Event.project_id == project_id)
        .where(pred)
        .where(Event.raw_stix.isnot(None))
    )
    rows = (await session.execute(stmt)).all()
    return [r[0] for r in rows if r[0] is not None]


def _extract_iocs(
    raw_stix_docs: list[dict],
    kind: Literal["ip", "domain", "hash"],
    pattern: re.Pattern[str],
) -> set[str]:
    """Walk each raw_stix doc and extract IOC literals of one kind.

    raw_stix may be shaped either as a single STIX object (has 'pattern' directly)
    or a bundle-style ({"objects": [{"pattern": "..."}, ...]}). We handle both —
    the real data ingests is a mix.
    """
    seen: set[str] = set()
    for doc in raw_stix_docs:
        patterns: list[str] = []
        # Single-SDO form: {"type": "indicator", "pattern": "[ip...]"}
        p = doc.get("pattern")
        if isinstance(p, str):
            patterns.append(p)
        # Bundle-objects form: {"objects": [{"pattern": "..."}, ...]}
        for obj in doc.get("objects", []) or []:
            if isinstance(obj, dict):
                op = obj.get("pattern")
                if isinstance(op, str):
                    patterns.append(op)
        for pat in patterns:
            for match in pattern.finditer(pat):
                seen.add(match.group(1))
    return seen


async def shared_iocs(
    session: AsyncSession,
    project_a: uuid.UUID,
    project_b: uuid.UUID,
) -> list[SharedIOC]:
    """Return IOCs (ip / domain / hash) shared by events of BOTH projects.

    Scope-intersection: pred_a + pred_b composed via build_scope_predicate are
    applied at the SQL layer when fetching raw_stix rows for each project
    (symmetric with shared_actors + shared_techniques — all three panels honour
    scope_predicate equally). Per-kind regex extraction then runs in Python
    over the scope-matching raw_stix docs; intersections are computed as set
    operations. Per-kind results sorted + capped at COMPARE_CAP; total result
    also capped at COMPARE_CAP.

    Return shape: [{"kind": "ip"|"domain"|"hash", "value": "<ioc_literal>"}, ...]
    """
    pred_a = build_scope_predicate(await fetch_scope_rows_intel(session, project_a))
    pred_b = build_scope_predicate(await fetch_scope_rows_intel(session, project_b))

    a_raw = await _scoped_raw_stix_rows(session, project_a, pred_a)
    b_raw = await _scoped_raw_stix_rows(session, project_b, pred_b)

    result: list[SharedIOC] = []
    for kind, pattern in _IOC_KIND_PATTERNS:
        a_set = _extract_iocs(a_raw, kind, pattern)
        b_set = _extract_iocs(b_raw, kind, pattern)
        shared = sorted(a_set & b_set)[:COMPARE_CAP]
        for v in shared:
            result.append({"kind": kind, "value": v})
    return result[:COMPARE_CAP]


__all__ = [
    "COMPARE_CAP",
    "SharedIOC",
    "shared_actors",
    "shared_techniques",
    "shared_iocs",
]

"""Project export service - PRJ-07.

Produces STIX 2.1 Bundle (via stix2 3.0.2) or CSV (via stdlib csv) for a project scope.
Both formats are capped at 50k events; above the cap, the router returns 413.

Filename convention: intellibird-project-<slug>-<YYYY-MM-DD>.<stix.json|csv>

Locked decisions (CONTEXT.md §PRJ-07):
- Sync response (no async job path - deferred to v2.1)
- 50k event cap - 413 with hint to narrow scope
- STIX Bundle uses Identity("IntelliBird") + Note SDO carrying
  x_intellibird_project + x_intellibird_scope_rows custom properties
- CSV 10-column locked set (CONTEXT.md anchor, narrowed from RESEARCH.md 17-col draft)
- Observer role excluded from export (Contributor+ only; global Admin bypass)
"""
from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import datetime, timezone

import stix2
import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.events import Event
from app.models.markings import TlpMarking
from app.models.projects import Project, ProjectScopeRow
from app.models.sources import Source
from app.models.tags import AttackTechniqueTag
from app.services.events_query import EventsQueryParams, build_events_query
from app.services.project_scope import (
    build_scope_predicate,
    fetch_bound_sources,
    fetch_scope_rows_intel,
)

log = structlog.get_logger(__name__)

#: Per-format event cap. CONTEXT.md §PRJ-07: "50k event cap → 413 Payload Too Large"
STIX_BUNDLE_EVENT_CAP: int = 50_000
CSV_EVENT_CAP: int = 50_000

#: CSV locked column set (CONTEXT.md §PRJ-07 Claude's Discretion anchor).
#: Order is load-bearing - test_csv_columns asserts header == CSV_COLUMNS exactly.
CSV_COLUMNS: list[str] = [
    "id",
    "observed_at",
    "stix_type",
    "source_name",
    "title",
    "description",
    "tlp",
    "tags",
    "attack_techniques",
    "geo_country",
]


_SLUG_STRIP = re.compile(r"[^a-z0-9-]")


def slug(name: str) -> str:
    """Convert a project name to a filename-safe slug.

    Examples:
      "Red Team 2026"      -> "red-team-2026"
      "Client X – Engagement"  -> "client-x-engagement"
      ""                   -> "untitled"
    """
    s = name.lower().replace(" ", "-")
    s = _SLUG_STRIP.sub("", s)
    s = s.strip("-")
    return s or "untitled"


def export_filename(project_name: str, fmt: str) -> str:
    """intellibird-project-<slug>-<YYYY-MM-DD>.<ext>

    Server-side filename construction per plan 10-07 iter-1 lock: no client-side
    slug generation. Content-Disposition header is the sole source of truth.
    """
    ext = "stix.json" if fmt == "stix" else "csv"
    today = datetime.now(timezone.utc).date().isoformat()
    return f"intellibird-project-{slug(project_name)}-{today}.{ext}"


# ---------------------------------------------------------------------------
# Count + fetch helpers
# ---------------------------------------------------------------------------


async def count_exportable_events(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> int:
    """Return the count of events that would be included in an export of this project.

    Honours the full scope-intersection pipeline: project_id match + bound_sources
    filter + scope_predicate. This is the same predicate stack that fetch_scoped_events
    applies, so the count and the fetched rowset are always consistent.
    """
    scope_rows = await fetch_scope_rows_intel(session, project_id)
    scope_predicate = build_scope_predicate(scope_rows)
    bound_sources = await fetch_bound_sources(session, project_id)

    stmt = select(func.count(Event.id)).where(Event.project_id == project_id)
    if bound_sources:
        stmt = stmt.where(Event.source_id.in_(bound_sources))
    stmt = stmt.where(scope_predicate)
    return int((await session.execute(stmt)).scalar_one())


async def fetch_scoped_events(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> list[Event]:
    """Load up to the cap's worth of scoped events for this project.

    Uses build_events_query so dashboard_roles / visibility gating is applied
    consistently with the /events endpoint. Limit applied at query level -
    the 413 gate at the router must prevent cases where truncation would lose data.
    """
    scope_rows = await fetch_scope_rows_intel(session, project_id)
    scope_predicate = build_scope_predicate(scope_rows)
    bound_sources = await fetch_bound_sources(session, project_id)

    stmt = build_events_query(
        EventsQueryParams(),
        None,  # dashboard_roles=None => no visibility filter (admin-equivalent)
        project_id=project_id,
        scope_predicate=scope_predicate,
        bound_sources=bound_sources,
    ).limit(STIX_BUNDLE_EVENT_CAP)
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


# ---------------------------------------------------------------------------
# STIX Bundle builder
# ---------------------------------------------------------------------------


def build_stix_bundle(
    project: Project,
    events: list[Event],
    scope_rows: list[ProjectScopeRow],
) -> str:
    """Produce a STIX 2.1 Bundle string with project metadata + scope rows custom props.

    Bundle composition (RESEARCH.md §STIX 2.1 Bundle Composition):
      - stix2.Identity("IntelliBird", system) - producer provenance
      - stix2.Note SDO with x_intellibird_project + x_intellibird_scope_rows
        custom properties capturing project metadata + scope configuration
      - Every event.raw_stix parsed via stix2.parse(allow_custom=True) and appended;
        malformed STIX is logged (warning) and skipped - never fatal.

    Returns a JSON string (bundle.serialize(pretty=False)) suitable for an HTTP
    application/json response.
    """
    producer = stix2.Identity(name="IntelliBird", identity_class="system")
    project_note = stix2.Note(
        abstract=f"IntelliBird project export: {project.name}",
        content=project.description or "",
        object_refs=[producer.id],
        allow_custom=True,
        custom_properties={
            "x_intellibird_project": {
                "id": str(project.id),
                "name": project.name,
                "engagement_type": project.engagement_type,
                "description": project.description,
                "exported_at": datetime.now(timezone.utc).isoformat(),
            },
            "x_intellibird_scope_rows": [
                {
                    "scope_type": r.scope_type,
                    "value": r.value,
                    "exclude": r.exclude,
                    "intel_scope": r.intel_scope,
                    "active_test_scope": r.active_test_scope,
                }
                for r in scope_rows
            ],
        },
    )
    stix_objects: list = [producer, project_note]
    for e in events:
        if e.raw_stix is None:
            continue
        try:
            obj = stix2.parse(e.raw_stix, allow_custom=True)
            stix_objects.append(obj)
        except Exception as exc:
            # Malformed stored STIX - log + skip; not fatal to the bundle.
            log.warning(
                "stix_export_malformed_event",
                event_id=str(e.id),
                error_type=type(exc).__name__,
            )
            continue

    bundle = stix2.Bundle(objects=stix_objects, allow_custom=True)
    return bundle.serialize(pretty=False)


# ---------------------------------------------------------------------------
# CSV builder
# ---------------------------------------------------------------------------


async def _hydrate_csv_row(e: Event, session: AsyncSession) -> dict:
    """Denormalise one event into a CSV-ready dict.

    Issues small per-event lookups for source_name / tlp / attack_techniques.
    Acceptable for export workload (50k max; O(50k) additional queries at the cap).

    Newline characters in title + description are replaced with spaces to keep
    CSV row-per-line hygiene for downstream consumers that line-split unsafely.
    Description is further truncated to 4096 chars to bound cell size.
    """
    source_name: str = ""
    if e.source_id:
        sn = (
            await session.execute(
                select(Source.name).where(Source.id == e.source_id)
            )
        ).scalar_one_or_none()
        source_name = sn or ""

    tlp: str = ""
    if e.tlp_marking_id:
        tn = (
            await session.execute(
                select(TlpMarking.name).where(TlpMarking.id == e.tlp_marking_id)
            )
        ).scalar_one_or_none()
        tlp = tn or ""

    tech_ids = (
        await session.execute(
            select(AttackTechniqueTag.technique_id).where(
                AttackTechniqueTag.event_id == e.id
            )
        )
    ).scalars().all()

    title_raw = (e.title or "").replace("\n", " ").replace("\r", " ")
    desc_raw = (e.description or "").replace("\n", " ").replace("\r", " ")

    return {
        "id": str(e.id),
        "observed_at": e.observed_at.isoformat() if e.observed_at else "",
        "stix_type": e.stix_type or "",
        "source_name": source_name,
        "title": title_raw,
        "description": desc_raw[:4096],
        "tlp": tlp,
        "tags": "|".join(e.tags or []),
        "attack_techniques": "|".join(tech_ids),
        "geo_country": e.country_code or "",
    }


async def build_csv_bytes(
    session: AsyncSession,
    events: list[Event],
) -> bytes:
    """Synchronous CSV builder - collects full output into bytes.

    Safe at the 50k cap: ~50k × ~1KB/row = ~50MB worst case, well within a single
    server response buffer. Streaming variant (build_csv_stream) remains an option
    for v2.1 if memory pressure materialises.
    """
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf, fieldnames=CSV_COLUMNS, quoting=csv.QUOTE_MINIMAL
    )
    writer.writeheader()
    for e in events:
        row = await _hydrate_csv_row(e, session)
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


__all__ = [
    "STIX_BUNDLE_EVENT_CAP",
    "CSV_EVENT_CAP",
    "CSV_COLUMNS",
    "slug",
    "export_filename",
    "count_exportable_events",
    "fetch_scoped_events",
    "build_stix_bundle",
    "build_csv_bytes",
]

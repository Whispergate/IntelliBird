"""Shared event writer + per-source health update for workers.

These two helpers are the ONLY code path that touches the events table
insert + UNIQUE(source_id, content_hash, observed_at) ON CONFLICT DO NOTHING
contract and the sources health-field update contract
. Worker plans 03/04/05 call these — they do not re-implement.

IMPORTANT: The unique index on the events hypertable spans THREE columns:
(source_id, content_hash, observed_at). TimescaleDB requires the partition
column (observed_at) in every unique index. Workers must pass observed_at
in the row dict. Re-fetched items use the original item publication timestamp
as observed_at, so the triple is identical on re-fetch — dedup works correctly.
"""
from __future__ import annotations

import uuid

from sqlalchemy import text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.events import Event
from app.models.sources import Source
from app.services.source_health import bump_last_event_at


def _inject_score_into_row(session: Session, row: dict) -> None:
    """Phase 15 / SCR-01: populate score, scored_at, score_version before INSERT.

    Looks up feed_type + confidence from sources using the source_id already in
    the row. Falls back to DEFAULT_SOURCE_CONFIDENCE[feed_type] when the source
    has no confidence set; falls back to 0.7 if feed_type is unknown.

    Mutates ``row`` in-place. No-ops if score is already set (caller pre-scored).
    """
    if row.get("score") is not None:
        return  # already scored by caller — don't double-score

    from app.services.scoring import score_event, ScoringWeights  # lazy import
    from app.services.scoring.defaults import DEFAULT_SOURCE_CONFIDENCE  # lazy import

    source_id = row.get("source_id")
    feed_type = "rss"  # default fallback
    src_conf: float = DEFAULT_SOURCE_CONFIDENCE.get(feed_type, 0.7)

    if source_id is not None:
        src_row = session.execute(
            text("SELECT feed_type, confidence FROM sources WHERE id = :id"),
            {"id": str(source_id)},
        ).one_or_none()
        if src_row is not None:
            feed_type = src_row[0] or feed_type
            db_conf = src_row[1]
            if db_conf is not None:
                src_conf = float(db_conf)
            else:
                src_conf = DEFAULT_SOURCE_CONFIDENCE.get(feed_type, 0.7)

    observed_at = row.get("observed_at")
    if observed_at is None:
        from datetime import datetime, timezone
        observed_at = datetime.now(timezone.utc)

    score_val, scored_at_ts, score_ver = score_event(
        feed_type=feed_type,
        cvss_score=None,    # RSS/TAXII path — no CVSS at this stage
        brand_severity=None,
        observed_at=observed_at,
        source_confidence=src_conf,
        tag_relevance=0.0,  # project context not available at ingest; rescore applies
        weights=ScoringWeights(),
    )
    row["score"] = score_val
    row["scored_at"] = scored_at_ts
    row["score_version"] = score_ver

VALID_STATUSES: frozenset[str] = frozenset({
    "ok",
    "rate_limited",
    "http_error",
    "network_error",
    "parse_error",
})


def _persist_event(session: Session, row: dict) -> int:
    """Insert one event row with ON CONFLICT (source_id, content_hash, observed_at) DO NOTHING.

 Returns: 1 if inserted, 0 if conflict skipped. Caller is responsible
 for `session.commit` at the end of the batch.

 The three-column conflict target matches the unique index
 uq_events_source_content_hash created by migration 002 — TimescaleDB
 requires the partition column (observed_at) in any unique index on a
 hypertable. The row dict MUST include observed_at (set to the feed
 item's published/modified timestamp so re-fetches produce identical
 triples and are silently dropped).

 Phase 10: events.project_id is NOT NULL (migration 009 dropped the default).
 Workers that don't know a project binding yet (RSS/NVD/TAXII ingest) default
 to LEGACY_PROJECT_ID so pre-project-scoping feeds continue to land. A future
 plan will thread project_id through the worker → source-binding resolution.
"""
    # Phase 10: ensure every row carries a project_id. Default to the LEGACY
    # sentinel when unset so feed workers (rss/nvd/taxii) that haven't been
    # updated yet don't blow up against the NOT NULL constraint.
    if row.get("project_id") is None:
        from app.models.projects import LEGACY_PROJECT_ID  # lazy import (avoids cycles)
        row["project_id"] = LEGACY_PROJECT_ID

    # MAP-05 — resolve geo at ingest if worker has not pre-populated
    if row.get("geo_lat") is None or row.get("geo_lon") is None:
        from app.services.geo import resolve_geo  # lazy import — keeps worker boot cheap
        lat, lon, cc = resolve_geo(row.get("raw_stix"))
        if lat is not None and lon is not None:
            row["geo_lat"] = lat
            row["geo_lon"] = lon
            if cc is not None and row.get("country_code") is None:
                row["country_code"] = cc

    #+ article enrichment — regex-extract CVE IDs, ATT&CK technique
    # IDs, IOCs, severity, country hints from title + description prose.
    # Deterministic (no NLP inference). Extracted ATT&CK IDs get feed_asserted
    # provenance because the text literally contains them.
    from app.services.enrichment import (  # lazy import
        enrich_event,
        merge_enrichment_into_event_row,
        attack_technique_tag_rows,
    )
    enrichment = enrich_event(row.get("title"), row.get("description"))
    merge_enrichment_into_event_row(row, enrichment)

    # Phase 15 / SCR-01: populate score, scored_at, score_version at INSERT time.
    # Pure scoring function — no additional DB writes. One SELECT on sources.
    _inject_score_into_row(session, row)

    stmt = (
        pg_insert(Event.__table__)
        .values(**row)
        .on_conflict_do_nothing(
            index_elements=["source_id", "content_hash", "observed_at"]
        )
        .returning(Event.__table__.c.id, Event.__table__.c.observed_at)
    )
    result = session.execute(stmt)
    inserted = result.fetchone()
    if inserted is None:
        return 0

    # Phase 16 MON-01: bump last_event_at after successful insert
    source_id_val = row.get("source_id")
    if source_id_val is not None:
        bump_last_event_at(session, source_id_val)

    # Fire-and-forget ATT&CK tag rows for extracted techniques. If the ID
    # does not exist in attack_techniques catalog the FK check fails — we
    # swallow individual failures so ingest stays green (scope-safety).
    from sqlalchemy.dialects.postgresql import insert as _pg_insert  # noqa: PLC0415
    from app.models.tags import AttackTechniqueTag  # noqa: PLC0415
    for tag_row in attack_technique_tag_rows(inserted[0], enrichment):
        try:
            session.execute(
                _pg_insert(AttackTechniqueTag.__table__)
                .values(**tag_row)
                .on_conflict_do_nothing()
            )
        except Exception:  # noqa: BLE001
            # Unknown technique ID → skip. Caller transaction continues.
            pass

    return 1


def update_source_health(
    session: Session,
    source_id: uuid.UUID,
    *,
    status: str,
    succeeded: bool,
) -> None:
    """Update sources.last_polled_at, last_status, consecutive_failures —.

 - `last_polled_at` → now (DB-side clock, not Python's)
 - `last_status` → one of VALID_STATUSES
 - `consecutive_failures` → 0 on success, else self-increment (+1)

 Caller commits the transaction — this helper only issues the UPDATE.
"""
    if status not in VALID_STATUSES:
        raise ValueError(
            f"invalid status {status!r}; must be one of {sorted(VALID_STATUSES)}"
        )
    values: dict = {
        "last_polled_at": text("now()"),
        "last_status": status,
    }
    if succeeded:
        values["consecutive_failures"] = 0
    else:
        values["consecutive_failures"] = Source.consecutive_failures + 1
    stmt = update(Source).where(Source.id == source_id).values(**values)
    session.execute(stmt)

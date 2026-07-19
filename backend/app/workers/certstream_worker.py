"""CertStream WebSocket consumer - CERT-01/02.

Long-lived asyncio process. Entry point: python -m app.workers.certstream_worker
Connects to wss://certstream.calidog.io (or CERTSTREAM_URL env override).
Filters CT log entries against project brand_terms patterns.
Matches upserted into brand_matches with match_source='certstream'.
Synthesised events inserted into events table with tag 'brand-match:certstream'.
Pattern set refreshed from DB every 30 seconds (atomic replacement, no mutation).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import NamedTuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.services.brand_synth import build_event_dict

log = logging.getLogger(__name__)

CERTSTREAM_URI = os.environ.get("CERTSTREAM_URL", "wss://certstream.calidog.io")
PATTERN_REFRESH_INTERVAL = 30  # seconds


class _ProjectPattern(NamedTuple):
    project_id: UUID
    brand_term_id: UUID
    value: str
    term_type: str


# ── Public helpers (tested directly) ─────────────────────────────────────────


def _extract_domains(frame: dict) -> list[str]:
    """Extract all_domains from a certificate_update frame. Returns [] for other types."""
    if frame.get("message_type") != "certificate_update":
        return []
    return frame.get("data", {}).get("leaf_cert", {}).get("all_domains", [])


def _matches_pattern(domain: str, pattern: str) -> bool:
    """True if pattern substring found in domain (case-insensitive)."""
    return pattern.lower() in domain.lower()


def _build_match_dict(*, domain: str, pattern: str, project_id: str | UUID) -> dict:
    """Build a match dict compatible with brand_synth.build_event_dict."""
    return {
        "match_source": "certstream",
        "matched_value": domain,
        "brand_term_id": str(pattern),
        "project_id": str(project_id),
        "severity": "medium",  # default; brand_synth may override
    }


# ── DB helpers ────────────────────────────────────────────────────────────────


async def _load_patterns(session: AsyncSession) -> list[_ProjectPattern]:
    """Load brand_terms of type 'domain' or 'product' for certstream_enabled projects."""
    from sqlalchemy import text  # noqa: PLC0415

    result = await session.execute(
        text(
            "SELECT bt.id, bt.project_id, bt.value, bt.term_type "
            "FROM brand_terms bt "
            "JOIN projects p ON p.id = bt.project_id "
            "WHERE p.certstream_enabled = TRUE "
            "  AND p.archived IS NOT TRUE "
            "  AND bt.term_type IN ('domain', 'product')"
        )
    )
    return [
        _ProjectPattern(
            project_id=row.project_id,
            brand_term_id=row.id,
            value=row.value,
            term_type=row.term_type,
        )
        for row in result.fetchall()
    ]


_UPSERT_SQL = """
INSERT INTO brand_matches (
    project_id, brand_term_id, matched_value, match_source, severity,
    match_metadata, first_seen, last_seen, lifecycle_status
) VALUES (
    CAST(:project_id AS uuid), CAST(:brand_term_id AS uuid),
    :matched_value, 'certstream', 'medium',
    '{}', now(), now(), 'new'
)
ON CONFLICT (project_id, brand_term_id, matched_value, match_source)
DO UPDATE SET last_seen = now()
RETURNING id, webhook_fired_at, first_seen
"""

_EVENT_INSERT_SQL = """
INSERT INTO events (
    source_id, stix_type, stix_id, title, description,
    observed_at, tags, content_hash, raw_stix, project_id,
    score, scored_at, score_version
) VALUES (
    NULL, :stix_type, :stix_id, :title, :description,
    :observed_at, :tags, :content_hash, CAST(:raw_stix AS jsonb),
    CAST(:project_id AS uuid),
    :score, :scored_at, :score_version
)
ON CONFLICT (source_id, content_hash, observed_at) DO NOTHING
"""


async def _upsert_match(session: AsyncSession, domain: str, pattern: _ProjectPattern) -> None:
    """Upsert a BrandMatch row for a CertStream hit, then synthesise an event row.

    Replicates the two-step pattern from brand_monitor.py _maybe_synth:
      1. INSERT INTO brand_matches ... ON CONFLICT DO UPDATE (upsert)
      2. call build_event_dict(match=..., term=...) -> INSERT the returned
         event dict into events table

    This ensures ROADMAP criterion CERT-02 ('persist as brand-monitor events with
    tag_source=certstream') is satisfied - brand_matches alone is insufficient.
    """
    from sqlalchemy import text  # noqa: PLC0415

    # Step 1 - upsert brand_matches row
    result = await session.execute(
        text(_UPSERT_SQL),
        {
            "project_id": str(pattern.project_id),
            "brand_term_id": str(pattern.brand_term_id),
            "matched_value": domain,
        },
    )
    stored = result.mappings().one()

    # Only synthesise an event if webhook_fired_at is NULL (matches brand_monitor pattern)
    if stored.get("webhook_fired_at") is not None:
        await session.commit()
        return

    # Step 2 - build event dict using brand_synth (matches _maybe_synth in brand_monitor.py)
    match_dict = {
        "id": stored["id"],
        "project_id": pattern.project_id,
        "brand_term_id": pattern.brand_term_id,
        "matched_value": domain,
        "match_source": "certstream",
        "severity": "medium",
        "first_seen": stored.get("first_seen", datetime.now(timezone.utc)),
    }
    term_dict = {
        "id": pattern.brand_term_id,
        "value": pattern.value,
        "term_type": pattern.term_type,
    }
    event_dict = build_event_dict(match=match_dict, term=term_dict)

    # SCR-01: compute score at INSERT time (mirrors brand_monitor._maybe_synth)
    from app.services.scoring import score_event, ScoringWeights  # noqa: PLC0415
    from app.services.scoring.defaults import DEFAULT_SOURCE_CONFIDENCE  # noqa: PLC0415

    _score_val, _scored_at, _score_ver = score_event(
        feed_type="rss",
        cvss_score=None,
        brand_severity="medium",
        observed_at=event_dict["observed_at"],
        source_confidence=DEFAULT_SOURCE_CONFIDENCE.get("rss", 0.7),
        tag_relevance=0.0,
        weights=ScoringWeights(),
    )

    try:
        await session.execute(
            text(_EVENT_INSERT_SQL),
            {
                "stix_type": event_dict["stix_type"],
                "stix_id": event_dict["stix_id"],
                "title": event_dict["title"],
                "description": event_dict["description"],
                "observed_at": event_dict["observed_at"],
                "tags": event_dict["tags"],
                "content_hash": event_dict["content_hash"],
                "raw_stix": json.dumps(event_dict["raw_stix"]),
                "project_id": str(event_dict["project_id"]),
                "score": _score_val,
                "scored_at": _scored_at,
                "score_version": _score_ver,
            },
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("certstream_synth_event_insert_failed exc=%s", exc)

    await session.commit()


# ── Main loops ────────────────────────────────────────────────────────────────

_CURRENT_PATTERNS: list[_ProjectPattern] = []


async def _pattern_refresh_loop(session_factory: async_sessionmaker) -> None:
    """Reload patterns from DB every 30s. Replace reference atomically - no mutation."""
    global _CURRENT_PATTERNS  # noqa: PLW0603
    while True:
        try:
            async with session_factory() as session:
                patterns = await _load_patterns(session)
            _CURRENT_PATTERNS = patterns  # atomic replacement
            log.debug("certstream_patterns_refreshed count=%d", len(patterns))
        except Exception as exc:  # noqa: BLE001
            log.warning("certstream_pattern_refresh_failed error=%s", exc)
        await asyncio.sleep(PATTERN_REFRESH_INTERVAL)


async def _certstream_loop(session_factory: async_sessionmaker) -> None:
    """Persistent WebSocket consumer. websockets 16.0 handles reconnect."""
    from websockets.asyncio.client import connect  # noqa: PLC0415

    async for websocket in connect(CERTSTREAM_URI):
        log.info("certstream_connected uri=%s", CERTSTREAM_URI)
        try:
            async for raw_message in websocket:
                try:
                    frame = json.loads(raw_message)
                except json.JSONDecodeError:
                    continue
                domains = _extract_domains(frame)
                for domain in domains:
                    patterns = _CURRENT_PATTERNS  # read current reference
                    for pattern in patterns:
                        if _matches_pattern(domain, pattern.value):
                            async with session_factory() as session:
                                await _upsert_match(session, domain, pattern)
                            log.debug(
                                "certstream_match domain=%s pattern=%s project=%s",
                                domain,
                                pattern.value,
                                pattern.project_id,
                            )
        except Exception:  # noqa: BLE001
            log.warning("certstream_connection_closed - reconnecting")
            continue


async def main() -> None:
    """Entry point. Runs pattern refresh + certstream consumer concurrently."""
    from app.config import settings  # noqa: PLC0415

    engine = create_async_engine(settings.DATABASE_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Initial load before entering loops
    async with session_factory() as session:
        initial = await _load_patterns(session)
    global _CURRENT_PATTERNS  # noqa: PLW0603
    _CURRENT_PATTERNS = initial

    async with asyncio.TaskGroup() as tg:
        tg.create_task(_pattern_refresh_loop(session_factory))
        tg.create_task(_certstream_loop(session_factory))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())

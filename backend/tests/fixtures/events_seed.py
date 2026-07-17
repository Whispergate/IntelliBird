"""Deterministic events seed for integration tests.

Contract:
- 3 sources (rss, taxii, nvd) with known UUIDs
- 50 events distributed:
 - source 1 (rss): 20 events, TLP clear, visibility shared
 - source 2 (taxii): 20 events, TLP amber, visibility red_only (10) + shared (10)
 - source 3 (nvd): 10 events, TLP green, visibility blue_only
- All observed_at in 2025-09-01..2025-10-20 (30-day span, deterministic hourly step)
- Tags mix: events 0-9 have tags=["apt28"], 10-19 have tags=["phishing"],
 20-29 have tags=["apt28","phishing"], 30+ have tags=[] (NOT NULL empty,
 to exercise COALESCE path)
- Events 5, 15, 25 have tags=NULL explicitly (to exercise ARRAY NULL coalesce pitfall)
- Event 0 has raw_stix={"objects":[{"type":"relationship",
 "source_ref":"threat-actor--aaa","target_ref":"malware--bbb",
 "relationship_type":"uses"}]} for graph depth-2 test
- Event 0 linked in attack_technique_tags to T1190
- Event 1 linked in attack_technique_tags to T1566 and T1059
- Title pattern: f"Event {i} {random_word}" where random_word is picked
 deterministically from ["APT28", "phishing", "vulnerability", "exploit", "campaign"]
- Description pattern: f"Description for event {i} about {random_word}"
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

# Fixed UUIDs — tests can reference directly
SOURCE_RSS   = uuid.UUID("00000000-0000-4000-8000-000000000001")
SOURCE_TAXII = uuid.UUID("00000000-0000-4000-8000-000000000002")
SOURCE_NVD   = uuid.UUID("00000000-0000-4000-8000-000000000003")
# every event row must carry a project_id; legacy seeds map to
# the LEGACY_PROJECT_ID sentinel row created by migration 009.
LEGACY_PROJECT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
# TLP markings — STIX 2.1 TLP 2.0 canonical names + stable test UUIDs
# seed_50_events upserts these into tlp_markings so filters resolve correctly.
TLP_CLEAR    = uuid.UUID("00000000-0000-4000-9000-000000000001")
TLP_GREEN    = uuid.UUID("00000000-0000-4000-9000-000000000002")
TLP_AMBER    = uuid.UUID("00000000-0000-4000-9000-000000000003")

_WORDS = ["APT28", "phishing", "vulnerability", "exploit", "campaign"]

# Fixed event UUIDs — deterministic across test runs
_EVENT_UUIDS = [
    uuid.UUID(f"00000000-0000-4000-8001-{i:012d}") for i in range(50)
]

_BASE_OBSERVED_AT = datetime(2025, 9, 1, tzinfo=timezone.utc)


def _tags_for(i: int) -> list[str] | None:
    """Return deterministic tags for event index i."""
    # Explicit NULL for events 5, 15, 25 — exercises ARRAY NULL coalesce path
    if i in (5, 15, 25):
        return None
    if i < 10:
        return ["apt28"]
    if i < 20:
        return ["phishing"]
    if i < 30:
        return ["apt28", "phishing"]
    # 30+ → NOT NULL empty array
    return []


def _source_tlp_visibility(i: int) -> tuple[str, str, str]:
    """Return (source_id_str, tlp_marking_id_str, visibility) for event index i."""
    if i < 20:
        # source 1 (rss): TLP clear, all shared
        return str(SOURCE_RSS), str(TLP_CLEAR), "shared"
    if i < 40:
        # source 2 (taxii): TLP amber, first 10 red_only, next 10 shared
        vis = "red_only" if (i - 20) < 10 else "shared"
        return str(SOURCE_TAXII), str(TLP_AMBER), vis
    # source 3 (nvd): TLP green, all blue_only
    return str(SOURCE_NVD), str(TLP_GREEN), "blue_only"


async def seed_50_events(session: AsyncSession) -> list[dict]:
    """Seed 3 sources + 50 events. Returns list of inserted row dicts.

 Clears sources, events, attack_technique_tags before inserting.
 Commits once at end; rolls back on exception.
"""
    try:
        # Ensure TLP markings exist with STIX 2.1 TLP 2.0 names (used by filter API)
        await session.execute(
            sa.text("""
 INSERT INTO tlp_markings (id, name) VALUES
 (:c_id, 'clear'),
 (:g_id, 'green'),
 (:a_id, 'amber')
 ON CONFLICT (id) DO NOTHING
"""),
            {
                "c_id": str(TLP_CLEAR),
                "g_id": str(TLP_GREEN),
                "a_id": str(TLP_AMBER),
            },
        )

        # Clear existing data (CASCADE handles FK dependents)
        await session.execute(
            sa.text("TRUNCATE TABLE attack_technique_tags, events, sources RESTART IDENTITY CASCADE")
        )

        # Insert 3 sources
        await session.execute(
            sa.text("""
 INSERT INTO sources (id, name, feed_type, url, poll_interval_sec, hot_retention_days,
 enabled, archive_policy)
 VALUES
 (:id1, 'Seed RSS Source', 'rss', 'http://seed/rss', 3600, 30, true, 'keep'),
 (:id2, 'Seed TAXII Source', 'taxii', 'http://seed/taxii', 3600, 30, true, 'keep'),
 (:id3, 'Seed NVD Source', 'nvd', 'http://seed/nvd', 3600, 30, true, 'keep')
"""),
            {
                "id1": str(SOURCE_RSS),
                "id2": str(SOURCE_TAXII),
                "id3": str(SOURCE_NVD),
            },
        )

        inserted: list[dict] = []

        for i in range(50):
            word = _WORDS[i % len(_WORDS)]
            eid = _EVENT_UUIDS[i]
            observed_at = _BASE_OBSERVED_AT + timedelta(hours=i)
            source_id, tlp_id, visibility = _source_tlp_visibility(i)
            tags = _tags_for(i)
            title = f"Event {i} {word}"
            description = f"Description for event {i} about {word}"

            # Event 0: include raw_stix with a STIX relationship SRO for graph depth-2 test
            if i == 0:
                raw_stix = json.dumps({
                    "objects": [
                        {
                            "type": "relationship",
                            "source_ref": "threat-actor--aaa",
                            "target_ref": "malware--bbb",
                            "relationship_type": "uses",
                        }
                    ]
                })
            else:
                raw_stix = None

            # Build tags SQL fragment — NULL vs ARRAY literal
            if tags is None:
                tags_sql = "NULL"
                tags_param: dict = {}
            elif len(tags) == 0:
                tags_sql = "ARRAY[]::text[]"
                tags_param = {}
            else:
                tags_sql = "ARRAY[" + ", ".join(f":tag_{i}_{j}" for j in range(len(tags))) + "]"
                tags_param = {f"tag_{i}_{j}": t for j, t in enumerate(tags)}

            params: dict = {
                "id": str(eid),
                "source_id": source_id,
                "project_id": str(LEGACY_PROJECT_ID),
                "stix_type": "indicator",
                "observed_at": observed_at,
                "title": title,
                "description": description,
                "tlp_marking_id": tlp_id,
                "visibility": visibility,
                "content_hash": f"seed-hash-{i:04d}",
                "raw_stix": raw_stix,
                **tags_param,
            }

            await session.execute(
                sa.text(f"""
 INSERT INTO events
 (id, source_id, project_id, stix_type, observed_at, title, description,
 tlp_marking_id, visibility, content_hash, raw_stix, tags)
 VALUES
 (:id,:source_id,:project_id,:stix_type,:observed_at,:title,:description,
:tlp_marking_id,:visibility,:content_hash,
 CAST(:raw_stix AS jsonb), {tags_sql})
"""),
                params,
            )

            inserted.append({
                "id": str(eid),
                "observed_at": observed_at.isoformat(),
                "source_id": source_id,
                "title": title,
                "tlp_marking_id": tlp_id,
                "visibility": visibility,
                "tags": tags,
            })

        # Insert attack_technique_tags for events 0 and 1
        att_rows = [
            # Event 0 → T1190
            {
                "event_id": str(_EVENT_UUIDS[0]),
                "observed_at": (_BASE_OBSERVED_AT + timedelta(hours=0)).isoformat(),
                "technique_id": "T1190",
                "tag_source": "feed_asserted",
            },
            # Event 1 → T1566
            {
                "event_id": str(_EVENT_UUIDS[1]),
                "observed_at": (_BASE_OBSERVED_AT + timedelta(hours=1)).isoformat(),
                "technique_id": "T1566",
                "tag_source": "feed_asserted",
            },
            # Event 1 → T1059
            {
                "event_id": str(_EVENT_UUIDS[1]),
                "observed_at": (_BASE_OBSERVED_AT + timedelta(hours=1)).isoformat(),
                "technique_id": "T1059",
                "tag_source": "feed_asserted",
            },
        ]
        for row in att_rows:
            await session.execute(
                sa.text("""
 INSERT INTO attack_technique_tags
 (event_id, technique_id, tag_source)
 VALUES
 (:event_id,:technique_id,:tag_source)
 ON CONFLICT DO NOTHING
"""),
                row,
            )

        await session.commit()
        return inserted

    except Exception:
        await session.rollback()
        raise

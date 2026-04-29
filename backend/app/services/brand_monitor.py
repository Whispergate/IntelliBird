"""Per-project brand monitor orchestrator (Phase 12 Plan 04 / BRP-02 + BRP-03).

Composes the Wave 2 primitives into a single async `scan_project(session, project_id)`
entry point. Three source branches run per term:

    - FTS branch     → project-scoped events search (field-scope branches on term
                      length + stoplist membership per CONTEXT.md)
    - CT log branch  → crt.sh wildcard query for term_type in {domain, product}
    - dnstwist branch→ subprocess run for term_type=='domain', batched 5 at a time
                      with asyncio.sleep(5) between batches and timeout=120s

All matches upsert into brand_matches via ON CONFLICT on the 4-tuple
(project_id, brand_term_id, matched_value, match_source). Severity is computed
by brand_severity.score; matches at or above BRAND_WEBHOOK_SEVERITY_THRESHOLD
with a NULL webhook_fired_at are synthesised into a canonical event via
brand_synth.build_event_dict.

dnstwist subprocess failures (TimeoutExpired / CalledProcessError / non-zero rc /
malformed JSON) are logged + skipped — they never raise out of scan_project.
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.brand_severity import score
from app.services.brand_stoplist import is_short, is_stoplisted, load_runtime_stoplist_for_project
from app.services.brand_synth import build_event_dict
from app.services.crtsh_client import fetch_certs
from app.services.dnstwist_parser import parse_dnstwist_output
from app.services.source_health import async_bump_last_event_at

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DNSTWIST_BATCH_SIZE = 5
DNSTWIST_BATCH_SLEEP_SECONDS = 5
DNSTWIST_TIMEOUT_SECONDS = 120
DNSTWIST_THREADS = 10

_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}


# ---------------------------------------------------------------------------
# FTS field-scope branching
# ---------------------------------------------------------------------------

_FTS_SQL_RESTRICTED = text(
    """
    SELECT id, title, stix_id
    FROM events
    WHERE project_id = CAST(:project_id AS uuid)
      AND to_tsvector('english', coalesce(title,'') || ' ' || coalesce(stix_id,''))
          @@ plainto_tsquery('english', :term)
    ORDER BY observed_at DESC
    LIMIT 500
    """
)

_FTS_SQL_FULL = text(
    """
    SELECT id, title, stix_id
    FROM events
    WHERE project_id = CAST(:project_id AS uuid)
      AND search_tsv @@ plainto_tsquery('english', :term)
    ORDER BY observed_at DESC
    LIMIT 500
    """
)


def _fts_sql_for_term(
    term_value: str,
    runtime_stoplist: "frozenset[str] | None" = None,
):
    """Return the FTS SQL clause for a given term value.

    Short (len<6) OR stoplisted terms use the restricted title+stix_id scope;
    everything else uses the full search_tsv.

    Pass a pre-loaded `runtime_stoplist` frozenset (from
    load_runtime_stoplist_for_project) to include per-project terms in the
    stoplist check without re-querying the DB each call.
    """
    if is_short(term_value) or is_stoplisted(term_value, runtime_stoplist=runtime_stoplist):
        return _FTS_SQL_RESTRICTED
    return _FTS_SQL_FULL


# ---------------------------------------------------------------------------
# Branch runners
# ---------------------------------------------------------------------------

async def _fts_scan(
    session: AsyncSession,
    project_id: UUID,
    term: dict,
    runtime_stoplist: "frozenset[str] | None" = None,
) -> list[dict]:
    sql = _fts_sql_for_term(term["value"], runtime_stoplist=runtime_stoplist)
    result = await session.execute(sql, {"project_id": str(project_id), "term": term["value"]})
    rows = result.mappings().all()
    out: list[dict] = []
    for row in rows:
        matched = (row.get("title") or row.get("stix_id") or "")[:200]
        out.append(
            {
                "matched_value": matched,
                "match_source": "fts",
                "match_metadata": {"event_id": str(row["id"])},
                "event_id": row["id"],
                "lookup_success": False,
            }
        )
    return out


async def _ctlog_scan(term: dict) -> list[dict]:
    if term["term_type"] not in ("domain", "product"):
        return []
    certs = await fetch_certs(term["value"])
    return [
        {
            "matched_value": c["matched_value"],
            "match_source": "ct_log",
            "match_metadata": {
                "not_before": c.get("not_before"),
                "issuer": c.get("issuer_name"),
                "min_cert_id": c.get("min_cert_id"),
            },
            "lookup_success": False,
        }
        for c in certs
    ]


def _run_dnstwist_one(term_value: str) -> list[dict] | None:
    """Invoke dnstwist for a single term. Returns parsed perms or None on error.

    Handles TimeoutExpired / CalledProcessError / non-zero rc / malformed JSON by
    logging + returning None — never raises.
    """
    cmd = ["dnstwist", "--threads", str(DNSTWIST_THREADS), "--format", "json", term_value]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=DNSTWIST_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        log.warning("brand_dnstwist_timeout term=%s", term_value)
        return None
    except subprocess.CalledProcessError as exc:
        log.warning("brand_dnstwist_error term=%s rc=%s", term_value, getattr(exc, "returncode", "?"))
        return None
    except Exception as exc:  # pragma: no cover — defensive
        log.warning("brand_dnstwist_unexpected term=%s exc=%s", term_value, exc)
        return None

    if proc.returncode != 0:
        log.warning(
            "brand_dnstwist_nonzero term=%s rc=%s stderr=%s",
            term_value,
            proc.returncode,
            (proc.stderr or "")[:500],
        )
        return None

    try:
        payload = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        log.warning("brand_dnstwist_bad_json term=%s", term_value)
        return None

    try:
        return parse_dnstwist_output(payload)
    except Exception as exc:  # pragma: no cover — parser is defensive, but guard anyway
        log.warning("brand_dnstwist_parse_failed term=%s exc=%s", term_value, exc)
        return None


async def _run_dnstwist_batch(terms: list[dict]) -> dict[str, list[dict]]:
    """Run dnstwist synchronously per term in a batch — returns {term_value: perms}."""
    results: dict[str, list[dict]] = {}
    for t in terms:
        perms = await asyncio.to_thread(_run_dnstwist_one, t["value"])
        if perms is None:
            continue
        results[t["value"]] = perms
    return results


# ---------------------------------------------------------------------------
# Upsert + synth
# ---------------------------------------------------------------------------

_UPSERT_SQL = text(
    """
    INSERT INTO brand_matches (
        project_id, brand_term_id, matched_value, match_source, severity,
        match_metadata, event_id, first_seen, last_seen, lifecycle_status
    ) VALUES (
        CAST(:project_id AS uuid), CAST(:brand_term_id AS uuid),
        :matched_value, :match_source, :severity,
        CAST(:match_metadata AS jsonb), :event_id, :now, :now, 'new'
    )
    ON CONFLICT (project_id, brand_term_id, matched_value, match_source)
    DO UPDATE SET last_seen = EXCLUDED.last_seen,
                  match_metadata = EXCLUDED.match_metadata
    RETURNING id, webhook_fired_at, first_seen
    """
)


async def _upsert_match(
    session: AsyncSession,
    *,
    project_id: UUID,
    term: dict,
    match: dict,
    severity: str,
) -> dict:
    result = await session.execute(
        _UPSERT_SQL,
        {
            "project_id": str(project_id),
            "brand_term_id": str(term["id"]),
            "matched_value": match["matched_value"],
            "match_source": match["match_source"],
            "severity": severity,
            "match_metadata": json.dumps(match.get("match_metadata") or {}),
            "event_id": match.get("event_id"),
            "now": datetime.now(timezone.utc),
        },
    )
    row = result.mappings().one()
    return dict(row)


_EVENT_INSERT_SQL = text(
    """
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
    RETURNING id
    """
)

_MARK_FIRED_SQL = text(
    """
    UPDATE brand_matches
       SET webhook_fired_at = :now,
           event_id = COALESCE(:event_id, event_id)
     WHERE id = CAST(:match_id AS uuid)
    """
)


def _threshold_rank() -> int:
    threshold_name = (getattr(settings, "BRAND_WEBHOOK_SEVERITY_THRESHOLD", "HIGH") or "HIGH").lower()
    return _SEVERITY_RANK.get(threshold_name, _SEVERITY_RANK["high"])


async def _maybe_synth(
    session: AsyncSession,
    *,
    project_id: UUID,
    term: dict,
    match: dict,
    stored: dict,
    severity: str,
) -> bool:
    """If severity ≥ threshold and webhook_fired_at IS NULL, build + insert event.

    Returns True when an event was synthesised (match upserted to events table).
    """
    if _SEVERITY_RANK[severity] < _threshold_rank():
        return False
    if stored.get("webhook_fired_at") is not None:
        return False

    event_dict = build_event_dict(
        match={
            "id": stored["id"],
            "project_id": project_id,
            "brand_term_id": term["id"],
            "matched_value": match["matched_value"],
            "match_source": match["match_source"],
            "severity": severity,
            "first_seen": stored.get("first_seen"),
        },
        term={"id": term["id"], "value": term["value"], "term_type": term["term_type"]},
    )

    # Phase 15 / SCR-01: compute score at INSERT time.
    # brand_synth path uses brand_severity (low/medium/high) as the CVSS proxy.
    from app.services.scoring import score_event, ScoringWeights  # noqa: PLC0415
    from app.services.scoring.defaults import DEFAULT_SOURCE_CONFIDENCE  # noqa: PLC0415
    _brand_score_val, _brand_scored_at, _brand_score_ver = score_event(
        feed_type="rss",  # brand events have no source feed_type; treat as rss
        cvss_score=None,
        brand_severity=severity,
        observed_at=event_dict["observed_at"],
        source_confidence=DEFAULT_SOURCE_CONFIDENCE.get("rss", 0.7),
        tag_relevance=0.0,
        weights=ScoringWeights(),
    )

    event_id: Any = None
    try:
        result = await session.execute(
            _EVENT_INSERT_SQL,
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
                "score": _brand_score_val,
                "scored_at": _brand_scored_at,
                "score_version": _brand_score_ver,
            },
        )
        row = result.first()
        if row is not None:
            event_id = row[0]
            # Phase 16 MON-01: bump last_event_at after successful insert
            # Brand synthetic events have source_id=NULL so no sources row to update;
            # call is a deliberate no-op guard for when a synth source is wired (Phase 17).
            synth_source_id = event_dict.get("source_id")
            if synth_source_id is not None:
                await async_bump_last_event_at(session, synth_source_id)
    except Exception as exc:
        log.warning("brand_synth_event_insert_failed exc=%s", exc)

    await session.execute(
        _MARK_FIRED_SQL,
        {
            "now": datetime.now(timezone.utc),
            "event_id": event_id,
            "match_id": str(stored["id"]),
        },
    )
    return True


# ---------------------------------------------------------------------------
# Orchestrator entry point
# ---------------------------------------------------------------------------

_TERMS_SQL = text(
    """
    SELECT id, term_type, value, mode, archived, high_noise_risk
    FROM brand_terms
    WHERE project_id = CAST(:project_id AS uuid)
      AND mode = 'active'
      AND archived = false
    """
)


async def scan_project(session: AsyncSession, project_id: UUID) -> dict[str, int]:
    """Run the full FTS + CT log + dnstwist scan for all active terms in a project.

    Returns a stats dict: {"fts": n, "ct_log": n, "dnstwist": n, "synthesised": n}.

    Phase 21 / BRAND-01: loads per-project stoplist ONCE at scan entry and threads
    the frozenset through to _fts_sql_for_term so FTS branch reflects project-level
    suppression terms alongside the global DEFAULT_STOPLIST + env extras.
    """
    # Load per-project stoplist once — includes DEFAULT ∪ env ∪ project terms
    runtime_stoplist = await load_runtime_stoplist_for_project(session, project_id)

    terms_result = await session.execute(_TERMS_SQL, {"project_id": str(project_id)})
    terms = [dict(r) for r in terms_result.mappings().all()]

    stats = {"fts": 0, "ct_log": 0, "dnstwist": 0, "synthesised": 0}

    # ---- FTS branch ----
    for term in terms:
        for match in await _fts_scan(session, project_id, term, runtime_stoplist=runtime_stoplist):
            severity = score("fts", False)
            stored = await _upsert_match(
                session, project_id=project_id, term=term, match=match, severity=severity
            )
            synthed = await _maybe_synth(
                session,
                project_id=project_id,
                term=term,
                match=match,
                stored=stored,
                severity=severity,
            )
            stats["fts"] += 1
            if synthed:
                stats["synthesised"] += 1

    # ---- CT log branch ----
    for term in terms:
        for match in await _ctlog_scan(term):
            severity = score("ct_log", False)
            stored = await _upsert_match(
                session, project_id=project_id, term=term, match=match, severity=severity
            )
            synthed = await _maybe_synth(
                session,
                project_id=project_id,
                term=term,
                match=match,
                stored=stored,
                severity=severity,
            )
            stats["ct_log"] += 1
            if synthed:
                stats["synthesised"] += 1

    # ---- dnstwist branch (batched 5, 5s sleep between batches) ----
    domain_terms = [t for t in terms if t["term_type"] == "domain"]
    for i in range(0, len(domain_terms), DNSTWIST_BATCH_SIZE):
        batch = domain_terms[i : i + DNSTWIST_BATCH_SIZE]
        batch_perms = await _run_dnstwist_batch(batch)
        for term in batch:
            for perm in batch_perms.get(term["value"], []):
                match = {
                    "matched_value": perm["matched_value"],
                    "match_source": "dnstwist",
                    "match_metadata": {k: v for k, v in perm.items() if k != "matched_value"},
                }
                severity = score("dnstwist", bool(perm.get("lookup_success")))
                stored = await _upsert_match(
                    session, project_id=project_id, term=term, match=match, severity=severity
                )
                synthed = await _maybe_synth(
                    session,
                    project_id=project_id,
                    term=term,
                    match=match,
                    stored=stored,
                    severity=severity,
                )
                stats["dnstwist"] += 1
                if synthed:
                    stats["synthesised"] += 1
        if i + DNSTWIST_BATCH_SIZE < len(domain_terms):
            await asyncio.sleep(DNSTWIST_BATCH_SLEEP_SECONDS)

    await session.commit()
    return stats

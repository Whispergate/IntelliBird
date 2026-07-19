"""Per-source retention archiver - STO-01, STO-03, STO-04.

: TimescaleDB add_retention_policy and add_compression_policy are
HYPERTABLE-WIDE (they apply to all rows regardless of source_id). IntelliBird
requires per-source retention, so archiving is done in application SQL via
per-source DELETE (policy=drop) or UPDATE events SET archived=true
(policy=move-to-cold). The events.archived flag is the application-level
'in cold storage' marker (STO-04 - archived rows remain referenceable so
attack graph references do not break).

Scheduled nightly at 03:00 UTC by app.scheduler.jobs (job id 'archiver_nightly').
"""
from __future__ import annotations

import logging

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.crypto import decrypt_credentials

logger = logging.getLogger(__name__)


def _fire_pagerduty_resolves(
    session: Session, source_id: str, event_ids: list[str]
) -> None:
    """Fire PagerDuty resolve POSTs for archived events (best-effort, fire-and-forget).

    Queries for enabled PagerDuty webhooks linked to the source's projects via
    preset_bindings and fires a resolve POST for each (event_id, webhook) pair.

    Called AFTER session.commit() in the move-to-cold path so the HTTP calls
    do not hold the DB transaction open. Failures are logged as warnings, not raised.
    """
    if not event_ids:
        return

    try:
        rows = session.execute(
            text(
                """
                SELECT DISTINCT w.url, w.auth_enc
                FROM webhooks w
                JOIN webhook_preset_bindings b ON b.webhook_id = w.id
                JOIN filter_presets fp ON fp.id = b.preset_id
                JOIN project_sources ps ON ps.project_id = fp.project_id
                WHERE ps.source_id = :source_id
                  AND w.destination_type = 'pagerduty'
                  AND w.enabled = true
                """
            ),
            {"source_id": source_id},
        ).fetchall()
    except Exception as exc:  # noqa: BLE001
        logger.warning("archiver_pd_resolve_query_failed source_id=%s error=%s", source_id, exc)
        return

    for row in rows:
        url = row[0]
        auth_enc = row[1]
        routing_key = ""
        if auth_enc:
            try:
                creds = decrypt_credentials(settings.SECRET_KEY, auth_enc)
                routing_key = creds.get("routing_key", "")
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "archiver_pd_resolve_decrypt_failed source_id=%s error=%s", source_id, exc
                )
        for eid in event_ids:
            try:
                httpx.post(
                    url,
                    json={
                        "routing_key": routing_key,
                        "event_action": "resolve",
                        "dedup_key": eid,
                    },
                    timeout=10.0,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "archiver_pd_resolve_post_failed source_id=%s event_id=%s error=%s",
                    source_id,
                    eid,
                    exc,
                )


def _archive_source(
    session: Session, source_id: str, hot_retention_days: int, policy: str
) -> tuple[int, list[str]]:
    """Apply the source's archive policy to events older than hot_retention_days.

    Returns (rows_affected, archived_event_ids).
    archived_event_ids is non-empty only for move-to-cold (used by caller to fire
    PagerDuty resolve POSTs after session.commit()).
    """
    if policy == "keep":
        return 0, []

    if policy == "drop":
        result = session.execute(
            text(
                "DELETE FROM events "
                "WHERE source_id = :sid "
                "  AND observed_at < now() - (:days || ' days')::interval "
                "  AND archived = false"
            ),
            {"sid": source_id, "days": str(hot_retention_days)},
        )
        return int(result.rowcount or 0), []  # type: ignore[attr-defined]

    if policy == "move-to-cold":
        # Collect IDs BEFORE the UPDATE so we can fire PD resolves post-commit.
        candidate_rows = session.execute(
            text(
                "SELECT id FROM events "
                "WHERE source_id = :sid "
                "  AND observed_at < now() - (:days || ' days')::interval "
                "  AND archived = false"
            ),
            {"sid": source_id, "days": str(hot_retention_days)},
        ).fetchall()
        archived_ids = [str(r[0]) for r in candidate_rows]

        result = session.execute(
            text(
                "UPDATE events "
                "SET archived = true "
                "WHERE source_id = :sid "
                "  AND observed_at < now() - (:days || ' days')::interval "
                "  AND archived = false"
            ),
            {"sid": source_id, "days": str(hot_retention_days)},
        )
        return int(result.rowcount or 0), archived_ids  # type: ignore[attr-defined]

    logger.warning(
        "archiver_unknown_policy source_id=%s policy=%s - treating as keep",
        source_id,
        policy,
    )
    return 0, []


def archive_once(session: Session) -> dict[str, int]:
    """Run one archiver pass across all sources. Returns per-policy row counts.

    Each source is processed and committed individually. A failure in one
    source logs archiver_source_failed and moves on to the next; one bad
    source does not halt the whole run (rollback + continue pattern).
    """
    logger.info("archiver_started")
    totals: dict[str, int] = {"keep": 0, "drop": 0, "move-to-cold": 0}

    rows = session.execute(
        text("SELECT id, hot_retention_days, archive_policy FROM sources")
    ).all()

    for row in rows:
        sid = str(row[0])
        days = int(row[1])
        policy = str(row[2])
        try:
            affected, archived_ids = _archive_source(session, sid, days, policy)
            session.commit()
            totals[policy] = totals.get(policy, 0) + affected
            logger.info(
                "archiver_source source_id=%s policy=%s rows_affected=%d",
                sid,
                policy,
                affected,
            )
            # Fire PagerDuty auto-resolves AFTER commit (must not hold DB transaction open).
            # Best-effort: failures are logged not raised. Only fires for move-to-cold.
            if policy == "move-to-cold" and archived_ids:
                _fire_pagerduty_resolves(session, sid, archived_ids)
        except Exception as e:  # noqa: BLE001
            session.rollback()
            logger.warning(
                "archiver_source_failed source_id=%s policy=%s error=%s",
                sid,
                policy,
                e,
            )

    logger.info(
        "archiver_completed drop=%d move_to_cold=%d keep=%d",
        totals.get("drop", 0),
        totals.get("move-to-cold", 0),
        totals.get("keep", 0),
    )
    return totals

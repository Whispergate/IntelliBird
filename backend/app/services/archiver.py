"""Per-source retention archiver — STO-01, STO-03, STO-04.

Pitfall 3: TimescaleDB add_retention_policy and add_compression_policy are
HYPERTABLE-WIDE (they apply to all rows regardless of source_id). IntelliBird
requires per-source retention, so archiving is done in application SQL via
per-source DELETE (policy=drop) or UPDATE events SET archived=true
(policy=move-to-cold). The events.archived flag is the application-level
'in cold storage' marker (STO-04 — archived rows remain referenceable so
attack graph references do not break).

Scheduled nightly at 03:00 UTC by app.scheduler.jobs (job id 'archiver_nightly').
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _archive_source(session: Session, source_id: str, hot_retention_days: int, policy: str) -> int:
    """Apply the source's archive policy to events older than hot_retention_days.

    Returns the number of rows affected (0 for keep).
    """
    if policy == "keep":
        return 0

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
        return int(result.rowcount or 0)

    if policy == "move-to-cold":
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
        return int(result.rowcount or 0)

    logger.warning(
        "archiver_unknown_policy source_id=%s policy=%s — treating as keep",
        source_id,
        policy,
    )
    return 0


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
            affected = _archive_source(session, sid, days, policy)
            session.commit()
            totals[policy] = totals.get(policy, 0) + affected
            logger.info(
                "archiver_source source_id=%s policy=%s rows_affected=%d",
                sid,
                policy,
                affected,
            )
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

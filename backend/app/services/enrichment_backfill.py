"""One-shot enrichment backfill actor — re-parses existing events' title +
description and merges extracted tags / country_code / ATT&CK tags.

Run manually via:
    docker compose exec -T worker python -m app.services.enrichment_backfill

Or dispatch via Dramatiq:
    from app.services.enrichment_backfill import backfill_enrichment
    backfill_enrichment.send()
"""
from __future__ import annotations

import logging

import dramatiq
from sqlalchemy import create_engine, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.events import Event
from app.models.tags import AttackTechniqueTag
from app.services.enrichment import (
    attack_technique_tag_rows,
    enrich_event,
)

logger = logging.getLogger(__name__)


@dramatiq.actor(queue_name="maintenance", max_retries=0)
def backfill_enrichment(batch_size: int = 500) -> dict:
    """Iterate existing events, enrich description + title, merge results.

    Returns summary dict with counts.
    """
    from app.config import settings  # noqa: PLC0415

    sync_url = settings.DATABASE_URL.replace(
        "postgresql+asyncpg://", "postgresql://"
    ).replace("+asyncpg", "")
    engine = create_engine(sync_url, future=True)

    total = 0
    updated = 0
    tags_written = 0
    country_written = 0
    attack_tags_written = 0

    try:
        with Session(engine) as session:
            stmt = select(
                Event.id,
                Event.observed_at,
                Event.title,
                Event.description,
                Event.tags,
                Event.country_code,
            ).execution_options(stream_results=True)

            for row in session.execute(stmt):
                total += 1
                enrichment = enrich_event(row.title, row.description)
                existing_tags = set(row.tags or [])
                new_tags = existing_tags | enrichment.tags
                country_new = row.country_code or enrichment.country_code

                tag_delta = new_tags != existing_tags
                country_delta = (
                    row.country_code is None
                    and enrichment.country_code is not None
                )

                if tag_delta or country_delta:
                    updated += 1
                    if tag_delta:
                        tags_written += len(new_tags - existing_tags)
                    if country_delta:
                        country_written += 1
                    session.execute(
                        update(Event)
                        .where(
                            Event.id == row.id,
                            Event.observed_at == row.observed_at,
                        )
                        .values(
                            tags=sorted(new_tags),
                            country_code=country_new,
                        )
                    )

                for tag_row in attack_technique_tag_rows(
                    row.id, enrichment, evidence_prefix="backfill"
                ):
                    try:
                        res = session.execute(
                            pg_insert(AttackTechniqueTag.__table__)
                            .values(**tag_row)
                            .on_conflict_do_nothing()
                        )
                        if res.rowcount:
                            attack_tags_written += int(res.rowcount)
                    except Exception:  # noqa: BLE001
                        session.rollback()
                        # reopen transaction
                        continue

                if total % batch_size == 0:
                    session.commit()

            session.commit()
    finally:
        engine.dispose()

    summary = {
        "total_scanned": total,
        "events_updated": updated,
        "new_tags_written": tags_written,
        "country_codes_filled": country_written,
        "attack_tags_written": attack_tags_written,
    }
    logger.info("enrichment_backfill_complete %s", summary)
    return summary


if __name__ == "__main__":
    import json

    result = backfill_enrichment.fn()  # invoke directly, no Dramatiq
    print(json.dumps(result, indent=2))

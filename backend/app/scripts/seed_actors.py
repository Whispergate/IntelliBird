"""Seed threat_actors from MITRE ATT&CK enterprise + ICS matrices at container start.

Invoked by `ops/api-entrypoint.sh` AFTER `alembic upgrade head`.

Idempotent — upserts on mitre_group_id; analyst-edited profile_md is preserved
across re-bootstraps. Falls through TAXII → GitHub → bundled JSON.

NOT a Dramatiq actor: runs synchronously at boot before workers exist.
"""
from __future__ import annotations

import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("seed_actors")

MATRICES = ("enterprise", "ics")


def main() -> None:
    from app.workers.bootstrap import fetch_with_fallback
    from app.workers.actor_writer import upsert_actors_sync

    total = 0
    failed: list[str] = []

    for matrix in MATRICES:
        logger.info("seed_actors: fetching %s ATT&CK bundle", matrix)
        bundle = fetch_with_fallback(matrix)
        if bundle is None:
            logger.error("seed_actors: all sources failed for matrix=%s", matrix)
            failed.append(matrix)
            continue
        count = upsert_actors_sync(bundle, matrix)
        logger.info("seed_actors: upserted %d threat actors from %s", count, matrix)
        total += count

    logger.info("seed_actors: total upserted=%d matrices_failed=%s", total, failed)
    if len(failed) == len(MATRICES):
        sys.exit(1)


if __name__ == "__main__":
    main()

"""Run the IOC backfill once at container start — IOC-07.

Invoked by `ops/api-entrypoint.sh` AFTER `alembic upgrade head` so the
freshly-shipped `iocs` schema is populated from the existing `events`
corpus on first deploy.

Idempotent — second invocation produces ~0 net new rows because
`backfill_iocs_for_project` upserts on `(project_id, type, normalized_value)
NULLS NOT DISTINCT` and the SET clause preserves analyst-set confidence.

NOT a Dramatiq actor: the runtime admin endpoint
(`POST /api/admin/iocs/backfill`) uses `backfill_iocs_actor` for async
processing on the `ingest` queue. This CLI calls the underlying service
function synchronously because it runs once at boot before workers exist.
"""
from __future__ import annotations

import asyncio
import logging
import sys

logger = logging.getLogger("seed_iocs")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


async def _run() -> dict[str, int]:
    from app.database import async_session_factory  # noqa: PLC0415
    from app.services.iocs import backfill_iocs_for_project  # noqa: PLC0415

    async with async_session_factory() as session:
        return await backfill_iocs_for_project(session, project_id=None)


def main() -> int:
    """CLI entry point. Returns 0 on success, 1 on any exception.

    The api-entrypoint.sh wrapper invokes this as a non-fatal best-effort:
    on failure the operator falls back to `POST /api/admin/iocs/backfill`.
    """
    try:
        result = asyncio.run(_run())
        logger.info(
            "seed_iocs_complete events_processed=%d iocs_inserted=%d",
            result.get("events_processed", 0),
            result.get("iocs_inserted", 0),
        )
        # Stdout breadcrumb so the entrypoint log shows the outcome.
        print(f"seed_iocs: {result}", flush=True)
        return 0
    except Exception:  # noqa: BLE001
        logger.exception("seed_iocs_failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())

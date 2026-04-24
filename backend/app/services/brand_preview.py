"""Brand term test-coverage preview — H-5 prevention recipe.

On brand-term dialog value `onBlur`, frontend hits
``/api/projects/{id}/brand/preview?term=...&term_type=...``. This service
counts FTS matches for the candidate term against the last SAMPLE_SIZE events
in the project and returns a noise forecast. Results are cached in Redis under
a per-(project, term, term_type) key with a 60s TTL to prevent dialog-
hammering.

Thresholds (LOCKED per 12-CONTEXT.md §Test-coverage preview at term creation):
  SAMPLE_SIZE           = 1000   last-N events per project
  TOO_BROAD_THRESHOLD   = 0.20   strictly > 20% match rate → warning
  CACHE_TTL_SECONDS     = 60     SETEX TTL
"""
from __future__ import annotations

import json
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.brand import BrandPreviewResponse


CACHE_TTL_SECONDS = 60
SAMPLE_SIZE = 1000
TOO_BROAD_THRESHOLD = 0.20


def _cache_key(project_id: UUID | str, term: str, term_type: str) -> str:
    return f"brand:preview:{project_id}:{term}:{term_type}"


_PREVIEW_SQL = text(
    """
    WITH recent AS (
        SELECT search_tsv
        FROM events
        WHERE project_id = CAST(:project_id AS uuid)
        ORDER BY observed_at DESC
        LIMIT :sample_size
    )
    SELECT
        (SELECT COUNT(*) FROM recent) AS total,
        (SELECT COUNT(*) FROM recent WHERE search_tsv @@ plainto_tsquery('english', :term)) AS hits
    """
)


async def preview_term(
    *,
    session: AsyncSession,
    redis: Redis,
    project_id: UUID,
    term: str,
    term_type: str,
) -> BrandPreviewResponse:
    """Return the test-coverage preview for a candidate brand term.

    Cache-first: on hit, decode the cached JSON response and return it.
    On miss, run the FTS count SQL, compute `percent` (1-decimal round) and
    `warning`, cache via SETEX(TTL=60), and return.
    """
    key = _cache_key(project_id, term, term_type)
    cached = await redis.get(key)
    if cached:
        payload = json.loads(cached)
        return BrandPreviewResponse(**payload)

    row = (
        await session.execute(
            _PREVIEW_SQL,
            {
                "project_id": str(project_id),
                "sample_size": SAMPLE_SIZE,
                "term": term,
            },
        )
    ).mappings().one()

    total = int(row["total"] or 0)
    hits = int(row["hits"] or 0)

    if total > 0:
        ratio = hits / total
        percent = round(ratio * 100, 1)
        warning = "likely_too_broad" if ratio > TOO_BROAD_THRESHOLD else None
    else:
        percent = 0.0
        warning = None

    resp = BrandPreviewResponse(
        preview_matches=hits, percent=percent, warning=warning
    )
    await redis.setex(key, CACHE_TTL_SECONDS, resp.model_dump_json())
    return resp

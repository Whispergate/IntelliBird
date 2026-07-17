"""TAXII 2.1 outbound server router — TAXII-01..05.

All endpoints require a valid partner key via require_taxii_client Depends().
The JWT AuthMiddleware is bypassed for /taxii2 paths (see middleware/auth.py).

Endpoints:
  GET /taxii2/                                    — Discovery (TAXII-01)
  GET /taxii2/api/                                — API Root info (TAXII-01)
  GET /taxii2/api/collections/                    — Collections list (TAXII-02)
  GET /taxii2/api/collections/{collection_id}/    — Single collection (TAXII-02)
  GET /taxii2/api/collections/{collection_id}/objects/  — Objects (TAXII-02, TAXII-04, TAXII-05)

Content-Type on ALL responses: application/taxii+json;version=2.1 (TAXII-05)
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.middleware.taxii_auth import require_taxii_client
from app.models.events import Event
from app.models.taxii import TaxiiClient
from app.schemas.taxii import (
    ApiRootResource,
    CollectionResource,
    CollectionsResource,
    DiscoveryResource,
    TaxiiEnvelope,
)
from app.services.events_query import decode_cursor, encode_cursor
from app.services.taxii_bundle import build_tlp_predicate, event_to_stix_sdo

log = structlog.get_logger(__name__)

PAGE_CAP: int = 100  # TAXII-05: hard cap — no single response exceeds 100 objects

TAXII_CONTENT_TYPE = "application/taxii+json;version=2.1"

router = APIRouter(tags=["taxii"])


# ---------------------------------------------------------------------------
# Custom response class — forces correct Content-Type on all TAXII responses
# RESEARCH.md §Pitfall 1: FastAPI's JSONResponse hardcodes application/json
# ---------------------------------------------------------------------------

class _TaxiiResponse(Response):
    media_type = TAXII_CONTENT_TYPE

    def __init__(self, content=None, status_code: int = 200, **kwargs):
        body = json.dumps(content, default=str).encode("utf-8")
        super().__init__(
            content=body,
            status_code=status_code,
            media_type=self.media_type,
            **kwargs,
        )


def _taxii_base_url(request: Request) -> str:
    """Return base URL for TAXII discovery (api_roots must be full URLs per spec §4)."""
    if settings.TAXII_BASE_URL:
        return settings.TAXII_BASE_URL.rstrip("/")
    # Fallback: derive from request (works behind reverse proxy if X-Forwarded-Proto set)
    return str(request.base_url).rstrip("/")


# ---------------------------------------------------------------------------
# GET /taxii2/  — Discovery (TAXII 2.1 §4)
# ---------------------------------------------------------------------------

@router.get("/")
async def get_discovery(
    request: Request,
    client: TaxiiClient = Depends(require_taxii_client),
) -> Response:
    """TAXII 2.1 §4 Discovery Resource.

    Returns only the API root the authenticated partner can access.
    Unauthenticated requests raise 401 via require_taxii_client.
    Collection titles are NOT leaked here (only API root URL).
    """
    base = _taxii_base_url(request)
    resource = DiscoveryResource(
        title="IntelliBird TAXII 2.1",
        description="IntelliBird threat intelligence feed — partner pull",
        default=f"{base}/taxii2/api/",
        api_roots=[f"{base}/taxii2/api/"],
    )
    return _TaxiiResponse(content=resource.model_dump(exclude_none=True))


# ---------------------------------------------------------------------------
# GET /taxii2/api/  — API Root (TAXII 2.1 §5.1)
# ---------------------------------------------------------------------------

@router.get("/api/")
async def get_api_root(
    request: Request,
    client: TaxiiClient = Depends(require_taxii_client),
) -> Response:
    """TAXII 2.1 §5.1 API Root Resource."""
    resource = ApiRootResource(title="IntelliBird TAXII 2.1 API Root")
    return _TaxiiResponse(content=resource.model_dump(exclude_none=True))


# ---------------------------------------------------------------------------
# GET /taxii2/api/collections/  — Collections list (TAXII 2.1 §5.2)
# ---------------------------------------------------------------------------

@router.get("/api/collections/")
async def get_collections(
    client: TaxiiClient = Depends(require_taxii_client),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """TAXII 2.1 §5.2 — List collections the partner key has ACL for.

    Each taxii_clients row is bound to exactly one project_id.
    That project is the one collection this partner can see.
    Collection ID = project UUID string (RESEARCH.md §Pattern 7).
    """
    from app.models.projects import Project  # local import to avoid circular

    result = await session.execute(
        select(Project).where(Project.id == client.project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        collections = []
    else:
        collections = [
            CollectionResource(
                id=str(project.id),
                title=project.name,
                description=getattr(project, "description", None),
            )
        ]
    resource = CollectionsResource(collections=collections)
    return _TaxiiResponse(content=resource.model_dump())


# ---------------------------------------------------------------------------
# GET /taxii2/api/collections/{collection_id}/  — Single collection (TAXII 2.1 §5.2)
# ---------------------------------------------------------------------------

@router.get("/api/collections/{collection_id}/")
async def get_collection(
    collection_id: str,
    client: TaxiiClient = Depends(require_taxii_client),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """TAXII 2.1 §5.2 — Single collection resource."""
    # Validate that the partner has ACL for this collection
    if collection_id != str(client.project_id):
        raise HTTPException(status_code=403, detail="taxii_collection_forbidden")

    from app.models.projects import Project

    result = await session.execute(
        select(Project).where(Project.id == client.project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="taxii_collection_not_found")

    resource = CollectionResource(
        id=str(project.id),
        title=project.name,
        description=getattr(project, "description", None),
    )
    return _TaxiiResponse(content=resource.model_dump(exclude_none=True))


# ---------------------------------------------------------------------------
# GET /taxii2/api/collections/{collection_id}/objects/  — Objects (TAXII 2.1 §5.4)
# ---------------------------------------------------------------------------

@router.get("/api/collections/{collection_id}/objects/")
async def get_objects(
    collection_id: str,
    client: TaxiiClient = Depends(require_taxii_client),
    session: AsyncSession = Depends(get_session),
    added_after: str | None = Query(default=None, description="ISO 8601 datetime filter"),
    limit: int | None = Query(default=None, ge=1, le=PAGE_CAP),
    next_cursor: str | None = Query(default=None, alias="next"),
) -> Response:
    """TAXII 2.1 §5.4 — Paginated STIX objects for a collection.

    Enforces:
      - ACL: partner can only access their bound project_id (TAXII-04)
      - TLP: only events at or below client.tlp_max_level returned (TAXII-04)
      - Page cap: max 100 objects per response (TAXII-05)
      - Pagination: more/next cursor envelope (TAXII-05)
    """
    # ACL check — TAXII-04
    if collection_id != str(client.project_id):
        raise HTTPException(status_code=403, detail="taxii_collection_forbidden")

    effective_limit = min(limit or PAGE_CAP, PAGE_CAP)

    # Build base query scoped to this project + TLP predicate
    query = (
        select(Event)
        .where(Event.project_id == uuid.UUID(collection_id))
        .where(build_tlp_predicate(client.tlp_max_level))
        .order_by(Event.observed_at.asc(), Event.id.asc())
    )

    # added_after filter (TAXII 2.1 §5.3)
    if added_after:
        try:
            after_dt = datetime.fromisoformat(added_after.replace("Z", "+00:00"))
            query = query.where(Event.observed_at > after_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="taxii_invalid_added_after")

    # Cursor-based pagination (reuse events_query encode/decode_cursor)
    if next_cursor:
        try:
            cursor_dt, cursor_id = decode_cursor(next_cursor)
            query = query.where(
                (Event.observed_at > cursor_dt)
                | ((Event.observed_at == cursor_dt) & (Event.id > cursor_id))
            )
        except Exception:
            raise HTTPException(status_code=400, detail="taxii_invalid_cursor")

    # Fetch effective_limit + 1 to detect has_more
    query = query.limit(effective_limit + 1)
    result = await session.execute(query)
    rows = result.scalars().all()

    has_more = len(rows) > effective_limit
    page = list(rows[:effective_limit])

    # Convert events to STIX SDOs
    tlp_cache: dict = {}
    stix_objects = [event_to_stix_sdo(e, tlp_cache) for e in page]

    # Build cursor for next page
    new_next: str | None = None
    if has_more and page:
        new_next = encode_cursor(page[-1].observed_at, page[-1].id)

    envelope = TaxiiEnvelope(
        more=has_more,
        next=new_next,
        objects=stix_objects,
    )

    response = _TaxiiResponse(content=envelope.model_dump())
    # TAXII 2.1 §5.4: add X-TAXII-Date-Added-Last header when objects present
    if page:
        response.headers["X-TAXII-Date-Added-Last"] = page[-1].observed_at.isoformat()

    log.info(
        "taxii_objects_served",
        collection_id=collection_id,
        client_id=str(client.id),
        count=len(stix_objects),
        has_more=has_more,
    )
    return response

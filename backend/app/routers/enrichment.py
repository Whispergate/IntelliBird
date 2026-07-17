"""Enrichment provider settings + IOC enrichment read/trigger — ENRICH-01, ENRICH-04.

Endpoints:
  GET  /api/projects/{project_id}/enrichment-providers          Lead+
  PUT  /api/projects/{project_id}/enrichment-providers/{prov}   Lead+
  GET  /api/iocs/{ioc_id}/enrichments                           Project member (any role)
  POST /api/iocs/{ioc_id}/enrich                                Lead+
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.config import settings
from app.crypto import encrypt_credentials
from app.database import get_session
from app.models.enrichment import EnrichmentProvider, IOCEnrichment
from app.models.iocs import IOC
from app.models.projects import ProjectMembership, ProjectRole
from app.schemas.enrichment import (
    EnrichmentProviderRead,
    EnrichmentProviderWrite,
    IOCEnrichmentRead,
)
from app.security.jwt import PROJECT_ROLE_RANK
from app.services.enrichment.resolver import PROVIDER_CHOICES
from app.services.redis_client import get_redis

log = structlog.get_logger(__name__)

router = APIRouter(tags=["enrichment"])

ALL_PROVIDERS = ["vt", "abuseipdb", "greynoise", "otx", "shodan", "urlhaus"]

# Lead rank from the PROJECT_ROLE_RANK table — Lead = 3.
_LEAD_RANK: int = PROJECT_ROLE_RANK[ProjectRole.Lead.value]


async def _require_project_lead_plus(
    project_id: uuid.UUID,
    request: Request,
    session: AsyncSession,
) -> None:
    """Check Lead+ role membership for project. Raise 403 if insufficient."""
    user = getattr(request.state, "user", None)
    if user is None:
        return  # AUTH_ENABLED=false

    # Admin bypasses per-project check
    if getattr(user, "role", None) == "Admin":
        return

    # Fast path via JWT pm claim (dict[str, int] of project_id_str → role_rank)
    pm: dict[str, int] = getattr(user, "project_memberships", None) or {}
    cached_rank = pm.get(str(project_id))
    if cached_rank is not None:
        if cached_rank >= _LEAD_RANK:
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient_role")

    # DB fallback (handles pm_truncated / missing pm claim)
    membership = (
        await session.execute(
            select(ProjectMembership).where(
                ProjectMembership.project_id == project_id,
                ProjectMembership.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not_a_member")
    rank = PROJECT_ROLE_RANK.get(membership.role, 0)
    if rank < _LEAD_RANK:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient_role")


async def _require_project_member(
    project_id: uuid.UUID,
    request: Request,
    session: AsyncSession,
) -> None:
    """Check that the caller is ANY member of the project (any role). Raise 403 if not."""
    user = getattr(request.state, "user", None)
    if user is None:
        return  # AUTH_ENABLED=false

    # Admin bypasses per-project check
    if getattr(user, "role", None) == "Admin":
        return

    # Fast path via JWT pm claim
    pm: dict[str, int] = getattr(user, "project_memberships", None) or {}
    if str(project_id) in pm:
        return

    # DB fallback
    membership = (
        await session.execute(
            select(ProjectMembership).where(
                ProjectMembership.project_id == project_id,
                ProjectMembership.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not_a_member")


async def _get_breaker_open_until(redis, provider: str, project_scope: str) -> datetime | None:
    """Return breaker expiry time, or None if breaker is not open."""
    key = f"enrich:cb:{provider}:{project_scope}"
    ttl = await redis.ttl(key)
    if ttl <= 0:
        return None
    return datetime.fromtimestamp(
        datetime.now(timezone.utc).timestamp() + ttl, tz=timezone.utc
    )


@router.get(
    "/projects/{project_id}/enrichment-providers",
    response_model=list[EnrichmentProviderRead],
)
async def list_enrichment_providers(
    project_id: uuid.UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[EnrichmentProviderRead]:
    """List all 6 provider slots with breaker state — Lead+ required."""
    await _require_project_lead_plus(project_id, request, session)
    redis = await get_redis()

    # Fetch all per-project rows
    rows = (
        await session.execute(
            select(EnrichmentProvider).where(EnrichmentProvider.project_id == project_id)
        )
    ).scalars().all()
    row_map = {r.provider: r for r in rows}

    result = []
    for prov in ALL_PROVIDERS:
        row = row_map.get(prov)
        project_scope = str(project_id)
        breaker_open_until = await _get_breaker_open_until(redis, prov, project_scope)
        if row is None:
            # Default disabled slot — no DB row yet for this provider
            result.append(EnrichmentProviderRead(
                id=uuid.uuid4(),  # ephemeral — no DB row
                project_id=project_id,
                provider=prov,
                enabled=False,
                api_key_masked=None,
                daily_request_cap=None,
                breaker_open_until=breaker_open_until,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            ))
        else:
            masked = "••••••••" if row.credentials_enc else None
            result.append(EnrichmentProviderRead(
                id=row.id,
                project_id=row.project_id,
                provider=row.provider,
                enabled=row.enabled,
                api_key_masked=masked,
                daily_request_cap=row.daily_request_cap,
                breaker_open_until=breaker_open_until,
                created_at=row.created_at,
                updated_at=row.updated_at,
            ))
    return result


@router.put(
    "/projects/{project_id}/enrichment-providers/{provider}",
    response_model=EnrichmentProviderRead,
)
async def upsert_enrichment_provider(
    project_id: uuid.UUID,
    provider: str,
    payload: EnrichmentProviderWrite,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EnrichmentProviderRead:
    """Create or update provider credentials — encrypts api_key before storage. Lead+ required."""
    if provider not in PROVIDER_CHOICES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown provider: {provider}. Valid: {sorted(PROVIDER_CHOICES)}",
        )
    await _require_project_lead_plus(project_id, request, session)

    # Encrypt API key if provided
    credentials_enc: str | None = None
    if payload.api_key:
        credentials_enc = encrypt_credentials(settings.SECRET_KEY, {"api_key": payload.api_key})

    # Upsert via PostgreSQL INSERT … ON CONFLICT DO UPDATE
    from sqlalchemy.dialects.postgresql import insert as _pg_insert  # noqa: PLC0415

    now = datetime.now(timezone.utc)

    insert_values: dict = {
        "project_id": project_id,
        "provider": provider,
        "enabled": payload.enabled,
        "daily_request_cap": payload.daily_request_cap,
        "updated_at": now,
    }
    if credentials_enc is not None:
        insert_values["credentials_enc"] = credentials_enc
        insert_values["credentials_key_version"] = 1

    # Only update mutable fields on conflict (exclude PK-like columns)
    set_values = {k: v for k, v in insert_values.items() if k not in ("project_id", "provider")}

    await session.execute(
        _pg_insert(EnrichmentProvider.__table__)
        .values(**insert_values)
        .on_conflict_do_update(
            constraint="uq_enrichment_providers_project_provider",
            set_=set_values,
        )
    )
    await session.commit()

    # Refresh from DB to return the canonical row
    row = (
        await session.execute(
            select(EnrichmentProvider).where(
                EnrichmentProvider.project_id == project_id,
                EnrichmentProvider.provider == provider,
            )
        )
    ).scalar_one()
    redis = await get_redis()
    breaker_open_until = await _get_breaker_open_until(redis, provider, str(project_id))
    masked = "••••••••" if row.credentials_enc else None
    return EnrichmentProviderRead(
        id=row.id,
        project_id=row.project_id,
        provider=row.provider,
        enabled=row.enabled,
        api_key_masked=masked,
        daily_request_cap=row.daily_request_cap,
        breaker_open_until=breaker_open_until,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/iocs/{ioc_id}/enrichments", response_model=list[IOCEnrichmentRead])
async def get_ioc_enrichments(
    ioc_id: uuid.UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[IOCEnrichmentRead]:
    """List all ioc_enrichments rows for this IOC.

    ACL: any project member (Analyst, Observer, Lead, Admin) can read enrichments.
    Only Lead+ can trigger or configure — enforced on POST and PUT endpoints.
    Returns 404 if IOC not found, 403 if caller has no project membership.
    """
    ioc = await session.get(IOC, ioc_id)
    if ioc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ioc_not_found")

    # ACL: any project member can read (Analyst and Observer included).
    await _require_project_member(ioc.project_id, request, session)

    enrichments = (
        await session.execute(
            select(IOCEnrichment).where(IOCEnrichment.ioc_id == ioc_id)
        )
    ).scalars().all()
    return [IOCEnrichmentRead.model_validate(e) for e in enrichments]


@router.post("/iocs/{ioc_id}/enrich", status_code=status.HTTP_202_ACCEPTED)
async def trigger_ioc_enrich(
    ioc_id: uuid.UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    refresh: bool = Query(default=False, description="Bypass 24h cache and re-fetch from providers"),
) -> dict:
    """Enqueue enrichment for an IOC. Lead+ required.

    ?refresh=true sets Redis key `enrich:force_refresh:{ioc_id}` (TTL 300s)
    that `_async_enrich` (Plan 23-04) reads to bypass cache before provider calls.
    """
    ioc = await session.get(IOC, ioc_id)
    if ioc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ioc_not_found")
    await _require_project_lead_plus(ioc.project_id, request, session)

    if refresh:
        # Short-lived flag — _async_enrich checks redis.exists(f"enrich:force_refresh:{ioc_id}")
        # before calling get_cached_result, and deletes the key after a successful commit.
        redis = await get_redis()
        await redis.set(f"enrich:force_refresh:{ioc_id}", "1", ex=300)

    from app.workers.iocs import enrich_ioc  # noqa: PLC0415

    enrich_ioc.send(str(ioc_id))
    log.info("enrich_ioc_queued", ioc_id=str(ioc_id), refresh=refresh)
    return {"queued": True, "ioc_id": str(ioc_id)}

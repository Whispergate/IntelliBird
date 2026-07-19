"""Admin TAXII partner key management - TAXII-03.

Endpoints:
  GET    /api/admin/taxii-clients/       - list all partner keys (no raw key exposed)
  POST   /api/admin/taxii-clients/       - issue new partner key (raw key returned ONCE)
  DELETE /api/admin/taxii-clients/{id}   - revoke partner key (sets revoked=True)

Admin-only (require_admin). Raw API keys are never stored; only SHA-256 hex digest.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.middleware.auth import require_admin
from app.models.taxii import TaxiiClient
from app.schemas.taxii import TaxiiClientCreate, TaxiiClientCreated, TaxiiClientRead
from app.security.jwt import AuthUser

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin/taxii-clients", tags=["admin-taxii"])


def _generate_raw_key() -> str:
    """Generate a URL-safe random API key (256 bits of entropy)."""
    return secrets.token_urlsafe(32)


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@router.get("/", response_model=list[TaxiiClientRead])
async def list_taxii_clients(
    _: AuthUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[TaxiiClientRead]:
    """List all TAXII partner keys. Raw API keys are NEVER returned."""
    result = await session.execute(
        select(TaxiiClient).order_by(TaxiiClient.created_at.desc())
    )
    rows = result.scalars().all()
    return [TaxiiClientRead.model_validate(r) for r in rows]


@router.post("/", response_model=TaxiiClientCreated, status_code=201)
async def create_taxii_client(
    body: TaxiiClientCreate,
    _: AuthUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> TaxiiClientCreated:
    """Issue a new TAXII partner key.

    The raw API key is returned ONCE in the response - it is not stored.
    The caller must copy and securely distribute it to the partner.
    """
    from app.services.taxii_bundle import TLP_LEVELS
    if body.tlp_max_level not in TLP_LEVELS:
        raise HTTPException(
            status_code=400,
            detail=f"invalid_tlp_level: must be one of {list(TLP_LEVELS.keys())}",
        )

    raw_key = _generate_raw_key()
    key_hash = _hash_key(raw_key)

    client = TaxiiClient(
        label=body.label,
        api_key_hash=key_hash,
        project_id=body.project_id,
        tlp_max_level=body.tlp_max_level,
        rate_limit_rpm=body.rate_limit_rpm,
        revoked=False,
    )
    session.add(client)
    await session.commit()
    await session.refresh(client)

    log.info(
        "taxii_client_created",
        client_id=str(client.id),
        label=client.label,
        project_id=str(client.project_id),
        tlp_max_level=client.tlp_max_level,
    )

    return TaxiiClientCreated(
        id=client.id,
        label=client.label,
        project_id=client.project_id,
        tlp_max_level=client.tlp_max_level,
        rate_limit_rpm=client.rate_limit_rpm,
        revoked=client.revoked,
        revoked_at=client.revoked_at,
        created_at=client.created_at,
        raw_api_key=raw_key,  # shown ONCE - not stored
    )


@router.delete("/{client_id}", status_code=204, response_model=None, response_class=Response)
async def revoke_taxii_client(
    client_id: uuid.UUID,
    _: AuthUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Revoke a TAXII partner key.

    Sets revoked=True and revoked_at=now(). The row is retained for audit purposes.
    Subsequent requests using this key will receive HTTP 401 immediately (no cache lag).
    """
    result = await session.execute(
        select(TaxiiClient).where(TaxiiClient.id == client_id)
    )
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="taxii_client_not_found")
    if client.revoked:
        raise HTTPException(status_code=409, detail="taxii_client_already_revoked")

    client.revoked = True
    client.revoked_at = datetime.now(timezone.utc)
    await session.commit()

    log.info(
        "taxii_client_revoked",
        client_id=str(client.id),
        label=client.label,
    )

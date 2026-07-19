"""POST /api/admin/rekey-credentials - INFRA-02.

Re-encrypt every sources.credentials_enc blob from the OLD SECRET_KEY
(settings.REKEY_FROM_SECRET) to the CURRENT SECRET_KEY (settings.SECRET_KEY).

Design:
- Setup-token gated via X-Setup-Token header compared against settings.SETUP_TOKEN.
  If SETUP_TOKEN env is unset, the endpoint is effectively disabled (403). This keeps
  the pre-auth endpoint safe for operator-only usage during bring-up.
- Atomic: all rows succeed or all roll back. Any decrypt failure under the old key
  returns 500 with the failing source_ids so the operator can investigate before retry.
- Re-encryption bumps credentials_key_version by 1 (simple monotonic counter; repeat
  rekeys are safe).
- Rows with credentials_enc = NULL are skipped (e.g. canary row before first startup,
  or sources that never had creds).
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crypto import decrypt_credentials, encrypt_credentials
from app.database import get_session
from app.models.enrichment import EnrichmentProvider
from app.models.sources import Source

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


class RekeyResponse(BaseModel):
    rekeyed: int
    skipped: int
    # DARK-04: count of sources.session_enc blobs re-encrypted.
    sources_session_enc_swept: int = 0


class RekeyErrorDetail(BaseModel):
    error: str
    source_ids: list[str]


def _require_setup_token(
    x_setup_token: str | None = Header(default=None, alias="X-Setup-Token"),
) -> None:
    if not settings.SETUP_TOKEN or x_setup_token != settings.SETUP_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing setup token",
        )


@router.post(
    "/rekey-credentials",
    response_model=RekeyResponse,
    responses={
        400: {"description": "REKEY_FROM_SECRET env var not set"},
        403: {"description": "Invalid or missing X-Setup-Token"},
        500: {
            "model": RekeyErrorDetail,
            "description": "One or more rows failed to decrypt under REKEY_FROM_SECRET",
        },
    },
)
async def rekey_credentials(
    _: None = Depends(_require_setup_token),
    session: AsyncSession = Depends(get_session),
) -> RekeyResponse:
    if not settings.REKEY_FROM_SECRET:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="REKEY_FROM_SECRET env var not set",
        )

    rows = (await session.execute(select(Source))).scalars().all()
    failed_ids: list[str] = []
    updates: list[tuple[Source, str]] = []

    skipped_already_current: list[str] = []

    for row in rows:
        if row.credentials_enc is None:
            continue
        # Idempotency: if a row is already encrypted under the CURRENT SECRET_KEY,
        # skip it. Happens for rows freshly seeded by the startup canary path
        # between rotations, or when rekey is re-run after a partial success.
        try:
            decrypt_credentials(settings.SECRET_KEY, row.credentials_enc)
            skipped_already_current.append(str(row.id))
            continue
        except Exception:
            pass
        try:
            creds = decrypt_credentials(settings.REKEY_FROM_SECRET, row.credentials_enc)
        except Exception:
            failed_ids.append(str(row.id))
            continue
        new_blob = encrypt_credentials(settings.SECRET_KEY, creds)
        updates.append((row, new_blob))

    # --- EnrichmentProvider sweep ---
    ep_rows = (
        await session.execute(
            select(EnrichmentProvider).where(EnrichmentProvider.credentials_enc.isnot(None))
        )
    ).scalars().all()

    ep_updates: list[tuple[EnrichmentProvider, str]] = []
    for ep_row in ep_rows:
        # Idempotency: skip rows already encrypted under the current key
        try:
            decrypt_credentials(settings.SECRET_KEY, ep_row.credentials_enc)  # type: ignore[arg-type]
            skipped_already_current.append(f"ep:{ep_row.id}")
            continue
        except Exception:
            pass
        try:
            creds = decrypt_credentials(settings.REKEY_FROM_SECRET, ep_row.credentials_enc)  # type: ignore[arg-type]
        except Exception:
            failed_ids.append(f"ep:{ep_row.id}")
            continue
        new_blob = encrypt_credentials(settings.SECRET_KEY, creds)
        ep_updates.append((ep_row, new_blob))

    if failed_ids:
        await session.rollback()
        log.critical(
            "rekey_credentials_failed",
            failed_source_ids=failed_ids,
            failed_count=len(failed_ids),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "decrypt_failed", "source_ids": failed_ids},
        )

    for row, new_blob in updates:
        row.credentials_enc = new_blob
        row.credentials_key_version = (row.credentials_key_version or 1) + 1

    for ep_row, new_blob in ep_updates:
        ep_row.credentials_enc = new_blob
        ep_row.credentials_key_version = (ep_row.credentials_key_version or 1) + 1

    # --- sources.session_enc sweep (DARK-04 - Telethon session strings) ---
    sources_session_swept = 0
    session_rows = (
        await session.execute(
            select(Source).where(Source.session_enc.isnot(None))
        )
    ).scalars().all()

    for src_row in session_rows:
        # Idempotency: skip rows already encrypted under the current key.
        try:
            decrypt_credentials(settings.SECRET_KEY, src_row.session_enc)  # type: ignore[arg-type]
            skipped_already_current.append(f"session:{src_row.id}")
            continue
        except Exception:  # noqa: BLE001
            pass
        try:
            creds = decrypt_credentials(settings.REKEY_FROM_SECRET, src_row.session_enc)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001
            failed_ids.append(f"session:{src_row.id}")
            continue
        src_row.session_enc = encrypt_credentials(settings.SECRET_KEY, creds)
        sources_session_swept += 1

    if failed_ids:
        await session.rollback()
        log.critical(
            "rekey_sources_session_enc_failed",
            failed_source_ids=failed_ids,
            failed_count=len(failed_ids),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "decrypt_failed", "source_ids": failed_ids},
        )

    log.info("rekey_sources_session_enc_swept count=%d", sources_session_swept)

    await session.commit()
    total_rekeyed = len(updates) + len(ep_updates)
    total_skipped = (len(rows) - len(updates)) + (len(ep_rows) - len(ep_updates))
    log.info(
        "rekey_credentials_ok",
        rekeyed=total_rekeyed,
        skipped=total_skipped,
        sources_session_enc_swept=sources_session_swept,
    )
    return RekeyResponse(
        rekeyed=total_rekeyed,
        skipped=total_skipped,
        sources_session_enc_swept=sources_session_swept,
    )

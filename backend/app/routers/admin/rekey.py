"""POST /api/admin/rekey-credentials — INFRA-02.

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
from app.models.sources import Source

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


class RekeyResponse(BaseModel):
    rekeyed: int
    skipped: int


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

    for row in rows:
        if row.credentials_enc is None:
            continue
        try:
            creds = decrypt_credentials(settings.REKEY_FROM_SECRET, row.credentials_enc)
        except Exception:
            failed_ids.append(str(row.id))
            continue
        new_blob = encrypt_credentials(settings.SECRET_KEY, creds)
        updates.append((row, new_blob))

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

    await session.commit()
    log.info(
        "rekey_credentials_ok",
        rekeyed=len(updates),
        skipped=len(rows) - len(updates),
    )
    return RekeyResponse(rekeyed=len(updates), skipped=len(rows) - len(updates))

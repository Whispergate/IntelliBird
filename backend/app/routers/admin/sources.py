"""Admin Source Registry CRUD — SRC-01, SRC-02, SRC-04, SRC-05, STO-01, STO-02.

AUTH-02 (Phase 9): every endpoint guarded by Depends(require_admin).
Test Connection endpoint (SRC-03) added by Plan 03.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Literal

from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crypto import encrypt_credentials
from app.database import get_session
from app.middleware.auth import require_admin
from app.models.sources import Source
from app.security.jwt import AuthUser
from app.services.source_events import publish_sources_changed
from app.services.source_probes import _probe_nvd, _probe_rss, _probe_taxii

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/sources", tags=["admin"])

FeedType = Literal["rss", "taxii", "nvd"]
ArchivePolicy = Literal["keep", "drop", "move-to-cold"]
_SILENT_THRESHOLD_DEFAULT = 5


def _effective_status(last_status: str | None, silent_failure_count: int) -> str | None:
    threshold = int(getattr(settings, "INGEST_SILENT_FAILURE_THRESHOLD", _SILENT_THRESHOLD_DEFAULT))
    if last_status == "ok" and silent_failure_count >= threshold:
        return "silent"
    return last_status


class SourceResponse(BaseModel):
    id: uuid.UUID
    name: str
    feed_type: FeedType
    url: str
    # credentials_enc DELIBERATELY ABSENT — SRC-04
    poll_interval_sec: int
    hot_retention_days: int
    archive_policy: ArchivePolicy
    enabled: bool
    last_polled_at: datetime | None
    last_status: str | None
    consecutive_failures: int
    silent_failure_count: int
    effective_status: str | None
    created_at: datetime

    @classmethod
    def from_orm_row(cls, src: Source) -> "SourceResponse":
        return cls(
            id=src.id,
            name=src.name,
            feed_type=src.feed_type,  # type: ignore[arg-type]
            url=src.url,
            poll_interval_sec=src.poll_interval_sec,
            hot_retention_days=src.hot_retention_days,
            archive_policy=src.archive_policy,  # type: ignore[arg-type]
            enabled=src.enabled,
            last_polled_at=src.last_polled_at,
            last_status=src.last_status,
            consecutive_failures=src.consecutive_failures,
            silent_failure_count=src.silent_failure_count,
            effective_status=_effective_status(src.last_status, src.silent_failure_count),
            created_at=src.created_at,
        )


class SourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    feed_type: FeedType
    url: str = Field(min_length=1)
    credentials: dict | None = None
    poll_interval_sec: int = Field(ge=60)
    hot_retention_days: int = Field(ge=1, le=3650)
    archive_policy: ArchivePolicy = "drop"
    enabled: bool = True


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    # feed_type DELIBERATELY ABSENT — locks it after creation
    url: str | None = None
    credentials: dict | None = None  # None/absent → keep; non-empty → re-encrypt
    poll_interval_sec: int | None = Field(default=None, ge=60)
    hot_retention_days: int | None = Field(default=None, ge=1, le=3650)
    archive_policy: ArchivePolicy | None = None
    enabled: bool | None = None


class EventCountResponse(BaseModel):
    count: int


class TestConnectionRequest(BaseModel):
    feed_type: FeedType
    url: str = Field(min_length=1)
    credentials: dict | None = None


class TestConnectionResponse(BaseModel):
    ok: bool
    latency_ms: int
    item_count_sampled: int
    error_detail: str | None


@router.post("/test-connection", response_model=TestConnectionResponse)
def test_connection(
    payload: TestConnectionRequest,
    _admin: AuthUser = Depends(require_admin),
) -> TestConnectionResponse:
    """Synchronous Test Connection probe. Returns 200 regardless of probe
 outcome — the ok flag in the body signals success/failure. UI uses
 this as informational only.
"""
    if payload.feed_type == "rss":
        ok, latency, count, err = _probe_rss(payload.url)
    elif payload.feed_type == "nvd":
        api_key = None
        if payload.credentials and payload.credentials.get("type") == "apiKey":
            api_key = payload.credentials.get("key")
        ok, latency, count, err = _probe_nvd(api_key)
    elif payload.feed_type == "taxii":
        ok, latency, count, err = _probe_taxii(payload.url, payload.credentials)
    else:  # pragma: no cover — Literal type keeps this unreachable
        raise HTTPException(status_code=422, detail=f"unsupported feed_type {payload.feed_type}")

    logger.info(
        "source_test_probe feed_type=%s ok=%s latency_ms=%d error=%s",
        payload.feed_type, ok, latency, err,
    )
    return TestConnectionResponse(
        ok=ok,
        latency_ms=latency,
        item_count_sampled=count,
        error_detail=err,
    )


@router.get("", response_model=list[SourceResponse])
async def list_sources(
    db: AsyncSession = Depends(get_session),
    _admin: AuthUser = Depends(require_admin),
) -> list[SourceResponse]:
    result = await db.execute(
        select(Source).order_by(Source.last_polled_at.desc().nullslast())
    )
    return [SourceResponse.from_orm_row(s) for s in result.scalars().all()]


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    _admin: AuthUser = Depends(require_admin),
) -> SourceResponse:
    src = await db.get(Source, source_id)
    if src is None:
        raise HTTPException(status_code=404, detail="source not found")
    return SourceResponse.from_orm_row(src)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=SourceResponse)
async def create_source(
    payload: SourceCreate,
    db: AsyncSession = Depends(get_session),
    _admin: AuthUser = Depends(require_admin),
) -> SourceResponse:
    credentials_enc = None
    if payload.credentials:
        credentials_enc = encrypt_credentials(settings.SECRET_KEY, payload.credentials)
    src = Source(
        id=uuid.uuid4(),
        name=payload.name,
        feed_type=payload.feed_type,
        url=payload.url,
        credentials_enc=credentials_enc,
        poll_interval_sec=payload.poll_interval_sec,
        hot_retention_days=payload.hot_retention_days,
        archive_policy=payload.archive_policy,
        enabled=payload.enabled,
        created_at=datetime.now(timezone.utc),
    )
    db.add(src)
    await db.commit()
    await db.refresh(src)
    publish_sources_changed("reload")
    logger.info("source_created source_id=%s feed_type=%s name=%s",
                src.id, src.feed_type, src.name)
    return SourceResponse.from_orm_row(src)


@router.patch("/{source_id}", response_model=SourceResponse)
async def update_source(
    source_id: uuid.UUID,
    payload: SourceUpdate,
    db: AsyncSession = Depends(get_session),
    _admin: AuthUser = Depends(require_admin),
) -> SourceResponse:
    src = await db.get(Source, source_id)
    if src is None:
        raise HTTPException(status_code=404, detail="source not found")

    data = payload.model_dump(exclude_unset=True)
    data.pop("feed_type", None)  # belt-and-braces — SourceUpdate has no feed_type field

    if "credentials" in data:
        creds = data.pop("credentials")
        if creds:
            src.credentials_enc = encrypt_credentials(settings.SECRET_KEY, creds)
        # else: keep existing credentials_enc

    for key, val in data.items():
        setattr(src, key, val)

    await db.commit()
    await db.refresh(src)
    publish_sources_changed("reload")
    logger.info("source_updated source_id=%s fields=%s", src.id, list(data.keys()))
    return SourceResponse.from_orm_row(src)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_source(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    _admin: AuthUser = Depends(require_admin),
) -> Response:
    src = await db.get(Source, source_id)
    if src is None:
        raise HTTPException(status_code=404, detail="source not found")

    feed_type = src.feed_type
    await db.delete(src)
    await db.commit()
    publish_sources_changed(
        "reload",
        deleted=[{"feed_type": feed_type, "source_id": str(source_id)}],
    )
    logger.info("source_deleted source_id=%s feed_type=%s", source_id, feed_type)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{source_id}/event-count", response_model=EventCountResponse)
async def event_count(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    _admin: AuthUser = Depends(require_admin),
) -> EventCountResponse:
    result = await db.execute(
        text("SELECT COUNT(*) FROM events WHERE source_id = :sid"),
        {"sid": str(source_id)},
    )
    n = int(result.scalar_one())
    return EventCountResponse(count=n)

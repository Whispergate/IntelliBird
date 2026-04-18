"""Admin Webhook Registry CRUD — HOOK-01, HOOK-02, HOOK-09.

Unauthenticated in M1 (loopback + auth-deferred). Mirrors sources.py.
Test-send endpoint registered BEFORE /{id} routes (FastAPI path order — Pitfall 5).
auth_enc encrypted on save; NEVER appears in any response body (SRC-04 parallel).
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crypto import encrypt_credentials
from app.database import get_session
from app.models.webhooks import Webhook, WebhookPresetBinding
from app.schemas.webhooks import (
    TestSendRequest,
    TestSendResponse,
    WebhookCreate,
    WebhookResponse,
    WebhookUpdate,
)
from app.services.webhook_payloads import build_payload_for_type

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/admin/webhooks", tags=["webhooks"])

_BATCHING_ALLOWED = {0, 60, 300, 900, 1800}
_TEST_SEND_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=30.0, pool=None)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _auth_to_dict(auth) -> dict | None:
    """Convert AuthSpec discriminated union → plain dict for encryption."""
    if auth is None:
        return None
    return auth.model_dump()


def _make_dummy_event() -> dict:
    """Synthesise a test event for the test-send endpoint (D-32)."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": f"urn:uuid:test-{uuid.uuid4()}",
        "observed_at": now,
        "fetched_at": now,
        "source_id": None,
        "source_name": "IntelliBird",
        "source_type": None,
        "stix_id": None,
        "stix_type": "indicator",
        "title": "IntelliBird test alert",
        "description": "This is a test message from IntelliBird. Your webhook is configured correctly.",
        "tlp": "clear",
        "tags": [],
        "attack_techniques": [],
        "archived": False,
        "visibility": "shared",
        "geo_lat": None,
        "geo_lon": None,
    }


def _build_auth_headers(auth) -> dict[str, str]:
    """Build Authorization / custom headers from plaintext AuthSpec for test-send.

    No DB round-trip — auth is supplied in the request body for test-send.
    """
    if auth is None:
        return {}
    if auth.type == "bearer":
        return {"Authorization": f"Bearer {auth.token}"}
    if auth.type == "basic":
        import base64
        encoded = base64.b64encode(
            f"{auth.username}:{auth.password}".encode()
        ).decode()
        return {"Authorization": f"Basic {encoded}"}
    if auth.type == "header":
        return {auth.name: auth.value}
    return {}


# ---------------------------------------------------------------------------
# test-send — MUST be registered BEFORE /{webhook_id} routes (Pitfall 5)
# FastAPI matches routes in declaration order; /test-send must come first or
# FastAPI will try to cast "test-send" as a UUID and return 422.
# ---------------------------------------------------------------------------


@router.post("/test-send", response_model=TestSendResponse)
def test_webhook_send(payload: TestSendRequest) -> TestSendResponse:
    """Non-blocking test send. D-31: always HTTP 200; ok flag in body signals result."""
    dummy_event = _make_dummy_event()
    result_payload = build_payload_for_type(
        payload.destination_type,
        [dummy_event],
        preset_name="test-preset",
        dashboard_url=settings.DASHBOARD_URL,
        preset_query_params={},
    )
    headers = {"Content-Type": "application/json; charset=utf-8"}
    headers.update(_build_auth_headers(payload.auth))

    start = time.monotonic()
    ok = False
    err: str | None = None
    try:
        with httpx.Client(timeout=_TEST_SEND_TIMEOUT) as client:
            resp = client.post(payload.url, json=result_payload, headers=headers)
            ok = resp.status_code < 300
            err = None if ok else f"HTTP {resp.status_code}"
    except httpx.TimeoutException:
        err = "timeout"
    except Exception as exc:  # noqa: BLE001
        err = str(exc)[:200]

    latency_ms = int((time.monotonic() - start) * 1000)
    log.info(
        "webhook_test_send",
        destination_type=payload.destination_type,
        ok=ok,
        latency_ms=latency_ms,
        error=err,
    )
    return TestSendResponse(ok=ok, latency_ms=latency_ms, error_detail=err)


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------


async def _load_bindings(db: AsyncSession, webhook_id: uuid.UUID) -> list[str]:
    rows = await db.execute(
        select(WebhookPresetBinding.preset_name).where(
            WebhookPresetBinding.webhook_id == webhook_id
        )
    )
    return [r[0] for r in rows.all()]


async def _hydrate(db: AsyncSession, wh: Webhook) -> WebhookResponse:
    """Build a WebhookResponse with bound_preset_names populated via join."""
    bound = await _load_bindings(db, wh.id)
    return WebhookResponse(
        id=wh.id,
        name=wh.name,
        destination_type=wh.destination_type,  # type: ignore[arg-type]
        url=wh.url,
        batching_window_sec=wh.batching_window_sec,
        enabled=wh.enabled,
        last_dispatch_at=wh.last_dispatch_at,
        last_delivery_at=wh.last_delivery_at,
        last_delivery_status=wh.last_delivery_status,
        consecutive_failures=wh.consecutive_failures,
        bound_preset_names=bound,
        created_at=wh.created_at,
        updated_at=wh.updated_at,
    )


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[WebhookResponse])
async def list_webhooks(
    db: AsyncSession = Depends(get_session),
) -> list[WebhookResponse]:
    rows = await db.execute(select(Webhook).order_by(Webhook.created_at.desc()))
    return [await _hydrate(db, wh) for wh in rows.scalars().all()]


@router.post("", status_code=201, response_model=WebhookResponse)
async def create_webhook(
    payload: WebhookCreate,
    db: AsyncSession = Depends(get_session),
) -> WebhookResponse:
    if payload.batching_window_sec not in _BATCHING_ALLOWED:
        raise HTTPException(
            status_code=422,
            detail=f"batching_window_sec must be one of {sorted(_BATCHING_ALLOWED)}",
        )

    auth_enc = None
    if payload.auth is not None:
        auth_dict = _auth_to_dict(payload.auth)
        auth_enc = encrypt_credentials(settings.SECRET_KEY, auth_dict)

    wh = Webhook(
        id=uuid.uuid4(),
        name=payload.name,
        destination_type=payload.destination_type,
        url=payload.url,
        auth_enc=auth_enc,
        batching_window_sec=payload.batching_window_sec,
        enabled=payload.enabled,
        consecutive_failures=0,
    )
    db.add(wh)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail=f"webhook name {payload.name!r} already exists"
        )

    for preset_name in payload.bound_preset_names:
        db.add(WebhookPresetBinding(webhook_id=wh.id, preset_name=preset_name))
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=422,
            detail=f"one or more preset names do not exist: {exc.orig}",
        )

    await db.refresh(wh)
    log.info("webhook_registered", webhook_id=str(wh.id), destination_type=wh.destination_type)
    return await _hydrate(db, wh)


@router.get("/{webhook_id}", response_model=WebhookResponse)
async def get_webhook(
    webhook_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> WebhookResponse:
    wh = await db.get(Webhook, webhook_id)
    if wh is None:
        raise HTTPException(status_code=404, detail="webhook not found")
    return await _hydrate(db, wh)


@router.patch("/{webhook_id}", response_model=WebhookResponse)
async def update_webhook(
    webhook_id: uuid.UUID,
    payload: WebhookUpdate,
    db: AsyncSession = Depends(get_session),
) -> WebhookResponse:
    wh = await db.get(Webhook, webhook_id)
    if wh is None:
        raise HTTPException(status_code=404, detail="webhook not found")

    data = payload.model_dump(exclude_unset=True)

    # auth handling: clear_auth=True → NULL; auth provided → re-encrypt; absent → keep
    if data.pop("clear_auth", False):
        wh.auth_enc = None
    if "auth" in data:
        auth = data.pop("auth")
        if auth is not None:
            wh.auth_enc = encrypt_credentials(settings.SECRET_KEY, auth)

    # Validate batching_window_sec if provided
    if "batching_window_sec" in data:
        bw = data["batching_window_sec"]
        if bw not in _BATCHING_ALLOWED:
            raise HTTPException(
                status_code=422,
                detail=f"batching_window_sec must be one of {sorted(_BATCHING_ALLOWED)}",
            )

    # Replace-all semantics for bound_preset_names if explicitly provided
    if "bound_preset_names" in data:
        names = data.pop("bound_preset_names") or []
        await db.execute(
            delete(WebhookPresetBinding).where(
                WebhookPresetBinding.webhook_id == webhook_id
            )
        )
        for n in names:
            db.add(WebhookPresetBinding(webhook_id=webhook_id, preset_name=n))

    # Apply remaining scalar fields
    for key, val in data.items():
        setattr(wh, key, val)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=422, detail=str(exc.orig))

    await db.refresh(wh)
    log.info("webhook_updated", webhook_id=str(wh.id))
    return await _hydrate(db, wh)


@router.delete("/{webhook_id}", status_code=204, response_class=Response)
async def delete_webhook(
    webhook_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> Response:
    wh = await db.get(Webhook, webhook_id)
    if wh is None:
        raise HTTPException(status_code=404, detail="webhook not found")
    await db.delete(wh)
    await db.commit()
    log.info("webhook_deleted", webhook_id=str(webhook_id))
    return Response(status_code=204)


@router.put("/{webhook_id}/reset-cursor", response_model=WebhookResponse)
async def reset_cursor(
    webhook_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> WebhookResponse:
    """D-12: reset last_dispatch_at to NULL. Next tick uses 24h lookback (D-13)."""
    wh = await db.get(Webhook, webhook_id)
    if wh is None:
        raise HTTPException(status_code=404, detail="webhook not found")
    wh.last_dispatch_at = None
    await db.commit()
    await db.refresh(wh)
    log.info("webhook_cursor_reset", webhook_id=str(webhook_id))
    return await _hydrate(db, wh)

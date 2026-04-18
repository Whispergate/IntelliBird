"""Webhook dispatcher service — core tick logic.

Fired every 60s by APScheduler via webhook_dispatch_tick actor.
D-04..D-28: per-webhook iteration -> build_events_query match ->
Redis wh-batch:{id} accumulation -> dispatch via payload builder -> retry.

Pitfall 2: broad try/except around run_dispatch_tick body so Dramatiq
max_retries=0 actually means "do not retry" — without the wrap, an
uncaught exception still re-queues.

Pitfall 5: tolerate Redis key eviction between tick and drain —
always check LLEN > 0 before drain; missing key is not an error.

Pitfall 7: role=None for all build_events_query calls — dispatcher is
an admin operation, not dashboard-scoped. All visibility classes delivered.
"""
from __future__ import annotations

import base64
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import redis as redis_lib
import structlog
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session as SyncSession

from app.config import settings
from app.crypto import decrypt_credentials
from app.models.events import Event
from app.models.filter_presets import FilterPreset
from app.models.markings import TlpMarking
from app.models.sources import Source
from app.models.tags import AttackTechniqueTag
from app.models.webhooks import Webhook, WebhookPresetBinding
from app.services.events_query import EventsQueryParams, build_events_query
from app.services.webhook_payloads import build_payload_for_type

log = structlog.get_logger(__name__)

# ---- constants --------------------------------------------------------------
RETRY_DELAYS: list[int] = [30, 60, 120]  # D-26 — 3 attempts, 2 inter-sleep gaps
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 20.0
TOTAL_TIMEOUT = 30.0
MAX_DIGEST_EVENTS = 50  # D-10
AUTO_DISABLE_FAILURES = 5  # D-27
NULL_CURSOR_LOOKBACK_HOURS = 24  # D-13


def _redis_ttl_for(window_sec: int) -> int:
    """TTL for Redis batch keys: 2x the window, minimum 120s."""
    return max(window_sec * 2, 120)


# ---- dispatch entrypoint ---------------------------------------------------
def run_dispatch_tick() -> None:
    """Called by webhook_dispatch_tick Dramatiq actor every 60s.

    Pitfall 2: catch everything; max_retries=0 + broad except = no re-queue.
    """
    try:
        _run_tick_inner()
    except Exception as e:  # noqa: BLE001
        log.warning("webhook_dispatch_tick_error", error=str(e))


def _run_tick_inner() -> None:
    sync_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    sync_url = sync_url.replace("+asyncpg", "")
    engine = create_engine(sync_url, future=True)
    r = redis_lib.from_url(settings.REDIS_URL)
    log.info("webhook_dispatch_tick_started")

    try:
        with SyncSession(engine) as session:
            webhooks = (
                session.execute(
                    select(Webhook).where(Webhook.enabled == True)  # noqa: E712
                )
                .scalars()
                .all()
            )

            for wh in webhooks:
                try:
                    _process_webhook(wh, session, r)
                except Exception as e:  # noqa: BLE001
                    log.warning(
                        "webhook_process_error",
                        webhook_id=str(wh.id),
                        error=str(e),
                    )
                    session.rollback()
    finally:
        engine.dispose()


# ---- per-webhook processing -------------------------------------------------
def _process_webhook(
    webhook: Webhook,
    session: SyncSession,
    r: redis_lib.Redis,
) -> None:
    # Load bound presets
    bindings = (
        session.execute(
            select(FilterPreset)
            .join(
                WebhookPresetBinding,
                WebhookPresetBinding.preset_name == FilterPreset.name,
            )
            .where(WebhookPresetBinding.webhook_id == webhook.id)
        )
        .scalars()
        .all()
    )

    if not bindings:
        log.debug("webhook_no_presets", webhook_id=str(webhook.id))
        return

    # Collect matching events across all bound presets, dedup by event.id (D-05)
    # all_matched: event_id str -> (event dict, first-matching FilterPreset)
    all_matched: dict[str, tuple[dict, FilterPreset]] = {}
    for preset in bindings:
        events = _fetch_matching_events(
            session,
            preset.query_params,
            webhook.last_dispatch_at,
        )
        for ev in events:
            eid = str(ev["id"])
            if eid not in all_matched:
                all_matched[eid] = (ev, preset)

    if not all_matched:
        return

    # Serialise events for Redis
    serialised = [
        json.dumps(
            {
                **ev,
                "observed_at": _iso(ev.get("observed_at")),
                "fetched_at": _iso(ev.get("fetched_at")),
            }
        )
        for ev, _ in all_matched.values()
    ]

    # Primary preset for payload header (first preset that matched)
    primary_preset = next(iter(all_matched.values()))[1]

    batch_key = f"wh-batch:{webhook.id}"
    ts_key = f"wh-batch-ts:{webhook.id}"
    ttl = _redis_ttl_for(webhook.batching_window_sec)
    now = datetime.now(timezone.utc)

    existing = int(r.llen(batch_key) or 0)

    if existing == 0:
        # D-09: first event of window → immediate dispatch
        r.rpush(batch_key, *serialised)
        r.set(ts_key, now.isoformat())
        r.expire(batch_key, ttl)
        r.expire(ts_key, ttl)
        _drain_and_dispatch(webhook, r, session, primary_preset)
    else:
        r.rpush(batch_key, *serialised)
        r.expire(batch_key, ttl)
        window_start_raw = r.get(ts_key)
        if window_start_raw:
            window_start_str = (
                window_start_raw.decode()
                if isinstance(window_start_raw, bytes)
                else window_start_raw
            )
            window_start = datetime.fromisoformat(window_start_str)
            if (now - window_start).total_seconds() >= webhook.batching_window_sec:
                _drain_and_dispatch(webhook, r, session, primary_preset)


# ---- event matching --------------------------------------------------------
def _fetch_matching_events(
    session: SyncSession,
    preset_query_params: dict,
    last_dispatch_at: datetime | None,
) -> list[dict]:
    """Reuse build_events_query with observed_from cursor.

    D-13: NULL cursor -> scan last 24h only.
    Pitfall 7: role=None (admin operation, no dashboard-scope gating).
    """
    if last_dispatch_at is None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=NULL_CURSOR_LOOKBACK_HOURS)
    else:
        cutoff = last_dispatch_at

    params = EventsQueryParams(
        source=preset_query_params.get("source"),
        source_type=preset_query_params.get("source_type"),
        observed_from=cutoff,
        observed_to=preset_query_params.get("observed_to"),
        tlp=preset_query_params.get("tlp"),
        attack_technique=preset_query_params.get("attack_technique"),
        tag=preset_query_params.get("tag"),
        include_archived=preset_query_params.get("include_archived", False),
        has_geo=preset_query_params.get("has_geo", False),
        tag_mode=preset_query_params.get("tag_mode", "all"),
    )
    stmt = build_events_query(params, role=None)  # Pitfall 7 — role=None always
    stmt = stmt.limit(MAX_DIGEST_EVENTS)

    rows = session.execute(stmt).scalars().all()
    return [_hydrate_event_dict(row, session) for row in rows]


def _hydrate_event_dict(event: Event, session: SyncSession) -> dict:
    """Build an EventItem-shaped dict from an ORM Event + joins (sync)."""
    source_name = None
    source_type = None
    if event.source_id is not None:
        row = session.execute(
            select(Source.name, Source.feed_type).where(Source.id == event.source_id)
        ).one_or_none()
        if row:
            source_name, source_type = row[0], row[1]

    tlp_name = None
    if event.tlp_marking_id is not None:
        row = session.execute(
            select(TlpMarking.name).where(TlpMarking.id == event.tlp_marking_id)
        ).one_or_none()
        if row:
            tlp_name = row[0]

    techs = session.execute(
        select(AttackTechniqueTag.technique_id).where(
            AttackTechniqueTag.event_id == event.id
        )
    ).all()

    return {
        "id": event.id,
        "observed_at": event.observed_at,
        "fetched_at": event.fetched_at,
        "source_id": event.source_id,
        "source_name": source_name,
        "source_type": source_type,
        "stix_id": event.stix_id,
        "stix_type": event.stix_type,
        "title": event.title,
        "description": event.description,
        "tlp": tlp_name,
        "tags": (event.tags or []),
        "attack_techniques": [r[0] for r in techs],
        "archived": event.archived,
        "visibility": event.visibility,
        "geo_lat": event.geo_lat,
        "geo_lon": event.geo_lon,
    }


def _iso(v: Any) -> Any:
    """Convert datetime to ISO string for JSON serialisation."""
    return v.isoformat() if hasattr(v, "isoformat") else v


# ---- drain + dispatch -------------------------------------------------------
def _drain_and_dispatch(
    webhook: Webhook,
    r: redis_lib.Redis,
    session: SyncSession,
    primary_preset: FilterPreset,
) -> None:
    """Drain Redis list, build payload, POST with retry, update cursor."""
    batch_key = f"wh-batch:{webhook.id}"
    ts_key = f"wh-batch-ts:{webhook.id}"

    raw_items = r.lrange(batch_key, 0, MAX_DIGEST_EVENTS - 1) or []
    if not raw_items:
        # Pitfall 5: eviction tolerance — missing key is not an error
        log.debug("webhook_batch_empty_or_evicted", webhook_id=str(webhook.id))
        return

    events = [
        json.loads(x.decode() if isinstance(x, bytes) else x) for x in raw_items
    ]
    max_observed = _max_observed_at(events)

    payload = build_payload_for_type(
        webhook.destination_type,
        events,
        primary_preset.name,
        settings.DASHBOARD_URL,
        primary_preset.query_params,
    )
    headers = {"Content-Type": "application/json; charset=utf-8"}
    headers.update(_build_auth_headers(webhook.auth_enc))

    ok, err = _post_with_retry(webhook.url, payload, headers)
    _record_delivery_result(session, webhook, ok, err)

    if ok:
        # D-06: advance cursor ONLY on success
        _advance_cursor(session, webhook, max_observed)
        r.delete(batch_key, ts_key)
        log.info(
            "webhook_delivery_ok",
            webhook_id=str(webhook.id),
            destination_type=webhook.destination_type,
            event_count=len(events),
        )
    else:
        # D-06: cursor NOT advanced on failure — next tick re-attempts same window
        log.warning(
            "webhook_delivery_failed",
            webhook_id=str(webhook.id),
            destination_type=webhook.destination_type,
            event_count=len(events),
            error=err,
        )

    session.commit()


# ---- HTTP retry -------------------------------------------------------------
def _post_with_retry(
    url: str,
    payload: dict,
    headers: dict[str, str],
) -> tuple[bool, str | None]:
    """3 attempts with sleeps of 30s then 60s between them (no sleep after last).

    D-26: RETRY_DELAYS = [30, 60, 120]; 3 attempts means 2 inter-attempt sleeps.
    Returns (success, error_detail).
    """
    last_err: str | None = None
    attempts = len(RETRY_DELAYS)  # 3

    for i, delay in enumerate(RETRY_DELAYS):
        try:
            with httpx.Client(
                timeout=httpx.Timeout(
                    connect=CONNECT_TIMEOUT,
                    read=READ_TIMEOUT,
                    write=TOTAL_TIMEOUT,
                    pool=None,
                )
            ) as client:
                resp = client.post(url, json=payload, headers=headers)
                if resp.status_code < 300:
                    return True, None
                last_err = f"http_{resp.status_code}"
        except httpx.TimeoutException:
            last_err = "timeout"
        except Exception as e:  # noqa: BLE001 — network errors
            last_err = f"network_error: {e}"[:200]

        if i < attempts - 1:
            time.sleep(delay)

    return False, last_err


# ---- auth header builder ----------------------------------------------------
def _build_auth_headers(auth_enc: str | None) -> dict[str, str]:
    """Decrypt auth_enc and return appropriate auth header dict (D-24)."""
    if not auth_enc:
        return {}
    try:
        creds = decrypt_credentials(settings.SECRET_KEY, auth_enc)
    except Exception:  # noqa: BLE001
        return {}

    atype = creds.get("type")
    if atype == "bearer":
        return {"Authorization": f"Bearer {creds['token']}"}
    if atype == "basic":
        encoded = base64.b64encode(
            f"{creds['username']}:{creds['password']}".encode()
        ).decode()
        return {"Authorization": f"Basic {encoded}"}
    if atype == "header":
        return {creds["name"]: creds["value"]}
    return {}


# ---- cursor helpers ---------------------------------------------------------
def _max_observed_at(events: list[dict]) -> datetime:
    """Return max observed_at across events, defaulting to now."""
    tmax: datetime | None = None
    for ev in events:
        v = ev.get("observed_at")
        if isinstance(v, str):
            try:
                v = datetime.fromisoformat(v)
            except ValueError:
                continue
        if v is None:
            continue
        if not v.tzinfo:
            v = v.replace(tzinfo=timezone.utc)
        if tmax is None or v > tmax:
            tmax = v
    return tmax or datetime.now(timezone.utc)


def _advance_cursor(
    session: SyncSession, webhook: Webhook, ts: datetime
) -> None:
    """UPDATE webhooks SET last_dispatch_at=:ts WHERE id=:id (D-06)."""
    session.execute(
        text(
            "UPDATE webhooks SET last_dispatch_at = :ts, updated_at = now() "
            "WHERE id = :id"
        ),
        {"ts": ts, "id": str(webhook.id)},
    )


def _record_delivery_result(
    session: SyncSession,
    webhook: Webhook,
    ok: bool,
    err: str | None,
) -> None:
    """Update delivery status columns; auto-disable at 5 consecutive failures (D-27)."""
    if ok:
        session.execute(
            text(
                "UPDATE webhooks SET "
                "  last_delivery_at = now(), "
                "  last_delivery_status = 'ok', "
                "  consecutive_failures = 0, "
                "  updated_at = now() "
                "WHERE id = :id"
            ),
            {"id": str(webhook.id)},
        )
        return

    new_failure_count = webhook.consecutive_failures + 1
    if err == "timeout":
        status_token = "timeout"
    elif (err or "").startswith("network_error"):
        status_token = "network_error"
    else:
        status_token = "http_error"

    should_disable = new_failure_count >= AUTO_DISABLE_FAILURES  # D-27
    session.execute(
        text(
            "UPDATE webhooks SET "
            "  last_delivery_at = now(), "
            "  last_delivery_status = :st, "
            "  consecutive_failures = :cf, "
            "  enabled = CASE WHEN :disable THEN false ELSE enabled END, "
            "  updated_at = now() "
            "WHERE id = :id"
        ),
        {
            "st": status_token,
            "cf": new_failure_count,
            "disable": should_disable,
            "id": str(webhook.id)},
    )
    if should_disable:
        log.warning(
            "webhook_auto_disabled",
            webhook_id=str(webhook.id),
            consecutive_failures=new_failure_count,
        )

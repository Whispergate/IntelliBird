"""Webhook dispatcher service — core tick logic.

Fired every 60s by APScheduler via webhook_dispatch_tick actor.
..: per-webhook iteration -> build_events_query match ->
Redis wh-batch:{id} accumulation -> dispatch via payload builder -> retry.

: broad try/except around run_dispatch_tick body so Dramatiq
max_retries=0 actually means "do not retry" — without the wrap, an
uncaught exception still re-queues.

: tolerate Redis key eviction between tick and drain —
always check LLEN > 0 before drain; missing key is not an error.

: dashboard_roles=None for all build_events_query calls — dispatcher is
an admin operation, not dashboard-scoped. All visibility classes delivered.

Burst suppression (SCR-05 — Roadmap pitfall H-1):
  HIGH-tier (S+A) events are subject to a per-project rolling-window cap of
  BURST_HIGH_CAP fires per BURST_WINDOW_SEC. Excess HIGH-tier events are:
    - tagged burst_cluster=true on the event row (still visible in /events list)
    - skipped from webhook fan-out (not serialised into the Redis batch)
  Non-HIGH-tier events (B/C/D or unscored) bypass suppression entirely.
  See: 15-CONTEXT.md §"Burst suppression", app.services.scoring.burst
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from typing import Any
from urllib.parse import urlparse

import aiosmtplib
import httpx
import redis as redis_lib
import structlog
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session as SyncSession

from app.config import settings
from app.crypto import decrypt_credentials
from app.models.events import Event
from app.services.scoring.burst import is_burst_suppressed, record_high_tier_dispatch
from app.services.scoring.tiers import classify_tier
from app.models.filter_presets import FilterPreset
from app.models.markings import TlpMarking
from app.models.projects import ProjectScopeRow, ProjectSource
from app.models.sources import Source
from app.models.tags import AttackTechniqueTag
from app.models.webhooks import Webhook, WebhookPresetBinding
from app.services.events_query import EventsQueryParams, build_events_query
from app.services.project_scope import build_scope_predicate
from app.services.webhook_payloads import build_payload_for_type

log = structlog.get_logger(__name__)

# ---- constants --------------------------------------------------------------
RETRY_DELAYS: list[int] = [30, 60, 120]  # — 3 attempts, 2 inter-sleep gaps
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 20.0
TOTAL_TIMEOUT = 30.0
MAX_DIGEST_EVENTS = 50  #
AUTO_DISABLE_FAILURES = 5  #
NULL_CURSOR_LOOKBACK_HOURS = 24  #


def _redis_ttl_for(window_sec: int) -> int:
    """TTL for Redis batch keys: 2x the window, minimum 120s."""
    return max(window_sec * 2, 120)


# ---- dispatch entrypoint ---------------------------------------------------
def run_dispatch_tick() -> None:
    """Called by webhook_dispatch_tick Dramatiq actor every 60s.

: catch everything; max_retries=0 + broad except = no re-queue.
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

    # Collect matching events across all bound presets, dedup by event.id
    # all_matched: event_id str -> (event dict, first-matching FilterPreset)
    # pre-compute scope predicate + bound sources once per webhook
    # (webhook.project_id is NOT NULL post-migration 009 — every webhook pins
    # to exactly one project).
    scope_predicate, bound_sources = _fetch_project_scope_sync(
        session, webhook.project_id,
    )
    all_matched: dict[str, tuple[dict, FilterPreset]] = {}
    for preset in bindings:
        events = _fetch_matching_events(
            session,
            preset.query_params,
            webhook.last_dispatch_at,
            project_id=webhook.project_id,
            scope_predicate=scope_predicate,
            bound_sources=bound_sources,
        )
        for ev in events:
            eid = str(ev["id"])
            if eid not in all_matched:
                all_matched[eid] = (ev, preset)

    if not all_matched:
        return

    # --- Burst suppression (SCR-05, Roadmap H-1) -----------------
    # For HIGH-tier events (S or A), check the per-project rolling window cap.
    # Suppressed events are tagged burst_cluster=true in the DB and excluded from
    # the fan-out batch. Non-HIGH-tier and unscored events pass through unchanged.
    #
    # record_high_tier_dispatch is called INLINE as each HIGH-tier event is
    # accepted into the surviving set — this ensures the 6th+ events see a
    # count ≥ BURST_HIGH_CAP and are correctly suppressed, even though HTTP
    # delivery hasn't happened yet. The window counter is thus "reserved" for
    # events that will be dispatched. This is intentional: it prevents two
    # concurrent ticks for the same project from both seeing count=0 and both
    # dispatching 5 events (race condition mitigation per RESEARCH §Pattern 4).
    project_id_str = str(webhook.project_id)
    surviving: dict[str, tuple[dict, FilterPreset]] = {}
    _high_tier_dispatch_count = 0
    for eid, (ev, preset) in all_matched.items():
        score = ev.get("score")
        if score is not None and classify_tier(float(score)) in {"S", "A"}:
            # HIGH-tier event: consult sliding window
            if is_burst_suppressed(r, project_id_str):
                # Cap reached — tag the event row and skip fan-out
                _tag_burst_cluster(session, uuid.UUID(eid))
                log.info(
                    "webhook_burst_suppressed",
                    webhook_id=str(webhook.id),
                    event_id=eid,
                    score=score,
                    project_id=project_id_str,
                )
                continue  # advance iteration (cursor advances with the rest)
            # Cap not yet reached — reserve a slot in the window and include
            # this event in the fan-out batch.
            record_high_tier_dispatch(r, project_id_str)
            _high_tier_dispatch_count += 1
            surviving[eid] = (ev, preset)
        else:
            # Non-HIGH tier or unscored: bypass suppression
            surviving[eid] = (ev, preset)

    if not surviving:
        return

    # Replace all_matched with the suppression-filtered view
    all_matched = surviving
    # -------------------------------------------------------------------------

    # Serialise events for Redis.
    # Strip internal dispatcher fields (score, _project_id) that are not part
    # of the outbound webhook payload schema. They were added to ev for the
    # burst-suppression check above and must not appear in the fanout payload.
    _INTERNAL_KEYS = frozenset({"score", "_project_id"})
    serialised = [
        json.dumps(
            {
                **{k: v for k, v in ev.items() if k not in _INTERNAL_KEYS},
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
        #: first event of window → immediate dispatch
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
def _fetch_project_scope_sync(
    session: SyncSession, project_id: uuid.UUID,
) -> tuple[Any, list[uuid.UUID] | None]:
    """Sync equivalent of project_scope.fetch_scope_rows_intel + fetch_bound_sources.

    The dispatcher runs against a sync Session (APScheduler + Dramatiq worker);
    project_scope's async helpers would need an event loop. Inline sync SELECT
    returns (scope_predicate, bound_sources) ready to pass into build_events_query.
    legacy webhooks point at LEGACY_PROJECT_ID sentinel — with zero scope
    rows the predicate is sa.text('false'), so those dispatches correctly match
    zero events going forward (M-6 enforcement).
    """
    rows = session.execute(
        select(ProjectScopeRow)
        .where(ProjectScopeRow.project_id == project_id)
        .where(ProjectScopeRow.intel_scope == True)  # noqa: E712
    ).scalars().all()
    scope_predicate = build_scope_predicate(list(rows))

    bound = session.execute(
        select(ProjectSource.source_id).where(
            ProjectSource.project_id == project_id
        )
    ).scalars().all()
    bound_sources = list(bound) if bound else None
    return scope_predicate, bound_sources


def _fetch_matching_events(
    session: SyncSession,
    preset_query_params: dict,
    last_dispatch_at: datetime | None,
    project_id: uuid.UUID,
    scope_predicate: Any = None,
    bound_sources: list[uuid.UUID] | None = None,
) -> list[dict]:
    """Reuse build_events_query with observed_from cursor.

: NULL cursor -> scan last 24h only.
: dashboard_roles=None (admin operation, no dashboard-scope gating).
project_id + scope_predicate + bound_sources threaded through so
per-webhook dispatch only surfaces events inside the webhook's project and
scope. project_id is mandatory — post-migration-009 webhooks.project_id is
NOT NULL.
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
    stmt = build_events_query(
        params, dashboard_roles=None,  # no role filter (admin operation)
        project_id=project_id,
        scope_predicate=scope_predicate,
        bound_sources=bound_sources,
    )
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
        "id": str(event.id),
        "observed_at": event.observed_at,
        "fetched_at": event.fetched_at,
        "source_id": str(event.source_id) if event.source_id is not None else None,
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
        # SCR-05: score included so burst suppression can classify tier
        # in _process_webhook before fan-out. None for pre-migration rows.
        "score": float(event.score) if event.score is not None else None,
        # _project_id used for burst_cluster tagging — private field, stripped before
        # Redis serialisation (not forwarded in webhook payload).
        "_project_id": str(event.project_id),
    }


def _iso(v: Any) -> Any:
    """Convert datetime to ISO string for JSON serialisation."""
    return v.isoformat() if hasattr(v, "isoformat") else v


def _tag_burst_cluster(session: SyncSession, event_id: uuid.UUID) -> None:
    """Append 'burst_cluster' to an event's tags array (SCR-05).

    Uses PostgreSQL array_append so the update is idempotent-safe even if
    burst_cluster is already present. The tags column is TEXT[] so duplicates
    are not prevented at the DB level — callers should only invoke this once
    per suppression decision. Mirrors the raw-SQL UPDATE approach from
    tags.py: SQLAlchemy ARRAY assignment has dialect quirks with asyncpg/sync.

    Does NOT commit — caller (webhook tick) is responsible for session.commit().
    """
    session.execute(
        text(
            "UPDATE events "
            "SET tags = array_append(COALESCE(tags, ARRAY[]::text[]), 'burst_cluster') "
            "WHERE id = :eid"
        ),
        {"eid": str(event_id)},
    )


# ---- email helpers ----------------------------------------------------------
def _build_email_body(events: list[dict]) -> str:
    """Build a plain-text digest body from a list of event dicts.

    One line per event: "{tier} | {title} | {observed_at}".
    Prefixed with an IntelliBird header.
    """
    header = f"IntelliBird Alert Digest — {len(events)} event(s)\n{'=' * 50}\n"
    lines = [
        f"{ev.get('tier', '?')} | {ev.get('title', '(no title)')} | {ev.get('observed_at', '')}"
        for ev in events
    ]
    return header + "\n".join(lines)


def _dispatch_email(
    webhook: Webhook,
    events: list[dict],
) -> tuple[bool, str | None]:
    """Send an email digest via SMTP using aiosmtplib.

    URL format: smtp://host:port — port defaults to 587 if absent.
    auth_enc must contain: username, password, from_addr, to_addr, use_starttls (bool).

    use_starttls=True  → STARTTLS (port 587): start_tls=True,  use_tls=False
    use_starttls=False → implicit TLS (port 465): start_tls=False, use_tls=True

    Returns (True, None) on success; (False, str(e)[:200]) on any exception.
    """
    try:
        parsed = urlparse(webhook.url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 587

        creds = decrypt_credentials(settings.SECRET_KEY, webhook.auth_enc)
        username = creds.get("username")
        password = creds.get("password")
        from_addr = creds.get("from_addr", username or "noreply@localhost")
        to_addr = creds.get("to_addr", "")
        use_starttls: bool = bool(creds.get("use_starttls", True))

        body = _build_email_body(events)
        subject = f"[IntelliBird] {len(events)} alert(s) — {webhook.name}"
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_addr

        async def _send() -> None:
            await aiosmtplib.send(
                msg,
                hostname=host,
                port=port,
                username=username,
                password=password,
                use_tls=not use_starttls,   # True = implicit TLS (port 465)
                start_tls=use_starttls,       # True = STARTTLS (port 587)
            )

        asyncio.run(_send())
        return True, None

    except Exception as e:  # noqa: BLE001
        return False, str(e)[:200]


# ---- drain + dispatch -------------------------------------------------------
def _drain_and_dispatch(
    webhook: Webhook,
    r: redis_lib.Redis,
    session: SyncSession,
    primary_preset: FilterPreset,
) -> None:
    """Drain Redis list, build payload, POST with retry, update cursor.

    SCR-05: Burst suppression is enforced upstream in _process_webhook
    before events reach the Redis batch. By this point, the batch already contains
    only non-suppressed events (≤ BURST_HIGH_CAP per high-tier project window).
    Window recording (record_high_tier_dispatch) was also already done inline.
    """
    batch_key = f"wh-batch:{webhook.id}"
    ts_key = f"wh-batch-ts:{webhook.id}"

    raw_items = r.lrange(batch_key, 0, MAX_DIGEST_EVENTS - 1) or []
    if not raw_items:
        #: eviction tolerance — missing key is not an error
        log.debug("webhook_batch_empty_or_evicted", webhook_id=str(webhook.id))
        return

    events = [
        json.loads(x.decode() if isinstance(x, bytes) else x) for x in raw_items
    ]
    max_observed = _max_observed_at(events)

    # Email branch: SMTP dispatch — must return early before HTTP payload build.
    # Burst-suppression and auto-disable operate upstream; both apply equally to
    # email because _record_delivery_result + consecutive_failures are called here.
    if webhook.destination_type == "email":
        ok, err = _dispatch_email(webhook, events)
        _record_delivery_result(session, webhook, ok, err)
        if ok:
            _advance_cursor(session, webhook, max_observed)
            r.delete(batch_key, ts_key)
            log.info(
                "webhook_delivery_ok",
                webhook_id=str(webhook.id),
                destination_type=webhook.destination_type,
                event_count=len(events),
            )
        else:
            log.warning(
                "webhook_delivery_failed",
                webhook_id=str(webhook.id),
                destination_type=webhook.destination_type,
                event_count=len(events),
                error=err,
            )
        session.commit()
        return

    payload = build_payload_for_type(
        webhook.destination_type,
        events,
        primary_preset.name,
        settings.DASHBOARD_URL,
        primary_preset.query_params,
    )
    # PagerDuty: routing_key must be in the JSON body, not an Authorization header.
    # Inject from auth_enc after the generic payload build.
    if webhook.destination_type == "pagerduty" and webhook.auth_enc:
        try:
            _pd_creds = decrypt_credentials(settings.SECRET_KEY, webhook.auth_enc)
            payload["routing_key"] = _pd_creds.get("routing_key", "")
        except Exception:  # noqa: BLE001
            pass  # sentinel remains; PD will 400, triggers auto-disable path
    headers = {"Content-Type": "application/json; charset=utf-8"}
    headers.update(_build_auth_headers(webhook.auth_enc))

    ok, err = _post_with_retry(webhook.url, payload, headers)
    _record_delivery_result(session, webhook, ok, err)

    if ok:
        #: advance cursor ONLY on success
        _advance_cursor(session, webhook, max_observed)
        r.delete(batch_key, ts_key)
        log.info(
            "webhook_delivery_ok",
            webhook_id=str(webhook.id),
            destination_type=webhook.destination_type,
            event_count=len(events),
        )
    else:
        #: cursor NOT advanced on failure — next tick re-attempts same window
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

: RETRY_DELAYS = [30, 60, 120]; 3 attempts means 2 inter-attempt sleeps.
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
    """Decrypt auth_enc and return appropriate auth header dict."""
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
    if atype == "geniekey":
        return {"Authorization": f"GenieKey {creds['api_key']}"}
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
    """UPDATE webhooks SET last_dispatch_at=:ts WHERE id=:id."""
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
    """Update delivery status columns; auto-disable at 5 consecutive failures."""
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

    should_disable = new_failure_count >= AUTO_DISABLE_FAILURES  #
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

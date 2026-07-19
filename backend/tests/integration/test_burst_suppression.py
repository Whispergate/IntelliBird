"""Integration test: burst suppression - SCR-05 / Roadmap H-1.

Verifies that when 50 CVE events all scoring 95.0 (S-tier) are seeded and the
webhook dispatcher tick runs, at most BURST_HIGH_CAP (5) webhook POSTs fire and
the remaining 45 events are tagged ``burst_cluster=true`` in the DB.

Design decisions:
  - Uses a SYNC SQLAlchemy session (mirrors webhook_dispatcher.py's own pattern)
    to seed data and invoke _process_webhook directly. Avoids nested event-loop
    issues from mixing asyncio with the sync dispatcher.
  - Mocks httpx.Client.post via unittest.mock.patch so no real HTTP egress.
  - Flushes Redis burst key at setup and teardown.
  - Seeds a filter_preset + webhook + webhook_preset_binding so the dispatcher
    has something to dispatch.
  - Seeds a project_scope_row (keyword='cve') so build_scope_predicate doesn't
    short-circuit to ``false`` (scope-intersection contract).
"""
from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import redis as redis_lib
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as SyncSession

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCORE_S_TIER = 95.0          # classifies as "S" (≥ 90)
NUM_EVENTS = 50               # total HIGH-tier events seeded
EXPECTED_DISPATCHED = 5       # == BURST_HIGH_CAP
EXPECTED_SUPPRESSED = NUM_EVENTS - EXPECTED_DISPATCHED


# ---------------------------------------------------------------------------
# Sync session fixture
# ---------------------------------------------------------------------------

def _make_sync_session(pg_url: str) -> SyncSession:
    """Return a new sync SQLAlchemy session using the testcontainer pg_url."""
    sync_url = (
        pg_url.replace("postgresql+asyncpg://", "postgresql://")
              .replace("+asyncpg", "")
    )
    engine = create_engine(sync_url, future=True)
    return SyncSession(engine), engine


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _seed_project(session: SyncSession) -> uuid.UUID:
    pid = uuid.uuid4()
    session.execute(
        text(
            "INSERT INTO projects (id, name, engagement_type, created_by, archived) "
            "VALUES (:id, :name, 'internal', 'burst-test', false)"
        ),
        {"id": pid, "name": f"BurstProject-{pid}"},
    )
    return pid


def _seed_scope_row(session: SyncSession, project_id: uuid.UUID) -> None:
    """Insert a permissive keyword scope row so build_scope_predicate matches."""
    session.execute(
        text(
            "INSERT INTO project_scope_rows "
            "(id, project_id, scope_type, value, intel_scope, active_test_scope, exclude) "
            "VALUES (gen_random_uuid(), :pid, 'keyword', 'cve', true, false, false)"
        ),
        {"pid": project_id},
    )


def _seed_events_high_tier(
    session: SyncSession, project_id: uuid.UUID, n: int
) -> list[uuid.UUID]:
    """Seed n events with score=SCORE_S_TIER and scored_at=now."""
    event_ids: list[uuid.UUID] = []
    base = datetime.now(timezone.utc) - timedelta(hours=1)
    for i in range(n):
        eid = uuid.uuid4()
        event_ids.append(eid)
        observed_at = base + timedelta(seconds=i)
        content_hash = hashlib.sha256(f"burst:{project_id}:{i}".encode()).hexdigest()
        session.execute(
            text(
                "INSERT INTO events "
                "(id, stix_type, project_id, observed_at, title, content_hash, "
                " visibility, score, scored_at, score_version) "
                "VALUES (:id, 'observed-data', :pid, :obs, :title, :ch, "
                "        'shared', :score, now(), 1)"
            ),
            {
                "id": eid,
                "pid": project_id,
                "obs": observed_at,
                "title": f"CVE-burst-{i}",
                "ch": content_hash,
                "score": SCORE_S_TIER,
            },
        )
    return event_ids


def _seed_filter_preset(session: SyncSession, project_id: uuid.UUID) -> str:
    """Insert a filter_preset that matches all events (empty params = wide open)."""
    name = f"burst-preset-{project_id}"
    # Use cast(... as jsonb) to avoid SQLAlchemy misinterpreting :qp::jsonb
    # (the :: cast syntax collides with named-parameter :qp parsing).
    # filter_presets schema: id, name, project_id, query_params, created_at, updated_at
    session.execute(
        text(
            "INSERT INTO filter_presets (name, project_id, query_params) "
            "VALUES (:name, :pid, cast(:qp as jsonb))"
        ),
        {"name": name, "pid": project_id, "qp": "{}"},
    )
    return name


def _seed_webhook_and_binding(
    session: SyncSession,
    project_id: uuid.UUID,
    preset_name: str,
) -> uuid.UUID:
    """Insert a webhook + binding, return webhook id."""
    wid = uuid.uuid4()
    session.execute(
        text(
            "INSERT INTO webhooks "
            "(id, name, project_id, destination_type, url, batching_window_sec, enabled) "
            "VALUES (:id, :name, :pid, 'generic', 'http://mock-webhook.internal', 60, true)"
        ),
        {"id": wid, "name": f"wh-burst-{wid}", "pid": project_id},
    )
    session.execute(
        text(
            "INSERT INTO webhook_preset_bindings (webhook_id, preset_name) "
            "VALUES (:wid, :pn)"
        ),
        {"wid": wid, "pn": preset_name},
    )
    return wid


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

def test_burst_suppression_caps_high_tier_webhooks(
    pg_url: str, redis_url: str, _migrations_applied: None
) -> None:
    """50 S-tier events → at most 5 webhook POSTs; remaining 45 tagged burst_cluster.

    Flow:
      1. Seed project + scope + 50 S-tier events + filter_preset + webhook.
      2. Flush the Redis burst key for this project.
      3. Patch httpx.Client.post to return HTTP 200 (mock delivery).
      4. Invoke _process_webhook with a sync SQLAlchemy session + sync Redis.
      5. Assert: POST count == EXPECTED_DISPATCHED (5).
      6. Assert: burst_cluster tag count in DB == EXPECTED_SUPPRESSED (45).
      7. Assert: Redis ZCARD burst:project:{pid}:high == EXPECTED_DISPATCHED.
    """
    # --- Build sync session --------------------------------------------------
    session, engine = _make_sync_session(pg_url)

    # --- Patch settings before importing dispatcher  -------------------------
    from app.config import settings
    settings.DATABASE_URL = pg_url  # type: ignore[assignment]
    settings.REDIS_URL = redis_url  # type: ignore[assignment]

    from app.services.webhook_dispatcher import _process_webhook
    from app.services.scoring.burst import BURST_HIGH_CAP, _key as burst_key

    # --- Seed data -----------------------------------------------------------
    with session:
        project_id = _seed_project(session)
        _seed_scope_row(session, project_id)
        _seed_events_high_tier(session, project_id, NUM_EVENTS)
        preset_name = _seed_filter_preset(session, project_id)
        webhook_id = _seed_webhook_and_binding(session, project_id, preset_name)
        session.commit()

        # --- Setup Redis + flush burst key -----------------------------------
        r = redis_lib.from_url(redis_url)
        rkey = burst_key(str(project_id))
        # Flush ALL keys in the test Redis DB (DB 12 is test-only per conftest)
        # to prevent stale burst-window entries from testcontainer reuse across
        # pytest sessions. Using flushdb is safer than delete(rkey) because
        # burst keys from prior runs with different project UUIDs can accumulate
        # and create confusing interference via ZSET ordering edge cases.
        r.flushdb()
        r.delete(rkey)  # defensive no-op after flushdb
        # Verify the key is clean before we start.
        pre_zcard = r.zcard(rkey)
        assert pre_zcard == 0, f"Pre-test: expected ZCARD=0 for {rkey}, got {pre_zcard}"

        # --- Load webhook ORM object -----------------------------------------
        from sqlalchemy import select
        from app.models.webhooks import Webhook

        webhook = session.execute(
            select(Webhook).where(Webhook.id == webhook_id)
        ).scalar_one()

        # --- Mock HTTP fan-out -----------------------------------------------
        # Record the JSON payloads sent so we can inspect event counts.
        dispatched_payloads = []

        def _mock_post(url, *, json=None, headers=None, **kwargs):
            dispatched_payloads.append(json or {})
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            return mock_resp

        # Patch httpx.Client to intercept the POST in _post_with_retry
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = lambda s: mock_client_instance
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.post = _mock_post

        with patch("app.services.webhook_dispatcher.httpx.Client", return_value=mock_client_instance):
            _process_webhook(webhook, session, r)

        session.commit()

        # --- Assertions -------------------------------------------------------

        # 1. Exactly 1 HTTP POST must fire (the dispatcher sends ONE batch request
        #    per tick, not one per event). The batch must contain BURST_HIGH_CAP (5)
        #    events - the 45 suppressed events never enter the Redis batch.
        assert len(dispatched_payloads) == 1, (
            f"Expected exactly 1 HTTP POST (one batch), got {len(dispatched_payloads)}"
        )
        # Payload shape: {"events": [...], ...} (see webhook_payloads.py)
        payload = dispatched_payloads[0]
        dispatched_events = payload.get("events", [])
        assert len(dispatched_events) == EXPECTED_DISPATCHED, (
            f"Expected batch to contain {EXPECTED_DISPATCHED} events (BURST_HIGH_CAP), "
            f"got {len(dispatched_events)}. Full payload keys: {list(payload.keys())}"
        )

        # 2. 45 events must carry burst_cluster in their tags array.
        result = session.execute(
            text(
                "SELECT COUNT(*) FROM events "
                "WHERE project_id = :pid AND 'burst_cluster' = ANY(COALESCE(tags, ARRAY[]::text[]))"
            ),
            {"pid": str(project_id)},
        )
        burst_count = result.scalar()
        assert burst_count == EXPECTED_SUPPRESSED, (
            f"Expected {EXPECTED_SUPPRESSED} events tagged burst_cluster, got {burst_count}"
        )

        # 3. Redis ZCARD for this project must equal BURST_HIGH_CAP (5 reserved slots).
        # record_high_tier_dispatch is called inline (before HTTP delivery) as each
        # HIGH-tier event is accepted into the surviving batch.
        zcard = r.zcard(rkey)
        assert zcard == BURST_HIGH_CAP, (
            f"Expected Redis ZCARD={BURST_HIGH_CAP}, got {zcard}"
        )

        # --- Cleanup ---------------------------------------------------------
        r.delete(rkey)

    engine.dispose()

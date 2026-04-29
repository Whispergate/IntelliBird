# Owned by: 15-07-PLAN (SCR-02, SCR-03)
"""Integration tests for scoring routes — Phase 15.

Covers:
  GET  /api/projects/{id}/scoring  — returns default or persisted rules
  PUT  /api/projects/{id}/scoring  — validates weights/tiers, persists, enqueues actor
  POST /api/projects/{id}/rescore  — manual trigger, 202
  GET  /api/projects/{id}/rescore/status  — shape test

Auth harness mirrors test_prod01_cross_project_leakage.py: real JWT middleware +
pinned signing key + stubbed token_version / jti lookups.

Two JWT variants seeded per project:
  lead_jwt   — pm=[[project_id, 3]]  (Lead rank = 3 per PROJECT_ROLE_RANK)
  observer_jwt — pm=[[project_id, 1]]  (Observer rank = 1)
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import MagicMock

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration

TEST_SIGNING_KEY = "j" * 64  # must match fixture mint key

# Valid default payload matching DEFAULT_SCORING_CONFIG exactly
VALID_RULES_PAYLOAD = {
    "weights": {"cvss": 50, "recency": 20, "source": 15, "relevance": 15},
    "decay_half_life_days": 14,
    "tier_cutoffs": {"S": 90, "A": 75, "B": 55, "C": 30},
}


# ---------------------------------------------------------------------------
# Harness helpers
# ---------------------------------------------------------------------------


def _patch_auth(monkeypatch) -> None:
    """Enable AUTH_ENABLED, pin signing key, stub token_version/jti checks."""
    import app.middleware.auth as auth_mod
    from app.config import settings

    monkeypatch.setattr(settings, "AUTH_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "JWT_SIGNING_KEY", TEST_SIGNING_KEY, raising=False)

    async def _tv(_user_id: str):
        return 0  # matches fixture-minted token_version

    async def _not_revoked(_jti: str) -> bool:
        return False

    monkeypatch.setattr(auth_mod, "_get_cached_token_version", _tv)
    monkeypatch.setattr(auth_mod, "_is_jti_revoked", _not_revoked)


async def _client():
    """Async httpx client wrapping the real FastAPI app."""
    from app.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _mint_jwt(project_id: uuid.UUID, rank: int) -> str:
    """Mint a JWT scoped to project_id with given rank."""
    from app.security.jwt import mint_access_token_with_pm

    user_id = str(uuid.uuid4())
    pm = [[str(project_id), rank]]
    token, _ = mint_access_token_with_pm(
        user_id, "Analyst", ["red", "blue"], 0, TEST_SIGNING_KEY, pm, False
    )
    return token


def _mint_lead(project_id: uuid.UUID) -> str:
    from app.security.jwt import PROJECT_ROLE_RANK
    return _mint_jwt(project_id, PROJECT_ROLE_RANK["Lead"])


def _mint_observer(project_id: uuid.UUID) -> str:
    from app.security.jwt import PROJECT_ROLE_RANK
    return _mint_jwt(project_id, PROJECT_ROLE_RANK["Observer"])


async def _seed_project(db_session) -> uuid.UUID:
    """Insert a minimal project row, return its id."""
    from sqlalchemy import text

    pid = uuid.uuid4()
    creator = str(uuid.uuid4())
    await db_session.execute(
        text(
            "INSERT INTO projects (id, name, engagement_type, created_by, archived) "
            "VALUES (:id, :name, 'internal', :cb, false)"
        ),
        {"id": pid, "name": f"scoring-test-{pid}", "cb": creator},
    )
    await db_session.commit()
    return pid


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_scoring_returns_default_when_no_override(db_session, monkeypatch):
    """GET /scoring on a fresh project returns 200 with is_default=True and default weights."""
    _patch_auth(monkeypatch)
    project_id = await _seed_project(db_session)
    lead_jwt = _mint_lead(project_id)

    async with await _client() as c:
        r = await c.get(
            f"/api/projects/{project_id}/scoring",
            headers=_bearer(lead_jwt),
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_default"] is True
    assert body["rules"]["weights"]["cvss"] == 50
    assert body["rules"]["weights"]["recency"] == 20
    assert body["rules"]["weights"]["source"] == 15
    assert body["rules"]["weights"]["relevance"] == 15
    assert body["rules"]["decay_half_life_days"] == 14
    assert body["rules"]["tier_cutoffs"]["S"] == 90


@pytest.mark.asyncio
async def test_put_scoring_persists_and_bumps_version(db_session, monkeypatch):
    """PUT with lead token persists rules; second GET returns is_default=False, version=2."""
    _patch_auth(monkeypatch)
    project_id = await _seed_project(db_session)
    lead_jwt = _mint_lead(project_id)

    # Patch the actor send so no real Dramatiq broker is needed
    import app.workers.scoring as scoring_mod
    mock_send = MagicMock()
    monkeypatch.setattr(scoring_mod.rescore_project, "send", mock_send)

    async with await _client() as c:
        # First PUT creates version=1
        r1 = await c.put(
            f"/api/projects/{project_id}/scoring",
            json=VALID_RULES_PAYLOAD,
            headers=_bearer(lead_jwt),
        )
        assert r1.status_code == 200, r1.text
        body1 = r1.json()
        assert body1["is_default"] is False
        assert body1["version"] == 1

        # Second PUT bumps to version=2
        r2 = await c.put(
            f"/api/projects/{project_id}/scoring",
            json=VALID_RULES_PAYLOAD,
            headers=_bearer(lead_jwt),
        )
        assert r2.status_code == 200, r2.text
        body2 = r2.json()
        assert body2["version"] == 2

        # GET now returns persisted rules
        r3 = await c.get(
            f"/api/projects/{project_id}/scoring",
            headers=_bearer(lead_jwt),
        )
        assert r3.status_code == 200, r3.text
        body3 = r3.json()
        assert body3["is_default"] is False
        assert body3["version"] == 2


@pytest.mark.asyncio
async def test_put_scoring_rejects_weights_not_100(db_session, monkeypatch):
    """PUT with weights summing to 90 returns 422."""
    _patch_auth(monkeypatch)
    project_id = await _seed_project(db_session)
    lead_jwt = _mint_lead(project_id)

    bad_payload = {
        "weights": {"cvss": 40, "recency": 20, "source": 15, "relevance": 15},  # sum=90
        "decay_half_life_days": 14,
        "tier_cutoffs": {"S": 90, "A": 75, "B": 55, "C": 30},
    }

    async with await _client() as c:
        r = await c.put(
            f"/api/projects/{project_id}/scoring",
            json=bad_payload,
            headers=_bearer(lead_jwt),
        )

    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_put_scoring_rejects_non_descending_cutoffs(db_session, monkeypatch):
    """PUT with cutoffs S=80, A=85 (not descending) returns 422."""
    _patch_auth(monkeypatch)
    project_id = await _seed_project(db_session)
    lead_jwt = _mint_lead(project_id)

    bad_payload = {
        "weights": {"cvss": 50, "recency": 20, "source": 15, "relevance": 15},
        "decay_half_life_days": 14,
        "tier_cutoffs": {"S": 80, "A": 85, "B": 55, "C": 30},  # S < A — not descending
    }

    async with await _client() as c:
        r = await c.put(
            f"/api/projects/{project_id}/scoring",
            json=bad_payload,
            headers=_bearer(lead_jwt),
        )

    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_put_scoring_enqueues_rescore_actor(db_session, monkeypatch):
    """PUT enqueues rescore_project.send(str(project_id)) exactly once."""
    _patch_auth(monkeypatch)
    project_id = await _seed_project(db_session)
    lead_jwt = _mint_lead(project_id)

    import app.workers.scoring as scoring_mod
    mock_send = MagicMock()
    monkeypatch.setattr(scoring_mod.rescore_project, "send", mock_send)

    async with await _client() as c:
        r = await c.put(
            f"/api/projects/{project_id}/scoring",
            json=VALID_RULES_PAYLOAD,
            headers=_bearer(lead_jwt),
        )

    assert r.status_code == 200, r.text
    mock_send.assert_called_once_with(str(project_id))


@pytest.mark.asyncio
async def test_post_rescore_returns_202(db_session, monkeypatch):
    """POST /rescore with lead token returns 202 and {"queued": true}."""
    _patch_auth(monkeypatch)
    project_id = await _seed_project(db_session)
    lead_jwt = _mint_lead(project_id)

    import app.workers.scoring as scoring_mod
    mock_send = MagicMock()
    monkeypatch.setattr(scoring_mod.rescore_project, "send", mock_send)

    async with await _client() as c:
        r = await c.post(
            f"/api/projects/{project_id}/rescore",
            headers=_bearer(lead_jwt),
        )

    assert r.status_code == 202, r.text
    body = r.json()
    assert body["queued"] is True
    mock_send.assert_called_once_with(str(project_id))


@pytest.mark.asyncio
async def test_get_rescore_status_shape(db_session, monkeypatch):
    """GET /rescore/status returns 200 with expected keys."""
    _patch_auth(monkeypatch)
    project_id = await _seed_project(db_session)
    lead_jwt = _mint_lead(project_id)

    async with await _client() as c:
        r = await c.get(
            f"/api/projects/{project_id}/rescore/status",
            headers=_bearer(lead_jwt),
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert "last_rescore_at" in body
    assert "in_progress_count" in body
    assert "total_count" in body
    # Fresh project has no overrides yet
    assert body["last_rescore_at"] is None
    assert body["total_count"] == 0
    assert body["in_progress_count"] == 0


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_observer_cannot_put_scoring(db_session, monkeypatch):
    """PUT /scoring with observer token returns 403."""
    _patch_auth(monkeypatch)
    project_id = await _seed_project(db_session)
    observer_jwt = _mint_observer(project_id)

    async with await _client() as c:
        r = await c.put(
            f"/api/projects/{project_id}/scoring",
            json=VALID_RULES_PAYLOAD,
            headers=_bearer(observer_jwt),
        )

    assert r.status_code == 403, r.text


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_unmembered_user_gets_403(db_session, monkeypatch):
    """GET /scoring with a JWT that has no membership for this project returns 403."""
    _patch_auth(monkeypatch)
    project_id = await _seed_project(db_session)
    other_project_id = uuid.uuid4()  # a different project — user has no membership for project_id
    unrelated_jwt = _mint_observer(other_project_id)

    async with await _client() as c:
        r = await c.get(
            f"/api/projects/{project_id}/scoring",
            headers=_bearer(unrelated_jwt),
        )

    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# Phase 15-10 gap closure: score fields surfaced through GET /api/events
# ---------------------------------------------------------------------------

from datetime import UTC, datetime as _datetime
from decimal import Decimal as _Decimal
from sqlalchemy import text as _text


async def _seed_permissive_scope(db_session, project_id: uuid.UUID, keyword: str) -> None:
    """Insert a permissive keyword scope row so build_scope_predicate does NOT
    short-circuit to false (the empty-scope → empty-result guard requires at
    least one intel_scope=true row per project for GET /api/events to return
    rows — see events_query.py / project_scope.py).
    """
    await db_session.execute(
        _text(
            "INSERT INTO project_scope_rows "
            "(id, project_id, scope_type, value, intel_scope, active_test_scope, exclude) "
            "VALUES (gen_random_uuid(), :pid, 'keyword', :kw, true, false, false)"
        ),
        {"pid": project_id, "kw": keyword},
    )
    await db_session.commit()


async def _insert_event(
    db_session,
    project_id: uuid.UUID,
    title: str = "scoretest event",
    score: float | None = None,
    scored_at: _datetime | None = None,
    score_version: int | None = None,
) -> uuid.UUID:
    """Directly INSERT a minimal Event row into the events table with optional
    score fields. Returns the new event's UUID.

    Uses raw SQL to avoid ORM model import complications and to match the
    explicit kwargs pattern used in test_prod01_cross_project_leakage.py.

    The title includes "scoretest" — a single unambiguous FTS token — which
    matches the permissive scope keyword seeded by _seed_permissive_scope.
    """
    event_id = uuid.uuid4()
    now = _datetime.now(UTC)

    await db_session.execute(
        _text(
            "INSERT INTO events "
            "(id, observed_at, fetched_at, stix_type, project_id, title, "
            " content_hash, archived, visibility, score, scored_at, score_version) "
            "VALUES "
            "(:id, :observed_at, :fetched_at, :stix_type, :project_id, :title, "
            " :content_hash, false, 'shared', :score, :scored_at, :score_version)"
        ),
        {
            "id": event_id,
            "observed_at": now,
            "fetched_at": now,
            "stix_type": "indicator",
            "project_id": project_id,
            "title": title,
            "content_hash": f"scoretest-{event_id}",
            "score": _Decimal(str(score)) if score is not None else None,
            "scored_at": scored_at,
            "score_version": score_version,
        },
    )
    await db_session.commit()
    return event_id


@pytest.mark.asyncio
async def test_events_list_returns_score_fields(db_session, monkeypatch):
    """GET /api/events returns score/scored_at/score_version for scored events
    and null for unscored events.

    Gap closure: Phase 15-10 SC-1 BLOCKER — EventItem schema previously omitted
    these fields; _hydrate_item did not pass them. This test would FAIL if Task 1
    changes (schema + hydration) were reverted.
    """
    _patch_auth(monkeypatch)
    project_id = await _seed_project(db_session)
    lead_jwt = _mint_lead(project_id)

    # Seed a permissive scope row so build_scope_predicate does not short-circuit.
    # Keyword "scoretest" is a single FTS token (no hyphen) that reliably matches
    # the event titles seeded below.
    await _seed_permissive_scope(db_session, project_id, "scoretest")

    # Arrange — one scored event, one unscored event.
    # Both titles contain "scoretest" so they match the scope keyword via FTS.
    score_ts = _datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)
    scored_event_id = await _insert_event(
        db_session,
        project_id=project_id,
        title="scoretest scored event",
        score=87.5,
        scored_at=score_ts,
        score_version=3,
    )
    unscored_event_id = await _insert_event(
        db_session,
        project_id=project_id,
        title="scoretest unscored event",
        score=None,
        scored_at=None,
        score_version=None,
    )

    async with await _client() as c:
        resp = await c.get(
            "/api/events",
            headers=_bearer(lead_jwt),
            params={"project_id": str(project_id), "limit": 50},
        )

    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) >= 2, f"Expected >= 2 items, got {len(items)}: {items}"

    scored = next((i for i in items if i["id"] == str(scored_event_id)), None)
    assert scored is not None, f"Scored event {scored_event_id} not found in response"
    assert scored["score"] == 87.5, f"Expected score=87.5, got {scored['score']}"
    assert scored["scored_at"] is not None, "scored_at should be a non-null ISO string"
    assert scored["score_version"] == 3, f"Expected score_version=3, got {scored['score_version']}"

    unscored = next((i for i in items if i["id"] == str(unscored_event_id)), None)
    assert unscored is not None, f"Unscored event {unscored_event_id} not found in response"
    assert unscored["score"] is None, f"Expected score=null, got {unscored['score']}"
    assert unscored["scored_at"] is None, f"Expected scored_at=null, got {unscored['scored_at']}"
    assert unscored["score_version"] is None, f"Expected score_version=null, got {unscored['score_version']}"


@pytest.mark.asyncio
async def test_event_detail_returns_score_fields(db_session, monkeypatch):
    """GET /api/events/{id} returns score/scored_at/score_version for a scored event.

    Gap closure: Phase 15-10 SC-5 PARTIAL → VERIFIED — EventDetail inherits from
    EventItem and model_dump() propagates the new fields through the detail route.
    This test would FAIL if Task 1 changes were reverted.
    """
    _patch_auth(monkeypatch)
    project_id = await _seed_project(db_session)
    lead_jwt = _mint_lead(project_id)

    score_ts = _datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)
    scored_event_id = await _insert_event(
        db_session,
        project_id=project_id,
        title="scoretest detail event",
        score=87.5,
        scored_at=score_ts,
        score_version=3,
    )

    async with await _client() as c:
        resp = await c.get(
            f"/api/events/{scored_event_id}",
            headers=_bearer(lead_jwt),
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["score"] == 87.5, f"Expected score=87.5, got {body['score']}"
    assert body["score_version"] == 3, f"Expected score_version=3, got {body['score_version']}"
    assert body["scored_at"] is not None, "scored_at should be a non-null ISO string"


# ---------------------------------------------------------------------------
# Plan 15-11 gap-closure tests: Redis in-progress flag lifecycle (SCR-02)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rescore_inprogress_flag_visible_during_actor(monkeypatch):
    """Flag is set while rescore_project_events runs, cleared after.

    Invokes _async_rescore directly (not via Dramatiq broker) after monkey-
    patching the inner rescore_project_events coroutine. This isolates the
    SET/DEL flag lifecycle without requiring a running worker or real DB.
    (Plan 15-11 / SCR-02 advisory gap closure)
    """
    from unittest.mock import AsyncMock, MagicMock

    from app.services.redis_client import get_redis
    from app.workers.scoring import _async_rescore
    import app.services.scoring.rescore as rescore_mod
    import app.workers.scoring as scoring_mod

    project_id = uuid.uuid4()
    flag_key = f"rescore:project:{project_id}:active"
    seen_during: dict = {"value": None}

    async def fake_rescore(session, pid):
        redis = await get_redis()
        seen_during["value"] = await redis.exists(flag_key)
        return {"events_rescored": 0}

    monkeypatch.setattr(rescore_mod, "rescore_project_events", fake_rescore)

    # Patch engine/session so no real DB is needed for this flag-lifecycle test
    mock_engine = MagicMock()
    mock_engine.dispose = AsyncMock()
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session_factory = MagicMock(return_value=mock_session)

    monkeypatch.setattr(scoring_mod, "create_async_engine", lambda *a, **kw: mock_engine)
    monkeypatch.setattr(scoring_mod, "async_sessionmaker", lambda *a, **kw: mock_session_factory)

    await _async_rescore(project_id)

    assert seen_during["value"] == 1, "flag should exist while actor body runs"
    redis = await get_redis()
    assert await redis.exists(flag_key) == 0, "flag should be cleared in finally"


@pytest.mark.asyncio
async def test_rescore_status_reports_inprogress_when_flag_set(db_session, monkeypatch):
    """rescore_status returns in_progress_count=1 when flag set, 0 when absent.

    Directly manipulates the Redis flag and asserts the route handler reads it.
    (Plan 15-11 / SCR-02 advisory gap closure — the "Rescoring..." spinner UX)
    """
    _patch_auth(monkeypatch)
    project_id = await _seed_project(db_session)
    lead_jwt = _mint_lead(project_id)

    from app.services.redis_client import get_redis
    flag_key = f"rescore:project:{project_id}:active"
    redis = await get_redis()

    # Ensure no stale flag from a previous run
    await redis.delete(flag_key)

    async with await _client() as c:
        # No flag present: in_progress_count == 0
        resp = await c.get(
            f"/api/projects/{project_id}/rescore/status",
            headers=_bearer(lead_jwt),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["in_progress_count"] == 0

        # Set flag: in_progress_count == 1
        await redis.set(flag_key, "1", ex=60)
        resp = await c.get(
            f"/api/projects/{project_id}/rescore/status",
            headers=_bearer(lead_jwt),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["in_progress_count"] == 1

    # Cleanup
    await redis.delete(flag_key)

"""Integration tests for BRAND-02 — PATCH history append + match details endpoint.

Phase 21 / BRAND-02. TDD Wave 1 (RED baseline before implementation).

Tests:
  - test_patch_appends_history             — PATCH with note + status creates history[0]
  - test_patch_preserves_detector_keys     — PATCH leaves existing detector keys intact
  - test_patch_appends_multiple            — two PATCHes → history len=2, ordered insertion
  - test_patch_note_max_500               — PATCH with 501-char note → 422
  - test_patch_observer_403               — Observer PATCH → 403 (existing gate, sanity)
  - test_details_endpoint_shape           — GET /matches/{id}/details returns correct shape
  - test_details_aggregate_counts         — 3 sibling matches → correct per-status counts
  - test_details_timeline_ordering        — 12 history entries → exactly 10, descending acted_at
  - test_details_observer_can_read        — Observer GET details → 200
  - test_details_cross_project_leakage    — details never returns data from other project
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Auth user builder (mirrors test_brand_router_matches.py pattern)
# ---------------------------------------------------------------------------

def _make_auth_user(
    role: str = "Admin",
    project_id: uuid.UUID | None = None,
    project_rank: int = 3,
    user_id: str | None = None,
):
    from app.security.jwt import AuthUser

    pm: dict[str, int] = {}
    if project_id is not None:
        pm[str(project_id)] = project_rank

    return AuthUser(
        id=user_id or str(uuid.uuid4()),
        role=role,
        dashboard_roles=["red", "blue"],
        jti=str(uuid.uuid4()),
        token_version=0,
        project_memberships=pm,
        pm_truncated=False,
    )


# ---------------------------------------------------------------------------
# App fixture that overrides session + auth
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def brand_app(db_engine, _migrations_applied):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from fastapi import FastAPI

    from app.database import get_session
    from app.middleware.auth import require_auth
    from app.routers.brand import router as brand_router

    factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)

    app = FastAPI()
    app.include_router(brand_router, prefix="/api")

    async def override_session():
        async with factory() as session:
            yield session

    admin_user = _make_auth_user(role="Admin")

    def override_require_auth():
        return admin_user

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_auth] = override_require_auth
    yield app, factory, admin_user


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

async def _seed_project(db_session, creator_id: str) -> uuid.UUID:
    pid = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO projects (id, name, engagement_type, created_by, archived) "
            "VALUES (CAST(:id AS uuid), :name, 'red_team', :cb, false)"
        ),
        {"id": str(pid), "name": f"brand-hist-proj-{pid.hex[:8]}", "cb": creator_id},
    )
    return pid


async def _seed_term(db_session, project_id: uuid.UUID) -> uuid.UUID:
    tid = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO brand_terms (id, project_id, term_type, value, mode, archived) "
            "VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), 'keyword', :val, 'active', false)"
        ),
        {"id": str(tid), "pid": str(project_id), "val": f"term-{tid.hex[:8]}"},
    )
    return tid


async def _seed_match(
    db_session,
    project_id: uuid.UUID,
    term_id: uuid.UUID,
    *,
    lifecycle: str = "new",
    matched_value: str | None = None,
    match_source: str = "fts",
    match_metadata: dict | None = None,
) -> uuid.UUID:
    mid = uuid.uuid4()
    mv = matched_value or f"evil-{mid.hex[:8]}.com"
    import json as _json
    meta_val = _json.dumps(match_metadata) if match_metadata else None
    await db_session.execute(
        text(
            """
            INSERT INTO brand_matches (
                id, project_id, brand_term_id, matched_value, match_source,
                severity, first_seen, last_seen, lifecycle_status, match_metadata
            ) VALUES (
                CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:tid AS uuid),
                :mv, :src, 'high', now(), now(), :lc,
                CAST(:meta AS jsonb)
            )
            """
        ),
        {
            "id": str(mid),
            "pid": str(project_id),
            "tid": str(term_id),
            "mv": mv,
            "src": match_source,
            "lc": lifecycle,
            "meta": meta_val,
        },
    )
    return mid


# ---------------------------------------------------------------------------
# Task 1: RED tests — PATCH history append
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_appends_history(brand_app, db_session):
    """PATCH with lifecycle_status + note appends a history entry."""
    app, factory, admin_user = brand_app

    pid = await _seed_project(db_session, admin_user.id)
    tid = await _seed_term(db_session, pid)
    mid = await _seed_match(db_session, pid, tid)
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch(
            f"/api/projects/{pid}/brand/matches/{mid}",
            json={"lifecycle_status": "confirmed", "note": "test note"},
        )
    assert r.status_code == 200, r.text

    # Verify history written to DB
    async with factory() as s:
        row = (await s.execute(
            text("SELECT match_metadata FROM brand_matches WHERE id = CAST(:id AS uuid)"),
            {"id": str(mid)},
        )).mappings().one()

    meta = row["match_metadata"] or {}
    history = meta.get("history", [])
    assert len(history) == 1, f"Expected 1 history entry, got {len(history)}: {history}"

    entry = history[0]
    assert entry["action"] == "confirmed"
    assert entry["prev_status"] == "new"
    assert entry["new_status"] == "confirmed"
    assert entry["note"] == "test note"
    assert "acted_at" in entry
    assert "actor_id" in entry


@pytest.mark.asyncio
async def test_patch_preserves_detector_keys(brand_app, db_session):
    """PATCH must not clobber existing detector provenance keys in match_metadata."""
    app, factory, admin_user = brand_app

    pid = await _seed_project(db_session, admin_user.id)
    tid = await _seed_term(db_session, pid)
    mid = await _seed_match(
        db_session, pid, tid,
        match_metadata={"event_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"},
    )
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch(
            f"/api/projects/{pid}/brand/matches/{mid}",
            json={"lifecycle_status": "confirmed"},
        )
    assert r.status_code == 200, r.text

    async with factory() as s:
        row = (await s.execute(
            text("SELECT match_metadata FROM brand_matches WHERE id = CAST(:id AS uuid)"),
            {"id": str(mid)},
        )).mappings().one()

    meta = row["match_metadata"] or {}
    # Detector key must survive
    assert meta.get("event_id") == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", (
        f"Detector key 'event_id' was clobbered: {meta}"
    )
    # And history was appended
    assert len(meta.get("history", [])) == 1


@pytest.mark.asyncio
async def test_patch_appends_multiple(brand_app, db_session):
    """Two successive PATCHes produce history len=2, ordered by acted_at."""
    app, factory, admin_user = brand_app

    pid = await _seed_project(db_session, admin_user.id)
    tid = await _seed_term(db_session, pid)
    mid = await _seed_match(db_session, pid, tid)
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.patch(
            f"/api/projects/{pid}/brand/matches/{mid}",
            json={"lifecycle_status": "confirmed"},
        )
        assert r1.status_code == 200
        r2 = await client.patch(
            f"/api/projects/{pid}/brand/matches/{mid}",
            json={"lifecycle_status": "watchlist", "note": "moved to watchlist"},
        )
        assert r2.status_code == 200

    async with factory() as s:
        row = (await s.execute(
            text("SELECT match_metadata FROM brand_matches WHERE id = CAST(:id AS uuid)"),
            {"id": str(mid)},
        )).mappings().one()

    history = (row["match_metadata"] or {}).get("history", [])
    assert len(history) == 2, f"Expected 2 history entries, got {len(history)}"
    # First entry is older
    t1 = datetime.fromisoformat(history[0]["acted_at"])
    t2 = datetime.fromisoformat(history[1]["acted_at"])
    assert t1 <= t2, "History entries should be in insertion order (oldest first)"
    assert history[0]["action"] == "confirmed"
    assert history[1]["action"] == "watchlist"


@pytest.mark.asyncio
async def test_patch_note_max_500(brand_app, db_session):
    """PATCH with a 501-char note returns 422."""
    app, _factory, admin_user = brand_app

    pid = await _seed_project(db_session, admin_user.id)
    tid = await _seed_term(db_session, pid)
    mid = await _seed_match(db_session, pid, tid)
    await db_session.commit()

    long_note = "x" * 501
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch(
            f"/api/projects/{pid}/brand/matches/{mid}",
            json={"lifecycle_status": "confirmed", "note": long_note},
        )
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_patch_observer_403(brand_app, db_session):
    """Observer (project rank 1) cannot PATCH a match."""
    app, _factory, admin_user = brand_app
    from app.middleware.auth import require_auth

    pid = await _seed_project(db_session, admin_user.id)
    tid = await _seed_term(db_session, pid)
    mid = await _seed_match(db_session, pid, tid)
    await db_session.commit()

    # Observer: global Viewer role + project rank 1
    observer = _make_auth_user(role="Viewer", project_id=pid, project_rank=1)
    app.dependency_overrides[require_auth] = lambda: observer

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(
                f"/api/projects/{pid}/brand/matches/{mid}",
                json={"lifecycle_status": "confirmed"},
            )
        assert r.status_code == 403
    finally:
        # Restore original auth override
        app.dependency_overrides[require_auth] = lambda: admin_user


# ---------------------------------------------------------------------------
# Task 1: RED tests — GET /matches/{match_id}/details
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_details_endpoint_shape(brand_app, db_session):
    """GET /matches/{id}/details returns provenance + aggregate_counts + timeline."""
    app, _factory, admin_user = brand_app

    pid = await _seed_project(db_session, admin_user.id)
    tid = await _seed_term(db_session, pid)
    mid = await _seed_match(
        db_session, pid, tid,
        match_metadata={"event_id": "abcd1234-0000-0000-0000-000000000000"},
    )
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(f"/api/projects/{pid}/brand/matches/{mid}/details")

    assert r.status_code == 200, r.text
    body = r.json()

    assert "match_id" in body
    assert "provenance" in body
    assert "aggregate_counts" in body
    assert "timeline" in body

    provenance = body["provenance"]
    assert "detector" in provenance
    assert "matched_value" in provenance
    assert "raw_input" in provenance
    assert "similarity" in provenance

    counts = body["aggregate_counts"]
    assert "new" in counts
    assert "confirmed" in counts
    assert "dismissed" in counts
    assert "watchlist" in counts


@pytest.mark.asyncio
async def test_details_aggregate_counts(brand_app, db_session):
    """3 matches for same brand_term_id (1 confirmed, 1 dismissed, 1 new) → correct counts."""
    app, _factory, admin_user = brand_app

    pid = await _seed_project(db_session, admin_user.id)
    tid = await _seed_term(db_session, pid)
    mid_confirmed = await _seed_match(db_session, pid, tid, lifecycle="confirmed", matched_value="evil-a.com")
    await _seed_match(db_session, pid, tid, lifecycle="dismissed", matched_value="evil-b.com")
    await _seed_match(db_session, pid, tid, lifecycle="new", matched_value="evil-c.com")
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(f"/api/projects/{pid}/brand/matches/{mid_confirmed}/details")

    assert r.status_code == 200, r.text
    counts = r.json()["aggregate_counts"]
    assert counts["confirmed"] == 1, f"Expected confirmed=1, got {counts}"
    assert counts["dismissed"] == 1, f"Expected dismissed=1, got {counts}"
    assert counts["new"] == 1, f"Expected new=1, got {counts}"
    assert counts["watchlist"] == 0, f"Expected watchlist=0, got {counts}"


@pytest.mark.asyncio
async def test_details_timeline_ordering(brand_app, db_session):
    """12 history entries across sibling matches → timeline has exactly 10, descending acted_at."""
    app, factory, admin_user = brand_app

    pid = await _seed_project(db_session, admin_user.id)
    tid = await _seed_term(db_session, pid)

    # Create 2 sibling matches, each with 6 history entries (12 total)
    base_time = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    history_a = [
        {
            "acted_at": (base_time + timedelta(hours=i)).isoformat(),
            "actor_id": "actor-a-id",
            "action": "confirmed",
            "prev_status": "new",
            "new_status": "confirmed",
            "note": None,
        }
        for i in range(6)
    ]
    history_b = [
        {
            "acted_at": (base_time + timedelta(hours=i + 6)).isoformat(),
            "actor_id": "actor-b-id",
            "action": "watchlist",
            "prev_status": "new",
            "new_status": "watchlist",
            "note": None,
        }
        for i in range(6)
    ]

    mid_a = await _seed_match(
        db_session, pid, tid,
        matched_value="a.evil.com",
        match_metadata={"history": history_a},
    )
    await _seed_match(
        db_session, pid, tid,
        matched_value="b.evil.com",
        match_metadata={"history": history_b},
    )
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(f"/api/projects/{pid}/brand/matches/{mid_a}/details")

    assert r.status_code == 200, r.text
    timeline = r.json()["timeline"]
    assert len(timeline) == 10, f"Expected 10 timeline entries, got {len(timeline)}"

    # Verify descending acted_at order
    times = [datetime.fromisoformat(e["acted_at"]) for e in timeline]
    assert times == sorted(times, reverse=True), (
        f"Timeline not descending: {[str(t) for t in times]}"
    )

    # The 10 newest entries should be the last 4 from history_a + all 6 from history_b
    # (12 total, take 10 newest)
    oldest_in_timeline = min(times)
    assert oldest_in_timeline >= base_time + timedelta(hours=2), (
        f"Expected to skip oldest 2, but found entry from {oldest_in_timeline}"
    )


@pytest.mark.asyncio
async def test_details_observer_can_read(brand_app, db_session):
    """Observer (rank 1) can read the details endpoint (Observer+ access)."""
    app, _factory, admin_user = brand_app
    from app.middleware.auth import require_auth

    pid = await _seed_project(db_session, admin_user.id)
    tid = await _seed_term(db_session, pid)
    mid = await _seed_match(db_session, pid, tid)
    await db_session.commit()

    observer = _make_auth_user(role="Viewer", project_id=pid, project_rank=1)
    app.dependency_overrides[require_auth] = lambda: observer

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/api/projects/{pid}/brand/matches/{mid}/details")
        assert r.status_code == 200, f"Observer should be able to read details: {r.text}"
    finally:
        app.dependency_overrides[require_auth] = lambda: admin_user


@pytest.mark.asyncio
async def test_details_cross_project_leakage(brand_app, db_session):
    """PROD-01: GET details for project_a match must NEVER return history from project_b.

    Scenario:
      - Project A and Project B each have a match for the SAME term value.
      - Both matches have history entries.
      - GET /projects/{a}/brand/matches/{match_a}/details must only return
        counts + timeline from Project A's matches.
    """
    app, factory, admin_user = brand_app

    actor_a_id = str(uuid.uuid4())
    actor_b_id = str(uuid.uuid4())

    # Project A
    pid_a = await _seed_project(db_session, admin_user.id)
    tid_a = await _seed_term(db_session, pid_a)
    history_a = [
        {
            "acted_at": "2026-01-01T10:00:00+00:00",
            "actor_id": actor_a_id,
            "action": "confirmed",
            "prev_status": "new",
            "new_status": "confirmed",
            "note": "project-a-note",
        }
    ]
    mid_a = await _seed_match(
        db_session, pid_a, tid_a,
        matched_value="evil.com",
        lifecycle="confirmed",
        match_metadata={"history": history_a},
    )
    # Additional match in project_a for count
    await _seed_match(db_session, pid_a, tid_a, matched_value="evil2.com", lifecycle="new")

    # Project B — separate project/term, but same matched value to simulate overlap
    pid_b = await _seed_project(db_session, admin_user.id)
    tid_b = await _seed_term(db_session, pid_b)
    history_b = [
        {
            "acted_at": "2026-01-02T10:00:00+00:00",
            "actor_id": actor_b_id,
            "action": "dismissed",
            "prev_status": "new",
            "new_status": "dismissed",
            "note": "project-b-secret-note",
        }
    ]
    await _seed_match(
        db_session, pid_b, tid_b,
        matched_value="evil.com",
        lifecycle="dismissed",
        match_metadata={"history": history_b},
    )
    await _seed_match(db_session, pid_b, tid_b, matched_value="evil3.com", lifecycle="confirmed")
    await db_session.commit()

    # GET details for project_a's match
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(f"/api/projects/{pid_a}/brand/matches/{mid_a}/details")

    assert r.status_code == 200, r.text
    body = r.json()

    # Aggregate counts must only reflect project_a (2 matches: 1 confirmed + 1 new)
    counts = body["aggregate_counts"]
    assert counts["confirmed"] == 1, f"Project B's data leaked into confirmed count: {counts}"
    assert counts["new"] == 1, f"Unexpected count: {counts}"
    assert counts["dismissed"] == 0, (
        f"Project B's dismissed count leaked into project A details: {counts}"
    )

    # Timeline must not contain project B actor_id or note
    timeline = body["timeline"]
    timeline_actor_ids = [e.get("actor_id") for e in timeline]
    assert actor_b_id not in timeline_actor_ids, (
        f"Project B actor_id leaked into project A timeline: {timeline_actor_ids}"
    )
    timeline_notes = [e.get("note") for e in timeline]
    assert "project-b-secret-note" not in timeline_notes, (
        f"Project B note leaked into project A timeline: {timeline_notes}"
    )

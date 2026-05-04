# Owned by: 13-01-PLAN (PROD-01) + 18-01-PLAN (TIBER-04 leakage extension)
"""Integration regression tests for PROD-01 cross-project leakage.

Tests below currently fail (red) until 18-03-PLAN service layer ships — H-4 leakage
gate per ROADMAP. The three test_tiber_* functions at the bottom of this file are the
Wave 0 red baseline: they import from app.services.tiber.auto_populate which does not
yet exist. They MUST fail today with ImportError/ModuleNotFoundError and MUST pass
after Wave 3 (18-03-PLAN) ships the TIBER service layer.

Proves Project A-scoped callers cannot observe Project B data through the four
surfaces mandated by 13-01-PLAN:

  1. REST list endpoint    — GET /api/events?project_id=<project_a>
  2. Project-scoped intel  — GET /api/projects/{project_b}/assets
  3. Project-scoped graph  — GET /api/events/{event_in_b}/graph?project_id=<project_b>
  4. Raw AGE BFS           — cypher('intellibird_graph', ...) variable-length path,
                             bounded *1..3 per AGE issue #195

A positive control (test 5) guards against a false-negative where the graph is
empty — it asserts Project A's own BFS returns the expected 20 events.

Fixture: two_project_fixture (conftest-registered; builds 2 projects × 20 events
each, all referencing the same :Actor in AGE with :SEEN_IN edges).

Auth pattern: real JWTs minted by the fixture + settings.AUTH_ENABLED patched
true + in-memory stubs for token_version / jti revocation (mirrors
test_admin_users.py convention).

Gaps surfaced during this plan (documented in 13-01-SUMMARY.md):
  - GAP-1: GET /api/events without a project_id query arg does NOT intersect
    request.state.user.project_memberships with the row filter. A JWT scoped
    to Project A sees Project B rows too. Mitigated here by explicitly passing
    project_id; full fix is a downstream plan.
  - GAP-2: GET /api/events/{id}/graph does NOT call require_project_membership
    on its project_id query param either. Isolation here rides on
    traverse_graph rejecting seed/project mismatch (404) + Cypher-level
    project_id filter — still leak-proof, but via the wrong layer.
"""
from __future__ import annotations

import os
import uuid

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from app.security.jwt import mint_access_token_with_pm
from app.services.graph_traversal import traverse_project  # noqa: F401

pytestmark = pytest.mark.integration

TEST_SIGNING_KEY = "j" * 64  # matches two_project.py fixture mint key


# ---------------------------------------------------------------------------
# Harness helpers — mirror test_admin_users._patch_auth + _client
# ---------------------------------------------------------------------------


def _patch_auth(monkeypatch) -> None:
    """Enable AUTH_ENABLED, pin signing key, stub token_version/jti checks.

    The fixture mints its JWTs with token_version=0 and a random jti — without
    these stubs the real middleware would call Redis / DB for those lookups
    and fail in the testcontainer."""
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
    """Async httpx client wrapping the real FastAPI app (all routers + middleware)."""
    from app.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _count_from_agtype(raw_value) -> int:
    """AGE count() RETURN comes back as an agtype literal; stringify + int-cast."""
    return int(str(raw_value))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def _seed_permissive_scope(db_session, project_id, keyword: str) -> None:
    """Insert a single keyword scope row so build_scope_predicate doesn't short
    to `false` (CONTEXT.md §Scope-intersection empty-scope-empty-result). The
    keyword matches the fixture's `evt-a-*` / `evt-b-*` title prefixes via FTS.
    """
    await db_session.execute(
        text(
            "INSERT INTO project_scope_rows "
            "(id, project_id, scope_type, value, intel_scope, active_test_scope, exclude) "
            "VALUES (gen_random_uuid(), :pid, 'keyword', :kw, true, false, false)"
        ),
        {"pid": project_id, "kw": keyword},
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_list_scoped(two_project_fixture, db_session, monkeypatch):
    """Surface 1: /api/events scoped to Project A returns ONLY Project A rows.

    Sends project_id=project_a so the row filter engages (see GAP-1 header
    comment). Asserts set equality of returned events' project_ids against
    {project_a.id}.

    Seeds a permissive keyword scope row first — without it, the Phase 10
    scope predicate shorts to `false` for projects lacking scope, producing
    an empty result set and a vacuous pass.
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture
    # Fixture titles start 'evt-a-<n>' / 'evt-b-<n>'; keyword 'evt' matches both
    # projects' events via FTS so the scope predicate selects them.
    await _seed_permissive_scope(db_session, fx.project_a.id, "evt")

    async with await _client() as c:
        r = await c.get(
            "/api/events",
            headers=_bearer(fx.jwt_a),
            params={"project_id": str(fx.project_a.id), "limit": 200},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    # EventItem schema omits project_id (the router pre-filters it); assert
    # set equality on the returned event *ids* against the 20 Project A event
    # ids minted by the fixture. Any ID outside that set = cross-project leak.
    returned_ids = {item["id"] for item in body["items"]}
    expected_a_ids = {str(eid) for eid in fx.events_a}
    b_ids = {str(eid) for eid in fx.events_b}
    assert returned_ids == expected_a_ids, (
        f"LEAK: events router returned unexpected event IDs. "
        f"Extra (not in Project A): {returned_ids - expected_a_ids} "
        f"Missing (should have been returned): {expected_a_ids - returned_ids}"
    )
    # Defensive: NO Project B event id must appear in the response.
    assert not (returned_ids & b_ids), (
        f"LEAK: Project B event IDs present in Project A scoped list: "
        f"{returned_ids & b_ids}"
    )
    assert len(body["items"]) == 20


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_intel_scoped(two_project_fixture, monkeypatch):
    """Surface 2: project-scoped intel route refuses cross-project access.

    /api/projects/{id}/assets is the Phase 11/12.1 intel surface over a
    project; it gates via require_project_membership(Observer). A JWT scoped
    to project_a must receive 403 when requesting project_b's assets.
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture

    async with await _client() as c:
        r = await c.get(
            f"/api/projects/{fx.project_b.id}/assets",
            headers=_bearer(fx.jwt_a),
        )
    assert r.status_code == 403, (
        f"LEAK: intel route {r.status_code} for cross-project JWT — {r.text}"
    )


@pytest.mark.asyncio
async def test_graph_scoped(two_project_fixture, monkeypatch):
    """Surface 3: graph route refuses to expose Project B events via Project A JWT.

    The graph router does NOT call require_project_membership (GAP-2). Isolation
    relies on traverse_graph's seed-vs-project mismatch check + cypher-level
    project filter. Concretely: a Project A JWT hitting a Project B event's
    graph with project_id=project_a narrows the BFS such that the seed fails
    the `seed.project_id == project_id` gate in graph_traversal.py:117 and
    returns 404. This test asserts the non-200 outcome — whether 403 (future
    hardening via membership dep) or 404 (current behavior). Either blocks
    the leak; both are regression-safe for PROD-01.
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture
    event_in_b = fx.events_b[0]  # a Project B event the user_a JWT must not see

    async with await _client() as c:
        r = await c.get(
            f"/api/events/{event_in_b}/graph",
            headers=_bearer(fx.jwt_a),
            params={"project_id": str(fx.project_a.id)},
        )
    # Accept either 403 (preferred future state: membership dep added) or 404
    # (current state: seed/project mismatch → traverse returns None → router
    # converts to 404). Reject 200 — that is a leak.
    assert r.status_code in (403, 404), (
        f"LEAK: graph router {r.status_code} for cross-project request — {r.text}"
    )


@pytest.mark.asyncio
async def test_age_bfs_scoped(two_project_fixture, db_session):
    """Surface 4: pre-filtered AGE BFS for Project A cannot reach Project B events.

    The shared :Actor vertex links to events in BOTH projects via :SEEN_IN.
    A Project A-scoped application query must pre-filter at the Cypher layer
    so that the BFS narrows to `(:Event {project_id: '<project_a>'})` before
    counting. Any Project B event that slips through is a leak.

    This test simulates the correctly-scoped query: BFS from the shared actor
    into Events whose `project_id` property equals project_a, then assert
    NONE of those events carry project_id = project_b. That count must be 0
    — the label-level gate is what saves us when application code does pre-
    filter. A future regression that drops `project_id` from the Event vertex
    properties OR rewrites the gate as a post-filter would flip this to >0.

    Path bound to *1..3 per AGE issue #195 (unbounded variable-length is a
    documented scaling cliff).
    """
    fx = two_project_fixture
    raw = await db_session.connection()
    await raw.exec_driver_sql("LOAD 'age'")
    await raw.exec_driver_sql('SET search_path = ag_catalog, "$user", public')

    # Simulate an application that has correctly pre-scoped its MATCH to
    # project_a via an Event-vertex property predicate. Then ask: are any of
    # the reachable Events actually tagged with project_b? If vertex-level
    # gating works, this is 0. If project_id lives only in SQL (not on the
    # AGE Event node), the label-level filter is a no-op and leak manifests.
    cypher_body = (
        "MATCH (a:Actor {id: '" + fx.shared_actor.id + "'})"
        "-[:SEEN_IN*1..3]-(e:Event {project_id: '" + str(fx.project_a.id) + "'}) "
        "WHERE e.project_id = '" + str(fx.project_b.id) + "' "
        "RETURN count(e) AS leaked"
    )
    sql = (
        "SELECT * FROM cypher('intellibird_graph', $$ "
        + cypher_body
        + " $$) AS (leaked ag_catalog.agtype)"
    )
    row = (await raw.exec_driver_sql(sql)).first()
    assert row is not None, "AGE BFS returned no rows at all — graph unreachable"
    leaked = _count_from_agtype(row[0])
    assert leaked == 0, (
        f"LEAK: Project A-scoped BFS reached {leaked} Project B event(s) via the "
        f"shared actor. The AGE vertex-level project_id gate is broken OR the "
        f"shared actor's event nodes are missing project_id properties."
    )


@pytest.mark.asyncio
async def test_positive_control_same_project(two_project_fixture, db_session):
    """Positive control (Pitfall 2): Project A's own BFS returns 20 events.

    Guards against an empty-graph false-negative where every leakage assertion
    would vacuously pass. Mirrors the AGE BFS in test_age_bfs_scoped but
    scopes to project_a — must return exactly 20 (the fixture's per-project
    event count).

    Bounded *1..3 per AGE issue #195.
    """
    fx = two_project_fixture
    raw = await db_session.connection()
    await raw.exec_driver_sql("LOAD 'age'")
    await raw.exec_driver_sql('SET search_path = ag_catalog, "$user", public')

    cypher_body = (
        "MATCH (a:Actor {id: '" + fx.shared_actor.id + "'})"
        "-[:SEEN_IN*1..3]-(e:Event {project_id: '" + str(fx.project_a.id) + "'}) "
        "RETURN count(e) AS seen"
    )
    sql = (
        "SELECT * FROM cypher('intellibird_graph', $$ "
        + cypher_body
        + " $$) AS (seen ag_catalog.agtype)"
    )
    row = (await raw.exec_driver_sql(sql)).first()
    assert row is not None
    seen = _count_from_agtype(row[0])
    assert seen == 20, (
        f"Positive control failed: expected 20 Project A events reachable "
        f"from shared actor via :SEEN_IN*1..3, got {seen}. Either fixture "
        f"seed changed or AGE edge traversal is broken — other tests may be "
        f"false-negatives."
    )

    # Sanity: SQL row count matches AGE graph count (fixture invariant).
    sql_count = (await db_session.execute(
        text("SELECT count(*) FROM events WHERE project_id = :pid"),
        {"pid": fx.project_a.id},
    )).scalar_one()
    assert sql_count == 20, f"SQL row count diverged from AGE seed: {sql_count}"


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_list_no_project_id_rejects_non_admin(two_project_fixture, db_session, monkeypatch):
    """GAP-1 regression lock: GET /api/events WITHOUT project_id must be rejected for non-admin callers.

    This test closes the coverage gap identified as GAP-1 in 13-01-SUMMARY.md. The five
    pre-existing tests in this file all pass `?project_id=<A>` explicitly, so the path
    where `enforce_project_query_scope` fires at `backend/app/routers/events.py:158` had
    ZERO regression coverage.

    Without this test, a future PR that removes or comments out line 158
    (the `enforce_project_query_scope` call) would leave the entire existing
    PROD-01 suite green, silently re-opening the cross-project leak.

    Expected flow:
      - Contributor JWT scoped to Project A only → project_memberships = {project_a.id}
      - GET /api/events with NO project_id query param
      - enforce_project_query_scope returns list[UUID] (the one-element membership set)
      - Router raises HTTPException(400): "project_id query parameter required for non-admin callers"
      - Response MUST be 400 or 403 (accept either to survive a future tightening that
        moves the raise into the helper itself at 403 rather than in the router wrapper)
      - Response body MUST NOT contain any Project B event UUID (defensive: if 200 is ever
        returned it must not be a leak)

    Link: backend/app/routers/events.py:158 (enforce_project_query_scope wiring)
    Requirement: PROD-01 / GAP-1
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture

    # Seed permissive scope so that, if the leak re-appeared and returned 200, the
    # response would contain observable event IDs rather than an empty list (which
    # would make the leak invisible).
    await _seed_permissive_scope(db_session, fx.project_a.id, "evt")

    async with await _client() as c:
        r = await c.get("/api/events", headers=_bearer(fx.jwt_a))
    # NO project_id, NO limit — raw request to hit the no-param path.

    assert r.status_code in (400, 403), (
        f"GAP-1 REGRESSION: GET /api/events without project_id from non-admin "
        f"returned {r.status_code}, expected 400 or 403. "
        f"Body: {r.text}"
    )

    # Defensive: even if status is wrong, no Project B event UUID must appear in body.
    b_id_strs = {str(eid) for eid in fx.events_b}
    for eid_str in b_id_strs:
        assert eid_str not in r.text, (
            f"GAP-1 REGRESSION: Project B event {eid_str} visible in response body "
            f"(status {r.status_code}). Cross-project leak detected."
        )


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_score_filter_no_leakage(two_project_fixture, db_session, monkeypatch):
    """SCR-03 PROD-01 extension: a score override in Project A does NOT bleed
    into Project B's tier-filtered query.

    Setup:
      - Insert one event_score_overrides row for the FIRST event in Project A
        with score=95.0 (S tier), score_version=2. This makes that event S-tier
        when Project A scores are consulted.
      - Project B events have no overrides (score IS NULL → coalesces to 0 → tier D).

    Assertions:
      a. GET /api/events?project_id=A&tier=S with jwt_a  → 200, that event id present.
      b. GET /api/events?project_id=B&tier=S with jwt_b  → 200, zero events (no B-scope
         event qualifies S-tier; Project A's override does NOT bleed across).
      c. GET /api/events?project_id=A with jwt_b         → 403 (existing PROD-01 path).

    This test proves the tier filter flows through the build_scope_predicate chokepoint
    (events.project_id scopes which events are returned; the override lateral subquery
    only adds a score column — it cannot pull in Project B events).
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture

    # Seed permissive keyword scope so build_scope_predicate does not short-circuit
    # to `false` for projects without scope rows (plan 13-01 SUMMARY §GAP note).
    await _seed_permissive_scope(db_session, fx.project_a.id, "evt")
    await _seed_permissive_scope(db_session, fx.project_b.id, "evt")

    # Pick the first Project A event and insert an S-tier override for it.
    scored_event_id = fx.events_a[0]
    await db_session.execute(
        text(
            "INSERT INTO event_score_overrides "
            "(event_id, project_id, score_version, score, scored_at) "
            "VALUES (:eid, :pid, 2, 95.0, now())"
        ),
        {"eid": scored_event_id, "pid": fx.project_a.id},
    )
    await db_session.commit()

    async with await _client() as c:
        # (a) Project A scoped, tier=S — the S-tier event must appear.
        r_a = await c.get(
            "/api/events",
            headers=_bearer(fx.jwt_a),
            params={
                "project_id": str(fx.project_a.id),
                "tier": "S",
                "limit": 200,
            },
        )
        assert r_a.status_code == 200, (
            f"Expected 200 for project_a tier=S query, got {r_a.status_code}: {r_a.text}"
        )
        returned_a_ids = {item["id"] for item in r_a.json()["items"]}
        assert str(scored_event_id) in returned_a_ids, (
            f"SCR-03: S-tier event {scored_event_id} not returned in Project A tier=S query. "
            f"Returned IDs: {returned_a_ids}"
        )

        # (b) Project B scoped, tier=S — must be empty (no Project B events are S-tier;
        #     Project A's override cannot bleed across the project boundary).
        r_b = await c.get(
            "/api/events",
            headers=_bearer(fx.jwt_b),
            params={
                "project_id": str(fx.project_b.id),
                "tier": "S",
                "limit": 200,
            },
        )
        assert r_b.status_code == 200, (
            f"Expected 200 for project_b tier=S query, got {r_b.status_code}: {r_b.text}"
        )
        returned_b_items = r_b.json()["items"]
        assert len(returned_b_items) == 0, (
            f"LEAK (SCR-03): Project B tier=S query returned {len(returned_b_items)} event(s) "
            f"— Project A's override should NOT bleed into Project B scope. "
            f"Returned IDs: {[i['id'] for i in returned_b_items]}"
        )
        # Defensive: Project A's scored event must not appear in Project B results.
        b_ids = {item["id"] for item in returned_b_items}
        assert str(scored_event_id) not in b_ids, (
            f"LEAK (SCR-03): Project A's S-tier event {scored_event_id} appeared in "
            f"Project B's tier=S response."
        )

        # (c) Cross-project access: Project B's JWT must NOT be able to query Project A.
        r_cross = await c.get(
            "/api/events",
            headers=_bearer(fx.jwt_b),
            params={"project_id": str(fx.project_a.id), "limit": 200},
        )
        assert r_cross.status_code == 403, (
            f"LEAK (PROD-01): jwt_b querying project_a returned {r_cross.status_code}, "
            f"expected 403. Body: {r_cross.text}"
        )


@pytest.mark.asyncio
async def test_list_no_project_id_admin_sees_all(two_project_fixture, db_session, monkeypatch):
    """Admin bypass regression lock: GET /api/events WITHOUT project_id must succeed for Admin callers.

    This test guards against an over-correction of GAP-1 that would tighten
    enforce_project_query_scope so hard that it also rejects Admin-role callers
    who legitimately need a global (cross-project) view.

    Expected flow:
      - Admin JWT (role='Admin', pm=[]) → enforce_project_query_scope returns None
      - GET /api/events?limit=200 with NO project_id query param
      - Response 200 with items from BOTH Project A and Project B
      - returned_ids must intersect fx.events_a (at least one Project A event returned)
      - returned_ids must intersect fx.events_b (at least one Project B event returned)

    Link: backend/app/routers/events.py:158 (enforce_project_query_scope returning None for Admin)
    Requirement: PROD-01 / GAP-1 admin-bypass
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture

    # Seed permissive keyword scope for BOTH projects so build_scope_predicate
    # does not short-circuit to false (the scope predicate only fires when
    # project_id is provided; admin without project_id skips it — but seed
    # anyway in case the router path changes).
    await _seed_permissive_scope(db_session, fx.project_a.id, "evt")
    await _seed_permissive_scope(db_session, fx.project_b.id, "evt")

    # Mint an Admin JWT: role='Admin', pm=[] (no project memberships required).
    # enforce_project_query_scope returns None for role == 'Admin' regardless of pm.
    import os as _os
    signing_key = _os.environ.get("JWT_SIGNING_KEY") or (_os.environ.get("SECRET_KEY")) or ("j" * 64)
    # Use TEST_SIGNING_KEY constant (pinned to 'j'*64) to match _patch_auth's monkeypatch.
    admin_user_id = str(__import__("uuid").uuid4())
    jwt_admin, _ = mint_access_token_with_pm(
        admin_user_id,
        "Admin",           # role — exact casing from app/middleware/auth.py:200 `user.role == "Admin"`
        ["red", "blue"],   # dashboard_roles — admin sees all visibility tiers
        0,                 # token_version — matches stub in _patch_auth
        TEST_SIGNING_KEY,  # signing key pinned by _patch_auth monkeypatch
        [],                # pm — Admin bypass; no project memberships needed
        False,             # pm_truncated
    )

    async with await _client() as c:
        r = await c.get("/api/events", headers=_bearer(jwt_admin), params={"limit": 200})

    assert r.status_code == 200, (
        f"Admin bypass broken: GET /api/events without project_id returned "
        f"{r.status_code}. Body: {r.text}"
    )

    returned_ids = {item["id"] for item in r.json()["items"]}
    expected_a = {str(eid) for eid in fx.events_a}
    expected_b = {str(eid) for eid in fx.events_b}

    assert returned_ids & expected_a, (
        "Admin bypass broken: no Project A events returned in all-projects query. "
        f"Returned IDs: {returned_ids!r}"
    )
    assert returned_ids & expected_b, (
        "Admin bypass broken: no Project B events returned in all-projects query. "
        f"Returned IDs: {returned_ids!r}"
    )


# ---------------------------------------------------------------------------
# TIBER-04 / H-4: TIBER auto-populate leakage gates (Wave 0 RED baseline)
#
# These three tests MUST FAIL today with ImportError — app.services.tiber.auto_populate
# does not yet exist. They will turn green after Wave 3 (18-03-PLAN) ships.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tiber_threat_landscape_no_leakage(two_project_fixture, db_session, monkeypatch):
    """TIBER-04 / H-4: populate_threat_landscape scoped to Project A returns zero Project B events.

    Exercises the build_scope_predicate chokepoint through the TIBER auto-populate
    layer. Every row in tl_top_events must carry project_id == project_a.

    Seed: existing two_project_fixture seeds 20 events per project with shared T1566.
    A permissive keyword='evt' scope row is added so build_scope_predicate does not
    short-circuit to `false` (empty scope → empty result → vacuous pass; per project_scope.py L182).
    """
    from app.services.tiber.auto_populate import populate_threat_landscape  # noqa: F401 — intentional ImportError

    _patch_auth(monkeypatch)
    fx = two_project_fixture
    project_a = fx.project_a.id
    project_b = fx.project_b.id

    # Seed permissive keyword scope for project_a
    await _seed_permissive_scope(db_session, project_a, "evt")

    rows = await populate_threat_landscape(db_session, project_id=project_a, top_n=20)

    # Every returned row must belong to project_a
    leaked_projects = {str(r.project_id) for r in rows if str(r.project_id) != str(project_a)}
    assert len(leaked_projects) == 0, (
        f"LEAK (TIBER-04): populate_threat_landscape returned events from wrong projects: "
        f"{leaked_projects}. All events must be scoped to project_a={project_a}."
    )
    # Defensive: no project_b id must appear
    b_ids_in_rows = {str(r.project_id) for r in rows} - {str(project_a)}
    assert str(project_b) not in b_ids_in_rows, (
        f"LEAK (TIBER-04): Project B events appeared in Project A threat landscape: "
        f"found project_ids={b_ids_in_rows}"
    )


@pytest.mark.asyncio
async def test_tiber_actor_profiles_no_leakage(two_project_fixture, db_session, monkeypatch):
    """TIBER-04 / H-4: populate_actor_profiles scoped to Project A returns zero Project B actors.

    Exercises the graph_traversal.py AGE Cypher path: actor traversal must be
    bounded by project_id so actors whose source events belong to Project B are
    excluded from Project A's TIBER report.

    Cross-check: actor.source_event_ids must not intersect fx.events_b (Project B
    event IDs seeded by two_project_fixture).
    """
    from app.services.tiber.auto_populate import populate_actor_profiles  # noqa: F401 — intentional ImportError

    _patch_auth(monkeypatch)
    fx = two_project_fixture
    project_a = fx.project_a.id
    project_b_event_ids = {str(eid) for eid in fx.events_b}

    actors = await populate_actor_profiles(db_session, project_id=project_a, top_n=6)

    for actor in actors:
        source_ids = {str(eid) for eid in getattr(actor, "source_event_ids", [])}
        leaked = source_ids & project_b_event_ids
        assert len(leaked) == 0, (
            f"LEAK (TIBER-04): Actor '{getattr(actor, 'name', actor)}' in Project A profile "
            f"has source_event_ids from Project B: {leaked}. "
            "graph_traversal must scope :SEEN_IN edges to project_id."
        )


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_tiber_scenarios_longlist_no_leakage(two_project_fixture, db_session, monkeypatch):
    """TIBER-04 / H-4: populate_scenarios_longlist scoped to Project A contains <=6 rows.

    Each scenario in the longlist must reference attack_technique_ids that were
    observed in at least one Project A event. TTPs seen only in Project B events
    must not appear in the Project A scenario longlist.

    Validation:
      - count <= 6 (max longlist per CONTEXT.md §Scenario count gate)
      - every scenario.attack_technique_id appears in
        SELECT DISTINCT technique_id FROM attack_technique_tags WHERE event_id IN
        (SELECT id FROM events WHERE project_id = project_a)
    """
    from app.services.tiber.auto_populate import populate_scenarios_longlist  # noqa: F401

    from sqlalchemy import text

    _patch_auth(monkeypatch)
    fx = two_project_fixture
    project_a = fx.project_a.id

    scenarios = await populate_scenarios_longlist(db_session, project_id=project_a, max_count=6)

    assert len(scenarios) <= 6, (
        f"TIBER-04: scenarios longlist returned {len(scenarios)} rows, max is 6."
    )

    # Fetch the set of technique_ids actually seen in Project A events
    # Table is attack_technique_tags (not event_attack_techniques — that table doesn't exist).
    result = await db_session.execute(
        text(
            "SELECT DISTINCT technique_id FROM attack_technique_tags "
            "WHERE event_id IN (SELECT id FROM events WHERE project_id = :pid)"
        ),
        {"pid": project_a},
    )
    project_a_techniques = {row[0] for row in result.fetchall()}

    for scenario in scenarios:
        technique_id = getattr(scenario, "attack_technique_id", None)
        if technique_id is not None and project_a_techniques:
            assert technique_id in project_a_techniques, (
                f"LEAK (TIBER-04): scenario technique {technique_id!r} was not observed "
                f"in any Project A event. Only Project B has this TTP — cross-project leak. "
                f"Project A techniques: {project_a_techniques}"
            )


# ---------------------------------------------------------------------------
# GRAPH-02 / H-4: Project-aggregate graph leakage gates
# ---------------------------------------------------------------------------


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_project_graph_no_leakage(two_project_fixture, db_session):
    """GRAPH-02 / H-4: traverse_project scoped to Project A returns ZERO nodes
    whose source event belongs to Project B.

    Directly calls the service layer (skip HTTP layer per H-4 pattern from
    Phases 13/15/18). The shared :Actor vertex links to events in BOTH projects
    via :SEEN_IN edges; the SQLAlchemy BFS must constrain traversal so that no
    node tagged with a Project B event id leaks through.

    Validation strategy:
      - Call traverse_project(db_session, project_a_id, dashboard_roles=["red","blue"],
        max_nodes=1000, max_edges=5000)
      - Inspect each node's `tag_source` field (set by add_node) — should NOT
        reference any id from fx.events_b (Project B event UUIDs as strings)
      - Assert result.truncated is False: 20 events at 1-hop depth is well below
        the 1000-node cap
    """
    fx = two_project_fixture
    project_a_id = fx.project_a.id
    project_b_event_ids = {str(eid) for eid in fx.events_b}

    result = await traverse_project(
        db_session,
        project_a_id,
        dashboard_roles=["red", "blue"],
        max_nodes=1000,
        max_edges=5000,
    )

    # No node should reference a Project B event id in its tag_source.
    leaked_nodes = []
    for node in result.nodes:
        ts = node.get("data", {}).get("tag_source")
        if ts is not None and str(ts) in project_b_event_ids:
            leaked_nodes.append(node)
    assert len(leaked_nodes) == 0, (
        f"LEAK (GRAPH-02): traverse_project for Project A returned {len(leaked_nodes)} "
        f"node(s) whose tag_source references a Project B event id. "
        f"Leaked nodes: {leaked_nodes}"
    )

    # The 20-event fixture seed is well below the 1000-node cap.
    assert result.truncated is False, (
        f"GRAPH-02: result.truncated=True for a 20-event fixture — cap logic may be wrong. "
        f"Node count: {len(result.nodes)}"
    )


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_project_graph_returns_only_in_scope_events(two_project_fixture, db_session):
    """GRAPH-02 positive control: traverse_project returns ≥1 node from Project A.

    Guards against a vacuous pass where the graph is empty (a bug in the
    implementation or a missing scope-row would produce zero nodes, making
    test_project_graph_no_leakage a false-negative).

    Asserts at least one returned node is an event node whose id appears in
    fx.events_a (Project A event UUIDs).
    """
    fx = two_project_fixture
    project_a_id = fx.project_a.id
    project_a_event_ids = {str(eid) for eid in fx.events_a}

    result = await traverse_project(
        db_session,
        project_a_id,
        dashboard_roles=["red", "blue"],
    )

    assert len(result.nodes) > 0, (
        "GRAPH-02 positive control: traverse_project returned zero nodes for a project "
        "with 20 seeded events. Check that the function actually traverses events."
    )

    # At least one event node's id must match a Project A event UUID.
    project_a_node_ids = set()
    for node in result.nodes:
        nid = node.get("data", {}).get("id", "")
        # Event nodes are keyed as "event:<uuid>" in GraphResult.add_node
        if nid.startswith("event:"):
            raw_id = nid[len("event:"):]
            if raw_id in project_a_event_ids:
                project_a_node_ids.add(raw_id)

    assert len(project_a_node_ids) > 0, (
        "GRAPH-02 positive control: no Project A event node found in traverse_project "
        f"result. Returned node ids: {[n.get('data', {}).get('id') for n in result.nodes[:10]]}. "
        "This would make test_project_graph_no_leakage a vacuous pass."
    )


# ---------------------------------------------------------------------------
# Phase 22 (IOC foundation) — Plan 22-03 wires the cross-project ACL chokepoint
# for the iocs table. This test covers BOTH directions of the IOC leakage
# surface:
#   1. GET /api/iocs scoped via build_ioc_scope_predicate
#   2. GET /api/events/{event_id}/iocs scoped via the SAME predicate (so a
#      Project A user pivoting against a Project B event_id receives [], not
#      403, not the data — no information disclosure).
# ---------------------------------------------------------------------------


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_iocs_leakage(two_project_fixture, db_session, monkeypatch):
    """IOC-03 / IOC-08: Admin sees A + B + global; Observer-A sees A + global.

    Setup:
      - Project A IOC (ip 1.1.1.1)
      - Project B IOC (ip 2.2.2.2)
      - Global IOC, project_id IS NULL (ip 3.3.3.3)

    Assertions:
      a. jwt_a (Lead on Project A) hitting GET /api/iocs sees A + global, NOT B.
      b. jwt_admin sees all three.
      c. jwt_a hitting GET /api/events/{B_event_id}/iocs (after linking the
         Project B IOC to a Project B event) returns [] — no leakage via the
         event-side pivot, even when the event_id itself is guessed.
      d. The same event-side endpoint returns the linked IOC for jwt_admin.

    Truncates iocs + ioc_event_links up-front because the shared
    _truncate_and_flush conftest fixture does not yet include them (carried as
    a follow-up from Plan 22-02 SUMMARY).
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture

    await db_session.execute(text("TRUNCATE TABLE ioc_event_links, iocs RESTART IDENTITY CASCADE"))
    await db_session.commit()

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    # Three IOCs: A-scoped, B-scoped, global.
    ioc_a = uuid.uuid4()
    ioc_b = uuid.uuid4()
    ioc_global = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO iocs "
            "(id, project_id, type, value, normalized_value, status, confidence, "
            " ttl_days, source, first_seen, last_seen, created_at, updated_at) "
            "VALUES "
            " (:a, :pa, 'ip', '1.1.1.1', '1.1.1.1', 'active', 0.8, 30, 'manual', :now, :now, :now, :now), "
            " (:b, :pb, 'ip', '2.2.2.2', '2.2.2.2', 'active', 0.8, 30, 'manual', :now, :now, :now, :now), "
            " (:g, NULL, 'ip', '3.3.3.3', '3.3.3.3', 'active', 1.0, 30, 'manual', :now, :now, :now, :now)"
        ),
        {
            "a": ioc_a, "pa": fx.project_a.id,
            "b": ioc_b, "pb": fx.project_b.id,
            "g": ioc_global, "now": now,
        },
    )

    # Link the Project B IOC to a Project B event (a real event already exists
    # courtesy of two_project_fixture's events_b list).
    event_b_id = fx.events_b[0]
    await db_session.execute(
        text(
            "INSERT INTO ioc_event_links (id, ioc_id, event_id, observed_at, source_field) "
            "VALUES (:id, :ioc, :evt, :now, 'description')"
        ),
        {"id": uuid.uuid4(), "ioc": ioc_b, "evt": event_b_id, "now": now},
    )
    await db_session.commit()

    async with await _client() as c:
        # (a) Observer-A (jwt_a) sees A + global only.
        r_a = await c.get("/api/iocs", headers=_bearer(fx.jwt_a), params={"limit": 200})
        assert r_a.status_code == 200, r_a.text
        ids_a = {row["id"] for row in r_a.json()}
        assert str(ioc_a) in ids_a, (
            f"LEAK (IOC-03): Project A's IOC missing from jwt_a result: {ids_a}"
        )
        assert str(ioc_global) in ids_a, (
            f"IOC-03: Global IOC missing from jwt_a result (must be visible to all): {ids_a}"
        )
        assert str(ioc_b) not in ids_a, (
            f"LEAK (IOC-03): Project B IOC visible to jwt_a — cross-project leakage: "
            f"{ids_a}"
        )

        # (b) Admin sees all three.
        r_admin = await c.get(
            "/api/iocs", headers=_bearer(fx.jwt_admin), params={"limit": 200},
        )
        assert r_admin.status_code == 200, r_admin.text
        ids_admin = {row["id"] for row in r_admin.json()}
        assert {str(ioc_a), str(ioc_b), str(ioc_global)}.issubset(ids_admin), (
            f"IOC-03: Admin must see all per-project + global rows; got: {ids_admin}"
        )

        # (c) Event-side leakage gate: jwt_a hitting Project B's event_id MUST
        #     return [] (NOT 403, NOT the IOC). Returning 403 would itself
        #     disclose that the event_id exists; returning [] is leak-proof.
        r_evt = await c.get(
            f"/api/events/{event_b_id}/iocs", headers=_bearer(fx.jwt_a),
        )
        assert r_evt.status_code == 200, (
            f"Expected 200 with empty body for cross-project event_id, got "
            f"{r_evt.status_code}: {r_evt.text}"
        )
        evt_rows = r_evt.json()
        evt_ids = {row["id"] for row in evt_rows}
        assert str(ioc_b) not in evt_ids, (
            f"LEAK (IOC-08 event-side): Project B IOC surfaced via "
            f"GET /api/events/{event_b_id}/iocs as jwt_a: {evt_rows}"
        )

        # (d) Same endpoint as Admin returns the IOC — proves the link is
        #     correctly wired and (c)'s emptiness was scope-driven, not a
        #     missing link.
        r_evt_admin = await c.get(
            f"/api/events/{event_b_id}/iocs", headers=_bearer(fx.jwt_admin),
        )
        assert r_evt_admin.status_code == 200, r_evt_admin.text
        admin_evt_ids = {row["id"] for row in r_evt_admin.json()}
        assert str(ioc_b) in admin_evt_ids, (
            f"IOC-08 positive control: Admin must see the linked IOC via the "
            f"event-side endpoint; got {admin_evt_ids}"
        )


# ---------------------------------------------------------------------------
# Phase 23 (IOC Enrichment APIs) — Plan 23-01 Wave 0 stub
#
# ENRICH-05: enrichment ACL chokepoint — ioc_enrichments rows for Project B
# must not be visible to a Project A caller via GET /api/iocs/{id}/enrichments.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.xfail(reason="not yet implemented — Phase 23 enrichment ACL not shipped")
async def test_enrichment_leakage(two_project_fixture):
    """PROD-01 extension: ioc_enrichments rows for Project B must not be
    visible to a Project A caller via GET /api/iocs/{id}/enrichments."""
    # Stub: will be fleshed out in plan 23-05 after routes exist.
    assert False, "enrichment leakage test not yet implemented"


# ---------------------------------------------------------------------------
# Phase 24 (Dark-Web Collection) — Plan 24-01 Wave 0 stub
#
# DARK-01..07: dark-web events (tor_html/paste/telegram) bound to Project B
# must not appear in Project A's /api/events response.
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Phase 24 not yet implemented")
async def test_darkweb_event_leakage(two_project_fixture):
    """Dark-web events (tor_html/paste/telegram) bound to Project B must not appear
    in Project A's /api/events response, even when Project A's JWT is used.
    Extends PROD-01 leakage contract to dark-web source types.
    """
    pass


# ---------------------------------------------------------------------------
# Phase 25 (Threat Actors, Campaigns & Audit Log) — Plan 25-01 Wave 0 stub
#
# ACTOR-03 / ACTOR-05 / ACTOR-06: campaigns bound to Project B must not be
# accessible via a Project A JWT through GET /api/campaigns.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=False, reason="actor/campaign routes pending Phase 25")
@pytest.mark.asyncio
async def test_actor_campaign_leakage(two_project_fixture):
    """PROD-01 extension: campaigns scoped to Project B must not be visible to Project A JWT.

    Setup:
      - Project A has a campaign with actor_id referencing a threat actor.
      - Project B has no campaigns.

    Assertion:
      - A JWT for a Project A member hitting GET /api/campaigns?project_id=<B>
        must NOT return any campaign rows (the project_id=NULL global campaigns
        and Project B-scoped campaigns must both be absent from a Project A
        member's cross-project query).

    This stub captures the leakage contract before campaign routes exist.
    It will be fleshed out in plan 25-05 after the campaign CRUD routes ship.
    """
    assert False, "stub — implement after Phase 25 campaign routes ship"


# ---------------------------------------------------------------------------
# Phase 28 (GRAPH-04) — Multi-hop DomainPivot traverse isolation gates
#
# These tests prove that 2-hop and 3-hop AGE Cypher traversals scoped to
# Project A cannot reach DomainPivot nodes belonging to Project B, even when
# those nodes share a registrar or IP (i.e. WOULD be connected if
# project_id were not embedded in the vertex properties).
#
# Setup per test:
#   - Insert one domain IOC in project_a and one in project_b, both with
#     the same registrar in whois_cache (simulating infrastructure overlap).
#   - Call sync_domain_pivot() which MERGEs DomainPivot nodes. Because the
#     cross-domain sibling SQL query is project-scoped, no SHARES_INFRA edge
#     is created between the two projects' nodes.
#   - Run AGE Cypher traversal scoped to project_a and assert zero project_b
#     nodes leak through.
# ---------------------------------------------------------------------------


async def _seed_domain_pivot_pair(db_session, project_a_id, project_b_id):
    """Seed one domain IOC + whois_cache row per project, then sync to AGE graph.

    Returns (domain_a, ioc_id_a, domain_b, ioc_id_b).
    Both domains share registrar 'SameRegistrar Inc.' to maximise leakage risk.
    """
    import uuid as _uuid
    from datetime import datetime, timezone
    from sqlalchemy import text as _text
    from app.services.age_sync import sync_domain_pivot

    now = datetime.now(timezone.utc)
    domain_a = f"domain-a-{_uuid.uuid4().hex[:8]}.example.com"
    domain_b = f"domain-b-{_uuid.uuid4().hex[:8]}.example.com"
    ioc_id_a = _uuid.uuid4()
    ioc_id_b = _uuid.uuid4()

    # Insert IOC rows
    await db_session.execute(
        _text(
            "INSERT INTO iocs "
            "(id, project_id, type, value, normalized_value, status, confidence, "
            " ttl_days, source, first_seen, last_seen, created_at, updated_at) "
            "VALUES "
            "(:a, :pa, 'domain', :da, :da, 'active', 0.8, 30, 'manual', :now, :now, :now, :now), "
            "(:b, :pb, 'domain', :db, :db, 'active', 0.8, 30, 'manual', :now, :now, :now, :now)"
        ),
        {
            "a": ioc_id_a, "pa": project_a_id, "da": domain_a,
            "b": ioc_id_b, "pb": project_b_id, "db": domain_b,
            "now": now,
        },
    )

    # Insert whois_cache rows — same registrar to simulate infrastructure overlap
    await db_session.execute(
        _text(
            "INSERT INTO whois_cache (domain, registrar, registrant_email, fetched_at) "
            "VALUES (:da, 'SameRegistrar Inc.', 'admin@same-registrar.example', :now), "
            "       (:db, 'SameRegistrar Inc.', 'admin@same-registrar.example', :now) "
            "ON CONFLICT (domain) DO UPDATE SET registrar = EXCLUDED.registrar, "
            "  registrant_email = EXCLUDED.registrant_email, fetched_at = EXCLUDED.fetched_at"
        ),
        {"da": domain_a, "db": domain_b, "now": now},
    )
    await db_session.commit()

    # Sync each domain to the AGE graph — this MERGEs DomainPivot nodes and
    # (correctly) does NOT create cross-project SHARES_INFRA edges.
    await sync_domain_pivot(db_session, str(ioc_id_a), domain_a, str(project_a_id))
    await sync_domain_pivot(db_session, str(ioc_id_b), domain_b, str(project_b_id))

    return domain_a, ioc_id_a, domain_b, ioc_id_b


@pytest.mark.asyncio
async def test_traverse_2hop_isolation(two_project_fixture, db_session):
    """GRAPH-04: 2-hop DomainPivot traversal scoped to Project A returns ZERO Project B nodes.

    Two domain IOCs share the same registrar (prime leakage vector via
    SHARES_INFRA). After sync, a Project A-scoped 2-hop AGE Cypher traversal
    must not reach the Project B DomainPivot node.

    Proves: project_id property on DomainPivot vertices structurally prevents
    cross-project traversal when the WHERE predicate is applied correctly.
    """
    fx = two_project_fixture
    _, _, domain_b, _ = await _seed_domain_pivot_pair(
        db_session, fx.project_a.id, fx.project_b.id
    )

    raw = await db_session.connection()
    await raw.exec_driver_sql("LOAD 'age'")
    await raw.exec_driver_sql('SET search_path = ag_catalog, "$user", public')

    pid_a = str(fx.project_a.id)
    pid_b = str(fx.project_b.id)

    # 2-hop traversal from ALL project_a DomainPivot nodes — should never reach project_b
    cypher_body = (
        f"MATCH (seed:DomainPivot {{project_id: '{pid_a}'}})"
        f"-[:SHARES_INFRA*1..2]-(t:DomainPivot) "
        f"WHERE t.project_id = '{pid_b}' "
        f"RETURN count(t) AS leaked"
    )
    sql = (
        "SELECT * FROM cypher('intellibird_graph', $$ "
        + cypher_body
        + " $$) AS (leaked ag_catalog.agtype)"
    )
    row = (await raw.exec_driver_sql(sql)).first()
    assert row is not None, "AGE traversal returned no rows — graph may be unreachable"
    leaked = _count_from_agtype(row[0])
    assert leaked == 0, (
        f"LEAK (GRAPH-04): 2-hop DomainPivot traversal from project_a reached "
        f"{leaked} project_b node(s). SHARES_INFRA edges must not cross project boundaries."
    )


@pytest.mark.asyncio
async def test_traverse_3hop_isolation(two_project_fixture, db_session):
    """GRAPH-04: 3-hop DomainPivot traversal scoped to Project A returns ZERO Project B nodes.

    Extends test_traverse_2hop_isolation to 3 hops — the maximum supported by
    the traverse endpoint. Deeper traversal must not create more leakage surface.
    """
    fx = two_project_fixture
    await _seed_domain_pivot_pair(db_session, fx.project_a.id, fx.project_b.id)

    raw = await db_session.connection()
    await raw.exec_driver_sql("LOAD 'age'")
    await raw.exec_driver_sql('SET search_path = ag_catalog, "$user", public')

    pid_a = str(fx.project_a.id)
    pid_b = str(fx.project_b.id)

    cypher_body = (
        f"MATCH (seed:DomainPivot {{project_id: '{pid_a}'}})"
        f"-[:SHARES_INFRA*1..3]-(t:DomainPivot) "
        f"WHERE t.project_id = '{pid_b}' "
        f"RETURN count(t) AS leaked"
    )
    sql = (
        "SELECT * FROM cypher('intellibird_graph', $$ "
        + cypher_body
        + " $$) AS (leaked ag_catalog.agtype)"
    )
    row = (await raw.exec_driver_sql(sql)).first()
    assert row is not None, "AGE 3-hop traversal returned no rows — graph may be unreachable"
    leaked = _count_from_agtype(row[0])
    assert leaked == 0, (
        f"LEAK (GRAPH-04): 3-hop DomainPivot traversal from project_a reached "
        f"{leaked} project_b node(s). Maximum hop depth must not increase leakage surface."
    )


@pytest.mark.asyncio
async def test_traverse_2hop_positive_control(two_project_fixture, db_session):
    """GRAPH-04 positive control: Project A's own DomainPivot is reachable at 1 hop.

    Guards against a vacuous pass where both isolation tests pass only because
    the graph is empty or the DomainPivot seed node was never created.
    A Project A-scoped 1-hop traversal must return >= 1 DomainPivot node
    (the seed itself, since we MERGE it unconditionally in sync_domain_pivot).
    """
    fx = two_project_fixture
    domain_a, _, _, _ = await _seed_domain_pivot_pair(
        db_session, fx.project_a.id, fx.project_b.id
    )

    raw = await db_session.connection()
    await raw.exec_driver_sql("LOAD 'age'")
    await raw.exec_driver_sql('SET search_path = ag_catalog, "$user", public')

    pid_a = str(fx.project_a.id)

    # Match the seed node itself (0-hop: start at project_a DomainPivot)
    cypher_body = (
        f"MATCH (d:DomainPivot {{domain: '{domain_a}', project_id: '{pid_a}'}}) "
        f"RETURN count(d) AS found"
    )
    sql = (
        "SELECT * FROM cypher('intellibird_graph', $$ "
        + cypher_body
        + " $$) AS (found ag_catalog.agtype)"
    )
    row = (await raw.exec_driver_sql(sql)).first()
    assert row is not None
    found = _count_from_agtype(row[0])
    assert found >= 1, (
        f"GRAPH-04 positive control FAILED: domain_a DomainPivot node not found in "
        f"intellibird_graph after sync_domain_pivot(). "
        f"Other isolation tests may be vacuous false-negatives. domain_a={domain_a}"
    )


# ---------------------------------------------------------------------------
# CASE-05: Cross-project case isolation (Phase 31)
# Added by 31-01-PLAN. Implemented by 31-05-PLAN.
# Verifies that a Project A JWT cannot read Project B's cases.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_isolation(two_project_fixture, monkeypatch):
    """CASE-05: A Project A JWT cannot read Project B's cases.

    Verifies that GET /api/projects/{project_b_id}/cases with a Project A JWT
    returns 403, preventing cross-project case data leakage.
    """
    pytest.skip("not yet implemented — plan 31-05 will turn this green")

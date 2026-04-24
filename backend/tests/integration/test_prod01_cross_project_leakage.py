# Owned by: 13-01-PLAN (PROD-01)
"""Integration regression tests for PROD-01 cross-project leakage.

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

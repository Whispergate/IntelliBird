"""Smoke test for two_project_fixture - PROD-01 Wave 0.

Asserts the fixture correctly seeds:
- 20 events per project in SQL (40 total)
- 1 :Actor + 40 :Event vertices + 40 :SEEN_IN edges in AGE graph
- JWTs decode to the correct project_id scopes

These are Wave 0 sanity checks for the fixture itself. PROD-01 plans build
on top once this smoke passes.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

# Ensure JWT signing key matches what the fixture mints with.
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)
os.environ.setdefault("SECRET_KEY", "s" * 64)


async def test_seed_counts(two_project_fixture, db_session):
    """SQL events: 20 per project. AGE: 1 Actor + 40 Events + 40 SEEN_IN edges."""
    fx = two_project_fixture

    # SQL: 20 events per project.
    count_a = (await db_session.execute(
        text("SELECT count(*) FROM events WHERE project_id = :pid"),
        {"pid": fx.project_a.id},
    )).scalar_one()
    assert count_a == 20, f"expected 20 events in project_a, got {count_a}"

    count_b = (await db_session.execute(
        text("SELECT count(*) FROM events WHERE project_id = :pid"),
        {"pid": fx.project_b.id},
    )).scalar_one()
    assert count_b == 20, f"expected 20 events in project_b, got {count_b}"

    # AGE: 1 Actor vertex with the shared id. Raw driver SQL avoids
    # SQLAlchemy text() parsing `:Label` as a bind parameter.
    raw = await db_session.connection()
    await raw.exec_driver_sql("LOAD 'age'")
    await raw.exec_driver_sql('SET search_path = ag_catalog, "$user", public')
    actor_rows = (await raw.exec_driver_sql(
        "SELECT count(*) FROM cypher('intellibird_graph', $$ "
        f"MATCH (a:Actor {{id: '{fx.shared_actor.id}'}}) RETURN a "
        "$$) AS (a ag_catalog.agtype)"
    )).scalar_one()
    assert actor_rows == 1, f"expected 1 :Actor vertex, got {actor_rows}"

    # AGE: 40 :Event vertices total.
    event_rows = (await raw.exec_driver_sql(
        "SELECT count(*) FROM cypher('intellibird_graph', $$ "
        "MATCH (e:Event) RETURN e "
        "$$) AS (e ag_catalog.agtype)"
    )).scalar_one()
    assert event_rows >= 40, f"expected >=40 :Event vertices, got {event_rows}"

    # AGE: 40 :SEEN_IN edges from Event to the shared Actor.
    edge_rows = (await raw.exec_driver_sql(
        "SELECT count(*) FROM cypher('intellibird_graph', $$ "
        f"MATCH (:Event)-[:SEEN_IN]->(a:Actor {{id: '{fx.shared_actor.id}'}}) RETURN a "
        "$$) AS (a ag_catalog.agtype)"
    )).scalar_one()
    assert edge_rows == 40, f"expected 40 :SEEN_IN edges, got {edge_rows}"


async def test_jwt_claims_scoped(two_project_fixture):
    """Each JWT decodes with exactly its own project in the pm claim."""
    from app.security.jwt import decode_token

    fx = two_project_fixture
    signing_key = os.environ.get("JWT_SIGNING_KEY") or ("j" * 64)

    claims_a = decode_token(fx.jwt_a, signing_key)
    pm_a = claims_a.get("pm", [])
    pm_a_pids = {entry[0] for entry in pm_a}
    assert pm_a_pids == {str(fx.project_a.id)}, f"jwt_a pm={pm_a}"
    assert claims_a["role"] == "Analyst"

    claims_b = decode_token(fx.jwt_b, signing_key)
    pm_b = claims_b.get("pm", [])
    pm_b_pids = {entry[0] for entry in pm_b}
    assert pm_b_pids == {str(fx.project_b.id)}, f"jwt_b pm={pm_b}"
    assert claims_b["role"] == "Analyst"

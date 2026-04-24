"""Two-project fixture for PROD-01 cross-project leakage tests.

Creates Project A + Project B with events in BOTH projects referencing the SAME
shared Actor vertex and technique id in Apache AGE. Overlap is intentional so
that any leak (SQL filter missing, AGE BFS crossing project boundary) surfaces
as a detectable cross-project path.

AGE graph name: `intellibird_graph` (matches Phase 13 RESEARCH §Pattern 2).

Layout seeded per invocation:
  Postgres rows:
    - 2 `projects` rows (Project A, Project B)
    - 40 `events` rows (20 per project), all with technique tag 'T1566'
    - `attack_technique_tags` rows linking events to the shared technique
  AGE vertices/edges:
    - 1 `:Actor {id: <shared_actor_id>}` vertex
    - 40 `:Event {id, project_id}` vertices
    - 40 `:SEEN_IN` edges Event→Actor (20 per project)

JWTs:
  - jwt_a: role='Analyst', pm=[[project_a.id, PROJECT_ROLE_RANK['Contributor']]]
  - jwt_b: role='Analyst', pm=[[project_b.id, PROJECT_ROLE_RANK['Contributor']]]

Returned SimpleNamespace fields:
  project_a, project_b, jwt_a, jwt_b, shared_actor, shared_technique
"""
from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

AGE_GRAPH_NAME = "intellibird_graph"
SHARED_TECHNIQUE = "T1566"  # ATT&CK Phishing


async def _ensure_age_graph(session: AsyncSession) -> None:
    """Create the intellibird_graph graph idempotently, load AGE."""
    raw = await session.connection()
    await raw.exec_driver_sql("LOAD 'age'")
    await raw.exec_driver_sql('SET search_path = ag_catalog, "$user", public')
    row = (await raw.exec_driver_sql(
        f"SELECT 1 FROM ag_catalog.ag_graph WHERE name = '{AGE_GRAPH_NAME}'"
    )).first()
    if row is None:
        await raw.exec_driver_sql(f"SELECT create_graph('{AGE_GRAPH_NAME}')")


async def _create_project(session: AsyncSession, name: str, created_by: str) -> uuid.UUID:
    """INSERT a minimal project row, return its id."""
    pid = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO projects (id, name, engagement_type, created_by, archived) "
            "VALUES (:id, :name, 'internal', :cb, false)"
        ),
        {"id": pid, "name": name, "cb": created_by},
    )
    return pid


async def _seed_events(
    session: AsyncSession,
    project_id: uuid.UUID,
    n: int,
    technique: str,
    title_prefix: str,
) -> list[uuid.UUID]:
    """Insert n events for project_id, return their ids."""
    event_ids: list[uuid.UUID] = []
    base = datetime.now(timezone.utc) - timedelta(days=1)
    for i in range(n):
        eid = uuid.uuid4()
        event_ids.append(eid)
        observed_at = base + timedelta(seconds=i)
        content_hash = hashlib.sha256(f"{project_id}:{i}:{title_prefix}".encode()).hexdigest()
        await session.execute(
            text(
                "INSERT INTO events "
                "(id, stix_type, project_id, observed_at, title, content_hash, visibility) "
                "VALUES (:id, 'observed-data', :pid, :obs, :title, :ch, 'shared')"
            ),
            {
                "id": eid,
                "pid": project_id,
                "obs": observed_at,
                "title": f"{title_prefix}-{i}",
                "ch": content_hash,
            },
        )
        # Tag event with technique — schema from migration 001. No FK on event_id
        # (TimescaleDB hypertables can't be FK targets); tag_source NOT NULL.
        await session.execute(
            text(
                "INSERT INTO attack_technique_tags "
                "(event_id, technique_id, tag_source) "
                "VALUES (:eid, :tech, 'feed_asserted')"
            ),
            {"eid": eid, "tech": technique},
        )
    return event_ids


async def _seed_age_actor_and_edges(
    session: AsyncSession,
    shared_actor_id: str,
    events_by_project: dict[uuid.UUID, list[uuid.UUID]],
) -> None:
    """Create one :Actor vertex + per-event :Event vertex + :SEEN_IN edge Event->Actor.

    Uses raw driver SQL (exec_driver_sql) because SQLAlchemy `text()` parses
    `:name` as a bind parameter, which collides with Cypher's `:LabelName`
    and `[:REL_TYPE]` syntax.
    """
    await _ensure_age_graph(session)
    raw = await session.connection()

    def _cypher_sql(body: str) -> str:
        return (
            f"SELECT * FROM cypher('{AGE_GRAPH_NAME}', $$ {body} $$) "
            f"AS (n ag_catalog.agtype)"
        )

    # Actor vertex — id is a string UUID.
    await raw.exec_driver_sql(_cypher_sql(
        f"CREATE (a:Actor {{id: '{shared_actor_id}'}}) RETURN a"
    ))
    for project_id, event_ids in events_by_project.items():
        pid_str = str(project_id)
        for eid in event_ids:
            eid_str = str(eid)
            await raw.exec_driver_sql(_cypher_sql(
                f"MATCH (a:Actor {{id: '{shared_actor_id}'}}) "
                f"CREATE (e:Event {{id: '{eid_str}', project_id: '{pid_str}'}})"
                f"-[:SEEN_IN]->(a) RETURN e"
            ))


async def build_two_project_fixture(session: AsyncSession) -> SimpleNamespace:
    """Build + return the two-project namespace. Caller commits the session.

    Uses the provided async session (db_session from integration conftest) so
    rows/vertex writes are visible to subsequent queries in the same test.
    """
    from app.security.jwt import PROJECT_ROLE_RANK, mint_access_token_with_pm

    creator_sub = "two-project-fixture-creator"

    project_a_id = await _create_project(session, "Alpha", creator_sub)
    project_b_id = await _create_project(session, "Bravo", creator_sub)
    await session.flush()

    shared_actor_id = str(uuid.uuid4())

    events_a = await _seed_events(session, project_a_id, 20, SHARED_TECHNIQUE, "evt-a")
    events_b = await _seed_events(session, project_b_id, 20, SHARED_TECHNIQUE, "evt-b")

    await _seed_age_actor_and_edges(
        session,
        shared_actor_id,
        {project_a_id: events_a, project_b_id: events_b},
    )

    await session.commit()

    # JWT mint — role='Analyst', dashboard_roles=['red','blue'] so the Analyst can
    # hit intel routes; project_memberships scoped singularly.
    signing_key = os.environ.get("JWT_SIGNING_KEY") or os.environ.get("SECRET_KEY") or ("j" * 64)
    user_a_id = str(uuid.uuid4())
    user_b_id = str(uuid.uuid4())
    pm_a: list[list[Any]] = [[str(project_a_id), PROJECT_ROLE_RANK["Contributor"]]]
    pm_b: list[list[Any]] = [[str(project_b_id), PROJECT_ROLE_RANK["Contributor"]]]
    jwt_a, _ = mint_access_token_with_pm(
        user_a_id, "Analyst", ["red", "blue"], 0, signing_key, pm_a, False,
    )
    jwt_b, _ = mint_access_token_with_pm(
        user_b_id, "Analyst", ["red", "blue"], 0, signing_key, pm_b, False,
    )

    project_a = SimpleNamespace(id=project_a_id, name="Alpha")
    project_b = SimpleNamespace(id=project_b_id, name="Bravo")
    shared_actor = SimpleNamespace(id=shared_actor_id)

    return SimpleNamespace(
        project_a=project_a,
        project_b=project_b,
        jwt_a=jwt_a,
        jwt_b=jwt_b,
        shared_actor=shared_actor,
        shared_technique=SHARED_TECHNIQUE,
        events_a=events_a,
        events_b=events_b,
    )

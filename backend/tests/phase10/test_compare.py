"""PRJ-06 cross-project compare integration tests — Phase 10 / plan 10-14.

Covers:
  * test_shared_actors: actor name intersection across two projects
  * test_shared_techniques: ATT&CK technique-id intersection via tag JOIN
  * test_shared_iocs: IOC (ip/domain/hash) intersection via raw_stix pattern extraction
  * test_auth_both_sides: user with membership only on project A receives 403 on compare

Scope-row hygiene: each project must have at least one intel_scope=True keyword row;
otherwise build_scope_predicate returns sa.text('false') and all queries return empty.
"""
from __future__ import annotations

import uuid as _uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def client(db_engine, monkeypatch):
    """AsyncClient wired to the app with get_session overridden to test DB engine."""
    from app.config import settings
    from app.database import get_session
    from app.main import app
    import app.middleware.auth as auth_mod

    monkeypatch.setattr(settings, "AUTH_ENABLED", True, raising=False)

    async def _fake_tv(user_id: str):
        return 0

    async def _fake_revoked(jti: str) -> bool:
        return False

    monkeypatch.setattr(auth_mod, "_get_cached_token_version", _fake_tv)
    monkeypatch.setattr(auth_mod, "_is_jti_revoked", _fake_revoked)

    factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)

    async def _override_session():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _override_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)


async def _seed_project_with_keyword_scope(db_session, name: str) -> _uuid.UUID:
    """Seed a project + a keyword scope row (intel_scope=True) so build_scope_predicate
    returns a real predicate rather than sa.text('false')."""
    from app.models.projects import Project, ProjectScopeRow

    pid = _uuid.uuid4()
    project = Project(
        id=pid, name=name, engagement_type="red_team",
        description=f"Compare test {name}", created_by="system", archived=False,
    )
    db_session.add(project)
    await db_session.flush()

    scope_row = ProjectScopeRow(
        id=_uuid.uuid4(),
        project_id=pid,
        scope_type="keyword",
        value="apt",
        intel_scope=True,
        active_test_scope=False,
        exclude=False,
    )
    db_session.add(scope_row)
    await db_session.commit()
    return pid


async def _mint_lead_token_for_projects(db_session, user, project_ids: list[_uuid.UUID], jwt_settings):
    """Add Lead membership for user on each project_id, then mint a pm-token."""
    from app.models.projects import ProjectMembership
    from app.security.jwt import build_membership_claim, mint_access_token_with_pm

    for pid in project_ids:
        db_session.add(ProjectMembership(
            user_sub=str(user.id),
            project_id=pid,
            project_role="Lead",
            added_by="system",
        ))
    await db_session.commit()

    pm, truncated = await build_membership_claim(db_session, [str(user.id)])
    token, _ = mint_access_token_with_pm(
        str(user.id), user.role, user.dashboard_roles, user.token_version,
        jwt_settings, pm, truncated,
    )
    return token


async def test_shared_actors(client, db_session, users_matrix, jwt_settings) -> None:
    """Shared threat-actor names (lowercased) appear in compare response; unique-to-A actors are absent."""
    from app.models.events import Event

    pid_a = await _seed_project_with_keyword_scope(db_session, "Actor Proj A")
    pid_b = await _seed_project_with_keyword_scope(db_session, "Actor Proj B")

    user = users_matrix["project_lead_user"]
    token = await _mint_lead_token_for_projects(db_session, user, [pid_a, pid_b], jwt_settings)

    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)

    # APT28 appears in BOTH projects -> shared
    for pid in (pid_a, pid_b):
        db_session.add(Event(
            id=_uuid.uuid4(),
            observed_at=now,
            stix_type="threat-actor",
            title="apt apt28 activity",
            raw_stix={"name": "APT28", "type": "threat-actor"},
            project_id=pid,
        ))
    # APT99 only in project A -> NOT shared
    db_session.add(Event(
        id=_uuid.uuid4(),
        observed_at=now,
        stix_type="threat-actor",
        title="apt apt99 unique",
        raw_stix={"name": "APT99", "type": "threat-actor"},
        project_id=pid_a,
    ))
    await db_session.commit()

    resp = await client.get(
        f"/api/projects/compare?a={pid_a}&b={pid_b}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "apt28" in data["shared_actors"], f"expected apt28 in {data['shared_actors']}"
    assert "apt99" not in data["shared_actors"], f"apt99 should not be shared"


async def test_shared_techniques(client, db_session, users_matrix, jwt_settings) -> None:
    """ATT&CK technique in both projects appears; technique only in A is absent."""
    from app.models.events import Event
    from app.models.tags import AttackTechniqueTag

    pid_a = await _seed_project_with_keyword_scope(db_session, "Tech Proj A")
    pid_b = await _seed_project_with_keyword_scope(db_session, "Tech Proj B")

    user = users_matrix["project_lead_user"]
    token = await _mint_lead_token_for_projects(db_session, user, [pid_a, pid_b], jwt_settings)

    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)

    # T1059 in both projects
    event_a = Event(
        id=_uuid.uuid4(), observed_at=now, stix_type="attack-pattern",
        title="apt t1059 execution", raw_stix={}, project_id=pid_a,
    )
    event_b = Event(
        id=_uuid.uuid4(), observed_at=now, stix_type="attack-pattern",
        title="apt t1059 execution", raw_stix={}, project_id=pid_b,
    )
    # T1566 only in project A
    event_a2 = Event(
        id=_uuid.uuid4(), observed_at=now, stix_type="attack-pattern",
        title="apt phishing t1566", raw_stix={}, project_id=pid_a,
    )
    db_session.add_all([event_a, event_b, event_a2])
    await db_session.flush()

    db_session.add(AttackTechniqueTag(event_id=event_a.id, technique_id="T1059"))
    db_session.add(AttackTechniqueTag(event_id=event_b.id, technique_id="T1059"))
    db_session.add(AttackTechniqueTag(event_id=event_a2.id, technique_id="T1566"))
    await db_session.commit()

    resp = await client.get(
        f"/api/projects/compare?a={pid_a}&b={pid_b}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "T1059" in data["shared_techniques"], f"T1059 missing: {data['shared_techniques']}"
    assert "T1566" not in data["shared_techniques"], f"T1566 should not be shared"


async def test_shared_iocs(client, db_session, users_matrix, jwt_settings) -> None:
    """IP IOC shared by both projects appears; IP only in A is absent."""
    from app.models.events import Event

    pid_a = await _seed_project_with_keyword_scope(db_session, "IOC Proj A")
    pid_b = await _seed_project_with_keyword_scope(db_session, "IOC Proj B")

    user = users_matrix["project_lead_user"]
    token = await _mint_lead_token_for_projects(db_session, user, [pid_a, pid_b], jwt_settings)

    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)

    # 10.0.0.1 in both -> shared
    for pid in (pid_a, pid_b):
        db_session.add(Event(
            id=_uuid.uuid4(),
            observed_at=now,
            stix_type="indicator",
            title="apt indicator shared ip",
            raw_stix={
                "type": "indicator",
                "pattern": "[ipv4-addr:value = '10.0.0.1']",
            },
            project_id=pid,
        ))
    # 8.8.8.8 only in A -> NOT shared
    db_session.add(Event(
        id=_uuid.uuid4(),
        observed_at=now,
        stix_type="indicator",
        title="apt indicator unique ip",
        raw_stix={
            "type": "indicator",
            "pattern": "[ipv4-addr:value = '8.8.8.8']",
        },
        project_id=pid_a,
    ))
    await db_session.commit()

    resp = await client.get(
        f"/api/projects/compare?a={pid_a}&b={pid_b}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    ioc_values = [i["value"] for i in data["shared_iocs"]]
    assert "10.0.0.1" in ioc_values, f"10.0.0.1 missing: {ioc_values}"
    assert "8.8.8.8" not in ioc_values, f"8.8.8.8 should not be shared"


async def test_auth_both_sides(client, db_session, users_matrix, jwt_settings) -> None:
    """User with membership on A only receives 403 when comparing A vs B."""
    pid_a = await _seed_project_with_keyword_scope(db_session, "Auth Proj A")
    pid_b = await _seed_project_with_keyword_scope(db_session, "Auth Proj B")

    # Mint token with membership on A only (not B)
    user = users_matrix["project_lead_user"]
    token = await _mint_lead_token_for_projects(db_session, user, [pid_a], jwt_settings)

    resp = await client.get(
        f"/api/projects/compare?a={pid_a}&b={pid_b}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, f"expected 403, got {resp.status_code}: {resp.text}"

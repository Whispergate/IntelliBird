"""PRJ-07 per-project export integration tests — plan 10-14.

Covers:
  * test_stix_bundle_parseable: STIX 2.1 bundle is parseable; Identity "IntelliBird" + Note present
  * test_csv_columns: CSV header matches locked CSV_COLUMNS set exactly
  * test_size_cap_413: monkeypatching STIX_BUNDLE_EVENT_CAP to 0 triggers 413
  * test_observer_cannot_export: Observer role receives 403 (Contributor+ required)

Scope-row hygiene: project must have at least one intel_scope=True keyword row.
Observer test uses a fresh Viewer-global user with only Observer project membership
so Admin bypass does not fire.
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


async def _seed_project_with_events(db_session, name: str, n_events: int = 2) -> _uuid.UUID:
    """Seed a project, keyword scope row (intel_scope=True), and n events."""
    from app.models.events import Event
    from app.models.projects import Project, ProjectScopeRow

    pid = _uuid.uuid4()
    project = Project(
        id=pid, name=name, engagement_type="red_team",
        description=f"Export test {name}", created_by="system", archived=False,
    )
    db_session.add(project)
    await db_session.flush()

    db_session.add(ProjectScopeRow(
        id=_uuid.uuid4(),
        project_id=pid,
        scope_type="keyword",
        value="apt",
        intel_scope=True,
        active_test_scope=False,
        exclude=False,
    ))
    await db_session.flush()

    import datetime as dt

    now = dt.datetime.now(dt.timezone.utc)
    for i in range(n_events):
        db_session.add(Event(
            id=_uuid.uuid4(),
            observed_at=now,
            stix_type="indicator",
            title=f"apt event {i}",
            raw_stix={
                "type": "indicator",
                "id": f"indicator--{_uuid.uuid4()}",
                "spec_version": "2.1",
                "pattern": f"[ipv4-addr:value = '10.0.{i}.1']",
                "pattern_type": "stix",
                "valid_from": now.isoformat(),
            },
            project_id=pid,
        ))
    await db_session.commit()
    return pid


async def _mint_contributor_token(db_session, user, project_id: _uuid.UUID, jwt_settings):
    """Add Contributor membership for user on project_id and mint a pm-token."""
    from app.models.projects import ProjectMembership
    from app.security.jwt import build_membership_claim, mint_access_token_with_pm

    db_session.add(ProjectMembership(
        user_sub=str(user.id),
        project_id=project_id,
        project_role="Contributor",
        added_by="system",
    ))
    await db_session.commit()

    pm, truncated = await build_membership_claim(db_session, [str(user.id)])
    token, _ = mint_access_token_with_pm(
        str(user.id), user.role, user.dashboard_roles, user.token_version,
        jwt_settings, pm, truncated,
    )
    return token


async def test_stix_bundle_parseable(client, db_session, users_matrix, jwt_settings) -> None:
    """POST export?format=stix returns parseable STIX 2.1 Bundle with expected objects."""
    import stix2

    pid = await _seed_project_with_events(db_session, "STIX Export Project", n_events=2)
    user = users_matrix["project_contributor_user"]
    token = await _mint_contributor_token(db_session, user, pid, jwt_settings)

    resp = await client.post(
        f"/api/projects/{pid}/export?format=stix",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert "application/json" in resp.headers["content-type"]
    assert "intellibird-project-" in resp.headers["content-disposition"]

    bundle = stix2.parse(resp.content, allow_custom=True)
    names = [getattr(o, "name", None) for o in bundle.objects]
    assert "IntelliBird" in names, f"Identity 'IntelliBird' missing from bundle: {names}"

    notes = [o for o in bundle.objects if o.type == "note"]
    assert notes, "No Note SDO in bundle"
    assert any(
        getattr(n, "x_intellibird_project", {}).get("id") == str(pid)
        for n in notes
    ), f"No Note with x_intellibird_project.id=={pid}"


async def test_csv_columns(client, db_session, users_matrix, jwt_settings) -> None:
    """POST export?format=csv returns CSV whose first line matches locked CSV_COLUMNS."""
    from app.services.project_export import CSV_COLUMNS

    pid = await _seed_project_with_events(db_session, "CSV Export Project", n_events=1)
    user = users_matrix["project_contributor_user"]
    token = await _mint_contributor_token(db_session, user, pid, jwt_settings)

    resp = await client.post(
        f"/api/projects/{pid}/export?format=csv",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert "text/csv" in resp.headers["content-type"]

    first_line = resp.content.decode("utf-8").split("\n", 1)[0].rstrip("\r")
    assert first_line == ",".join(CSV_COLUMNS), (
        f"CSV header mismatch.\nExpected: {','.join(CSV_COLUMNS)}\nGot:      {first_line}"
    )


async def test_size_cap_413(client, db_session, users_matrix, jwt_settings, monkeypatch) -> None:
    """Setting STIX_BUNDLE_EVENT_CAP=0 via monkeypatch triggers 413."""
    from app.services import project_export

    monkeypatch.setattr(project_export, "STIX_BUNDLE_EVENT_CAP", 0)

    pid = await _seed_project_with_events(db_session, "Cap Test Project", n_events=1)
    user = users_matrix["project_contributor_user"]
    token = await _mint_contributor_token(db_session, user, pid, jwt_settings)

    resp = await client.post(
        f"/api/projects/{pid}/export?format=stix",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 413, f"expected 413, got {resp.status_code}: {resp.text}"
    detail = resp.json()["detail"].lower()
    assert "narrow" in detail or "cap" in detail, f"detail should mention cap or narrow: {detail}"


async def test_observer_cannot_export(client, db_session, users_matrix, jwt_settings) -> None:
    """Observer role (non-Admin global role) receives 403 on export (Contributor+ required)."""
    from app.models.projects import ProjectMembership
    from app.security.jwt import build_membership_claim, mint_access_token_with_pm

    pid = await _seed_project_with_events(db_session, "Observer Export Project", n_events=1)

    # Use the project_observer_user (global role = Viewer, not Admin — no bypass)
    observer = users_matrix["project_observer_user"]

    db_session.add(ProjectMembership(
        user_sub=str(observer.id),
        project_id=pid,
        project_role="Observer",
        added_by="system",
    ))
    await db_session.commit()

    pm, truncated = await build_membership_claim(db_session, [str(observer.id)])
    obs_token, _ = mint_access_token_with_pm(
        str(observer.id), observer.role, observer.dashboard_roles, observer.token_version,
        jwt_settings, pm, truncated,
    )

    resp = await client.post(
        f"/api/projects/{pid}/export?format=stix",
        headers={"Authorization": f"Bearer {obs_token}"},
    )
    assert resp.status_code == 403, f"expected 403, got {resp.status_code}: {resp.text}"

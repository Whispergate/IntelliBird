"""IOC-03 / IOC-08 search and pivot integration tests.

Implemented by Plan 22-03 Task 2.

Covers:
  * GET /api/iocs?type=ip                - list filter by type
  * GET /api/iocs/{id}/events            - IOC → events pivot
  * GET /api/events/{event_id}/iocs      - event → IOCs pivot (Surface 5)
  * Substring search on `q` against value/normalized_value
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.security.jwt import PROJECT_ROLE_RANK, mint_access_token_with_pm

pytestmark = pytest.mark.integration

TEST_SIGNING_KEY = "j" * 64


def _patch_auth(monkeypatch) -> None:
    import app.middleware.auth as auth_mod
    from app.config import settings

    monkeypatch.setattr(settings, "AUTH_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "JWT_SIGNING_KEY", TEST_SIGNING_KEY, raising=False)

    async def _tv(_user_id: str):
        return 0

    async def _not_revoked(_jti: str) -> bool:
        return False

    monkeypatch.setattr(auth_mod, "_get_cached_token_version", _tv)
    monkeypatch.setattr(auth_mod, "_is_jti_revoked", _not_revoked)


async def _client():
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
async def _truncate_iocs(db_session):
    """Per-test truncate of iocs + ioc_event_links - these tables aren't yet in
    the shared conftest._TRUNCATE_TABLES list; documented as a Plan 22-02
    follow-up. Local fixture keeps the change scoped to this file.
    """
    await db_session.execute(text("TRUNCATE TABLE ioc_event_links, iocs RESTART IDENTITY CASCADE"))
    await db_session.commit()
    yield


async def _seed_lead_jwt(db_session, project_name: str = "search-proj") -> tuple[uuid.UUID, str]:
    """Create a project + Lead JWT for it. Returns (project_id, jwt)."""
    pid = uuid.uuid4()
    user_id = str(uuid.uuid4())
    await db_session.execute(
        text(
            "INSERT INTO projects (id, name, engagement_type, created_by, archived) "
            "VALUES (:id, :name, 'internal', :cb, false)"
        ),
        {"id": pid, "name": project_name, "cb": user_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO users (id, username, role) VALUES (:id, :u, 'Analyst') "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": user_id, "u": f"user-{project_name}"},
    )
    await db_session.commit()
    pm = [[str(pid), PROJECT_ROLE_RANK["Lead"]]]
    jwt, _ = mint_access_token_with_pm(
        user_id, "Analyst", ["red", "blue"], 0, TEST_SIGNING_KEY, pm, False,
    )
    return pid, jwt


async def _insert_ioc(db_session, project_id, ioc_type: str, value: str, status: str = "active"):
    iid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    await db_session.execute(
        text(
            "INSERT INTO iocs "
            "(id, project_id, type, value, normalized_value, status, confidence, "
            " ttl_days, source, first_seen, last_seen, created_at, updated_at) "
            "VALUES (:id, :pid, :t, :v, :nv, :st, 0.85, 30, 'manual', :now, :now, :now, :now)"
        ),
        {
            "id": iid, "pid": project_id, "t": ioc_type,
            "v": value, "nv": value.lower(), "st": status, "now": now,
        },
    )
    return iid


async def _insert_event(db_session, project_id, title: str = "test event") -> uuid.UUID:
    eid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    import hashlib
    ch = hashlib.sha256(f"{eid}".encode()).hexdigest()
    await db_session.execute(
        text(
            "INSERT INTO events "
            "(id, stix_type, project_id, observed_at, title, content_hash, visibility) "
            "VALUES (:id, 'observed-data', :pid, :obs, :t, :ch, 'shared')"
        ),
        {"id": eid, "pid": project_id, "obs": now, "t": title, "ch": ch},
    )
    return eid


async def _link_ioc_event(db_session, ioc_id, event_id):
    now = datetime.now(timezone.utc)
    await db_session.execute(
        text(
            "INSERT INTO ioc_event_links (id, ioc_id, event_id, observed_at, source_field) "
            "VALUES (:id, :ioc, :evt, :now, 'description')"
        ),
        {"id": uuid.uuid4(), "ioc": ioc_id, "evt": event_id, "now": now},
    )


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_search_returns_linked_events_via_m2m(db_session, monkeypatch):
    """End-to-end: insert project + event + IOC + link, hit all three pivot
    endpoints and assert each surfaces the seeded relationship.
    """
    _patch_auth(monkeypatch)
    project_id, jwt = await _seed_lead_jwt(db_session, "alpha")

    ioc_id = await _insert_ioc(db_session, project_id, "ip", "1.2.3.4")
    event_id = await _insert_event(db_session, project_id, "incident: 1.2.3.4 phoning home")
    await _link_ioc_event(db_session, ioc_id, event_id)
    await db_session.commit()

    async with await _client() as c:
        # 1. List filter by type - single match.
        r = await c.get(
            "/api/iocs",
            headers=_bearer(jwt),
            params={"type": "ip"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        ids = {row["id"] for row in body}
        assert str(ioc_id) in ids, f"GET /api/iocs missed seeded ioc: {body}"

        # 2. Substring search via q on value.
        r2 = await c.get(
            "/api/iocs",
            headers=_bearer(jwt),
            params={"q": "1.2.3"},
        )
        assert r2.status_code == 200, r2.text
        assert any(row["id"] == str(ioc_id) for row in r2.json())

        # 3. IOC → events pivot.
        r3 = await c.get(
            f"/api/iocs/{ioc_id}/events",
            headers=_bearer(jwt),
        )
        assert r3.status_code == 200, r3.text
        evt_rows = r3.json()
        assert any(row["id"] == str(event_id) for row in evt_rows), (
            f"GET /api/iocs/{{id}}/events missed seeded event: {evt_rows}"
        )

        # 4. Event → IOCs pivot (Surface 5).
        r4 = await c.get(
            f"/api/events/{event_id}/iocs",
            headers=_bearer(jwt),
        )
        assert r4.status_code == 200, r4.text
        ioc_rows = r4.json()
        assert any(row["id"] == str(ioc_id) for row in ioc_rows), (
            f"GET /api/events/{{id}}/iocs missed seeded IOC: {ioc_rows}"
        )


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_default_query_hides_expired_unless_opt_in(db_session, monkeypatch):
    """IOC-05: default `?include_expired=false` hides expired rows; passing
    true surfaces them.
    """
    _patch_auth(monkeypatch)
    project_id, jwt = await _seed_lead_jwt(db_session, "expiry-proj")

    active_id = await _insert_ioc(db_session, project_id, "domain", "active.example", status="active")
    expired_id = await _insert_ioc(db_session, project_id, "domain", "stale.example", status="expired")
    await db_session.commit()

    async with await _client() as c:
        # Default - expired hidden.
        r = await c.get("/api/iocs", headers=_bearer(jwt), params={"type": "domain"})
        assert r.status_code == 200, r.text
        ids = {row["id"] for row in r.json()}
        assert str(active_id) in ids
        assert str(expired_id) not in ids

        # include_expired=true - both surface.
        r2 = await c.get(
            "/api/iocs",
            headers=_bearer(jwt),
            params={"type": "domain", "include_expired": "true"},
        )
        assert r2.status_code == 200, r2.text
        ids2 = {row["id"] for row in r2.json()}
        assert str(active_id) in ids2
        assert str(expired_id) in ids2


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_get_ioc_404_when_out_of_scope(db_session, monkeypatch):
    """GET /api/iocs/{id} returns 404 (not 403) when the row is not visible -
    avoids an enumerable side channel.
    """
    _patch_auth(monkeypatch)
    project_a, jwt_a = await _seed_lead_jwt(db_session, "scope-a")
    project_b, _ = await _seed_lead_jwt(db_session, "scope-b")

    secret_id = await _insert_ioc(db_session, project_b, "ip", "9.9.9.9")
    await db_session.commit()

    async with await _client() as c:
        r = await c.get(f"/api/iocs/{secret_id}", headers=_bearer(jwt_a))
        assert r.status_code == 404, (
            f"Expected 404 for cross-project IOC GET, got {r.status_code}: {r.text}"
        )

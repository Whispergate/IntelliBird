"""IOC-04 whitelist + clone-on-whitelist + PATCH + DELETE - Plan 22-04 Task 3.

Covers:
  * Lead can whitelist a per-project IOC in place
  * Admin can whitelist a global IOC in place (no clone)
  * Non-admin Lead whitelisting a global IOC clones it into the Lead's project
  * Missing project_id on the clone path returns 400
  * Observer 403
  * Default GET /api/iocs?status=active hides whitelisted rows
  * Lead can PATCH confidence + ttl_days; Observer 403
  * Admin can DELETE; Lead 403
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

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


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
async def _truncate_iocs(db_session):
    await db_session.execute(
        text("TRUNCATE TABLE ioc_event_links, iocs RESTART IDENTITY CASCADE")
    )
    await db_session.commit()
    yield


async def _seed_project(db_session, name: str) -> tuple[uuid.UUID, str]:
    pid = uuid.uuid4()
    user_id = str(uuid.uuid4())
    await db_session.execute(
        text(
            "INSERT INTO projects (id, name, engagement_type, created_by, archived) "
            "VALUES (:id, :n, 'internal', :cb, false)"
        ),
        {"id": pid, "n": name, "cb": user_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO users (id, username, role) VALUES (:id, :u, 'Analyst') "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": user_id, "u": f"u-{name}"},
    )
    await db_session.commit()
    return pid, user_id


def _mint(user_id: str, role: str, pm: list[list]) -> str:
    jwt, _ = mint_access_token_with_pm(
        user_id, role, ["red", "blue"], 0, TEST_SIGNING_KEY, pm, False,
    )
    return jwt


async def _seed_admin(db_session) -> str:
    user_id = str(uuid.uuid4())
    await db_session.execute(
        text(
            "INSERT INTO users (id, username, role) VALUES (:id, :u, 'Admin') "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": user_id, "u": f"admin-{user_id[:8]}"},
    )
    await db_session.commit()
    return _mint(user_id, "Admin", [])


async def _insert_ioc(
    db_session, project_id, ioc_type: str, value: str, status: str = "active",
    confidence: float = 0.7, ttl_days: int = 30,
) -> uuid.UUID:
    iid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    await db_session.execute(
        text(
            "INSERT INTO iocs "
            "(id, project_id, type, value, normalized_value, status, confidence, "
            " ttl_days, source, first_seen, last_seen, created_at, updated_at) "
            "VALUES (:id, :pid, :t, :v, :nv, :st, :c, :ttl, 'manual', "
            ":ts, :ts, :ts, :ts)"
        ),
        {
            "id": iid, "pid": project_id, "t": ioc_type,
            "v": value, "nv": value.lower(), "st": status,
            "c": confidence, "ttl": ttl_days, "ts": now,
        },
    )
    return iid


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_lead_can_whitelist_per_project_in_place(db_session, monkeypatch):
    _patch_auth(monkeypatch)
    project_id, user_id = await _seed_project(db_session, "wl-lead-1")
    iid = await _insert_ioc(db_session, project_id, "ip", "1.2.3.4")
    await db_session.commit()
    jwt = _mint(user_id, "Analyst", [[str(project_id), PROJECT_ROLE_RANK["Lead"]]])

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/iocs/{iid}/whitelist", headers=_bearer(jwt))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "whitelisted"
        assert body["project_id"] == str(project_id)


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_admin_can_whitelist_global_in_place(db_session, monkeypatch):
    _patch_auth(monkeypatch)
    iid = await _insert_ioc(db_session, None, "domain", "evil.example")
    await db_session.commit()
    admin_jwt = await _seed_admin(db_session)

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/iocs/{iid}/whitelist", headers=_bearer(admin_jwt))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "whitelisted"
        assert body["project_id"] is None
        assert body["id"] == str(iid)


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_lead_clones_global_to_project_on_whitelist(db_session, monkeypatch):
    """Non-admin Lead whitelisting a global IOC clones it into a per-project
    shadow row; the global row is unchanged.
    """
    _patch_auth(monkeypatch)
    project_id, user_id = await _seed_project(db_session, "clone-target")
    global_id = await _insert_ioc(db_session, None, "domain", "noisy.example")
    await db_session.commit()
    jwt = _mint(user_id, "Analyst", [[str(project_id), PROJECT_ROLE_RANK["Lead"]]])

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"/api/iocs/{global_id}/whitelist",
            headers=_bearer(jwt),
            params={"project_id": str(project_id)},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["project_id"] == str(project_id), "clone must be project-scoped"
        assert body["status"] == "whitelisted"
        assert body["id"] != str(global_id), "clone must be a NEW row"

    # Original global row is unchanged.
    g_status, g_pid = (
        await db_session.execute(
            text("SELECT status, project_id FROM iocs WHERE id = :id"),
            {"id": global_id},
        )
    ).one()
    assert g_status == "active"
    assert g_pid is None


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_lead_clone_without_project_id_400(db_session, monkeypatch):
    _patch_auth(monkeypatch)
    project_id, user_id = await _seed_project(db_session, "clone-noprj")
    global_id = await _insert_ioc(db_session, None, "domain", "needs-target.example")
    await db_session.commit()
    jwt = _mint(user_id, "Analyst", [[str(project_id), PROJECT_ROLE_RANK["Lead"]]])

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/iocs/{global_id}/whitelist", headers=_bearer(jwt))
        assert r.status_code == 400, r.text


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_observer_gets_403(db_session, monkeypatch):
    _patch_auth(monkeypatch)
    project_id, user_id = await _seed_project(db_session, "wl-obs")
    iid = await _insert_ioc(db_session, project_id, "ip", "10.0.0.1")
    await db_session.commit()
    jwt = _mint(user_id, "Analyst", [[str(project_id), PROJECT_ROLE_RANK["Observer"]]])

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/iocs/{iid}/whitelist", headers=_bearer(jwt))
        assert r.status_code == 403, r.text


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_default_query_hides_whitelisted(db_session, monkeypatch):
    """`GET /api/iocs?status=active` does not return whitelisted rows;
    `?status=whitelisted` does.
    """
    _patch_auth(monkeypatch)
    project_id, user_id = await _seed_project(db_session, "hide-wl")
    iid = await _insert_ioc(db_session, project_id, "ip", "9.9.9.9", status="whitelisted")
    await db_session.commit()
    jwt = _mint(user_id, "Analyst", [[str(project_id), PROJECT_ROLE_RANK["Lead"]]])

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/iocs", headers=_bearer(jwt), params={"status": "active"})
        assert r.status_code == 200, r.text
        ids = {row["id"] for row in r.json()}
        assert str(iid) not in ids

        r2 = await c.get(
            "/api/iocs", headers=_bearer(jwt), params={"status": "whitelisted"}
        )
        assert r2.status_code == 200, r2.text
        ids2 = {row["id"] for row in r2.json()}
        assert str(iid) in ids2


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_lead_can_patch_confidence_and_ttl(db_session, monkeypatch):
    _patch_auth(monkeypatch)
    project_id, user_id = await _seed_project(db_session, "patch-lead")
    iid = await _insert_ioc(
        db_session, project_id, "ip", "1.1.1.1", confidence=0.5, ttl_days=10
    )
    await db_session.commit()
    jwt = _mint(user_id, "Analyst", [[str(project_id), PROJECT_ROLE_RANK["Lead"]]])

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.patch(
            f"/api/iocs/{iid}",
            headers=_bearer(jwt),
            json={"confidence": "0.85", "ttl_days": 60},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert Decimal(body["confidence"]) == Decimal("0.85")
        assert body["ttl_days"] == 60


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_observer_patch_403(db_session, monkeypatch):
    _patch_auth(monkeypatch)
    project_id, user_id = await _seed_project(db_session, "patch-obs")
    iid = await _insert_ioc(db_session, project_id, "ip", "2.2.2.2")
    await db_session.commit()
    jwt = _mint(user_id, "Analyst", [[str(project_id), PROJECT_ROLE_RANK["Observer"]]])

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.patch(
            f"/api/iocs/{iid}", headers=_bearer(jwt), json={"confidence": "0.9"}
        )
        assert r.status_code == 403, r.text


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_admin_can_delete_ioc(db_session, monkeypatch):
    _patch_auth(monkeypatch)
    project_id, _ = await _seed_project(db_session, "del-prj")
    iid = await _insert_ioc(db_session, project_id, "ip", "3.3.3.3")
    # Add a link row to verify cascade.
    await db_session.execute(
        text(
            "INSERT INTO ioc_event_links (id, ioc_id, event_id, observed_at, source_field) "
            "VALUES (:id, :iid, :eid, NOW(), 'test')"
        ),
        {"id": uuid.uuid4(), "iid": iid, "eid": uuid.uuid4()},
    )
    await db_session.commit()

    admin_jwt = await _seed_admin(db_session)
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.delete(f"/api/iocs/{iid}", headers=_bearer(admin_jwt))
        assert r.status_code == 204, r.text

    remaining = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM iocs WHERE id = :id"), {"id": iid}
        )
    ).scalar_one()
    assert remaining == 0
    link_remaining = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM ioc_event_links WHERE ioc_id = :id"),
            {"id": iid},
        )
    ).scalar_one()
    assert link_remaining == 0, "ioc_event_links must cascade on hard delete"


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_lead_delete_403(db_session, monkeypatch):
    _patch_auth(monkeypatch)
    project_id, user_id = await _seed_project(db_session, "del-lead")
    iid = await _insert_ioc(db_session, project_id, "ip", "4.4.4.4")
    await db_session.commit()
    jwt = _mint(user_id, "Analyst", [[str(project_id), PROJECT_ROLE_RANK["Lead"]]])

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.delete(f"/api/iocs/{iid}", headers=_bearer(jwt))
        assert r.status_code == 403, r.text

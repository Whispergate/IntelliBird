"""IOC-05 daily expiry scheduler integration tests - Plan 22-04 Task 2.

Covers:
  * `expire_iocs(session)` flips active → expired when last_seen + ttl exceeded.
  * `?include_expired=true` surfaces expired rows; default query hides them.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

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


@pytest.fixture(autouse=True)
async def _truncate_iocs(db_session):
    await db_session.execute(
        text("TRUNCATE TABLE ioc_event_links, iocs RESTART IDENTITY CASCADE")
    )
    await db_session.commit()
    yield


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_scheduler_flips_active_to_expired(db_session):
    """`expire_iocs` flips a stale active IOC to status='expired'."""
    from app.services.iocs import expire_iocs

    project_id = uuid.uuid4()
    one_year_ago = datetime.now(timezone.utc) - timedelta(days=365)

    await db_session.execute(
        text(
            "INSERT INTO projects (id, name, engagement_type, created_by, archived) "
            "VALUES (:pid, :n, 'internal', :cb, false) ON CONFLICT (id) DO NOTHING"
        ),
        {"pid": project_id, "n": f"expiry-{project_id.hex[:8]}", "cb": str(uuid.uuid4())},
    )
    await db_session.commit()
    iid = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO iocs "
            "(id, project_id, type, value, normalized_value, status, confidence, "
            " ttl_days, source, first_seen, last_seen, created_at, updated_at) "
            "VALUES (:id, :pid, 'ip', '198.51.100.1', '198.51.100.1', 'active', "
            "0.7, 30, 'manual', :ts, :ts, :ts, :ts)"
        ),
        {"id": iid, "pid": project_id, "ts": one_year_ago},
    )
    await db_session.commit()

    expired_count = await expire_iocs(db_session)
    assert expired_count >= 1, "expire_iocs should have flipped at least one row"

    status = (
        await db_session.execute(
            text("SELECT status FROM iocs WHERE id = :id"), {"id": iid}
        )
    ).scalar_one()
    assert status == "expired"


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_include_expired_query_param_surfaces_them(db_session, monkeypatch):
    """Default GET /api/iocs hides status='expired'; include_expired=true shows them."""
    _patch_auth(monkeypatch)

    project_id = uuid.uuid4()
    user_id = str(uuid.uuid4())
    await db_session.execute(
        text(
            "INSERT INTO projects (id, name, engagement_type, created_by, archived) "
            "VALUES (:pid, :n, 'internal', :cb, false)"
        ),
        {"pid": project_id, "n": f"expiry-list-{project_id.hex[:8]}", "cb": user_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO users (id, username, role) VALUES (:id, :u, 'Analyst') "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": user_id, "u": f"u-{user_id[:8]}"},
    )
    iid_active = uuid.uuid4()
    iid_expired = uuid.uuid4()
    now = datetime.now(timezone.utc)
    for iid, st in [(iid_active, "active"), (iid_expired, "expired")]:
        await db_session.execute(
            text(
                "INSERT INTO iocs "
                "(id, project_id, type, value, normalized_value, status, confidence, "
                " ttl_days, source, first_seen, last_seen, created_at, updated_at) "
                "VALUES (:id, :pid, 'domain', :v, :v, :s, 0.8, 180, 'manual', "
                ":ts, :ts, :ts, :ts)"
            ),
            {"id": iid, "pid": project_id, "v": f"{st}.example", "s": st, "ts": now},
        )
    await db_session.commit()

    pm = [[str(project_id), PROJECT_ROLE_RANK["Lead"]]]
    jwt, _ = mint_access_token_with_pm(
        user_id, "Analyst", ["red", "blue"], 0, TEST_SIGNING_KEY, pm, False,
    )
    headers = {"Authorization": f"Bearer {jwt}"}

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/iocs", headers=headers, params={"type": "domain"})
        assert r.status_code == 200, r.text
        ids = {row["id"] for row in r.json()}
        assert str(iid_active) in ids
        assert str(iid_expired) not in ids, "default query must hide expired"

        r2 = await c.get(
            "/api/iocs",
            headers=headers,
            params={"type": "domain", "include_expired": "true"},
        )
        assert r2.status_code == 200, r2.text
        ids2 = {row["id"] for row in r2.json()}
        assert str(iid_expired) in ids2, "include_expired=true must surface expired"

"""IOC-02 bulk-import endpoint integration tests - Plan 22-05 Task 3.

Covers:
  * dry_run=true returns counts without writing anything
  * Real run returns 202 + job_id + Redis status key
  * 10_001-row CSV → 413
  * Dry-run dedup is project-scoped (revision checker fix #9 - no cross-project
    info disclosure; mirrors PROD-01 leakage shape)
  * CSV row.project_id ≠ route project_id (non-admin) → 422 row_project_id_mismatch
    (revision checker fix #4)
  * Admin upload with project_id='global' is accepted
"""
from __future__ import annotations

import json
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


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _mint(user_id: str, role: str, pm: list[list]) -> str:
    jwt, _ = mint_access_token_with_pm(
        user_id, role, ["red", "blue"], 0, TEST_SIGNING_KEY, pm, False,
    )
    return jwt


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


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_dry_run_returns_counts_without_writing(db_session, monkeypatch):
    _patch_auth(monkeypatch)
    project_id, user_id = await _seed_project(db_session, "dryrun-1")
    jwt = _mint(user_id, "Analyst", [[str(project_id), PROJECT_ROLE_RANK["Lead"]]])

    csv_blob = b"type,value\nip,1.2.3.4\nip,5.6.7.8\ndomain,evil.example\n"
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/iocs/bulk-import",
            headers={**_bearer(jwt), "Content-Type": "text/csv"},
            params={"dry_run": "true", "project_id": str(project_id)},
            content=csv_blob,
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["would_insert"] == 3
    assert body["would_update"] == 0
    assert body["would_skip"] == 0

    cnt = (
        await db_session.execute(text("SELECT COUNT(*) FROM iocs"))
    ).scalar_one()
    assert cnt == 0, "dry_run must not write"


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_real_run_returns_job_id(db_session, monkeypatch):
    _patch_auth(monkeypatch)
    project_id, user_id = await _seed_project(db_session, "realrun-1")
    jwt = _mint(user_id, "Analyst", [[str(project_id), PROJECT_ROLE_RANK["Lead"]]])

    csv_blob = b"type,value\nip,1.2.3.4\n"
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/iocs/bulk-import",
            headers={**_bearer(jwt), "Content-Type": "text/csv"},
            params={"project_id": str(project_id)},
            content=csv_blob,
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "job_id" in body and body["rows_accepted"] == 1

    # Redis status key was staged.
    from app.services.redis_client import get_redis
    redis = await get_redis()
    blob = await redis.get(f"job:{body['job_id']}:status")
    assert blob is not None
    status = json.loads(blob)
    assert status["status"] in ("queued", "running", "complete")
    assert status["total"] == 1


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_row_cap_returns_413(db_session, monkeypatch):
    _patch_auth(monkeypatch)
    project_id, user_id = await _seed_project(db_session, "rowcap")
    jwt = _mint(user_id, "Analyst", [[str(project_id), PROJECT_ROLE_RANK["Lead"]]])

    # 10_001 rows past the cap (10_000) - the parser raises IOCImportTooLarge.
    body_lines = ["type,value"]
    for i in range(10_001):
        body_lines.append(f"ip,10.0.{(i // 256) % 256}.{i % 256}")
    csv_blob = ("\n".join(body_lines) + "\n").encode()

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/iocs/bulk-import",
            headers={**_bearer(jwt), "Content-Type": "text/csv"},
            params={"project_id": str(project_id)},
            content=csv_blob,
        )
    assert r.status_code == 413, r.text


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_dry_run_dedup_does_not_leak_across_projects(db_session, monkeypatch):
    """Revision checker fix #9 - Lead-A's dry_run on `9.9.9.9` must NOT see
    Project B's row as a `would_update` hit. Without project-scoped dedup,
    row counts become an oracle for cross-project IOC enumeration (mirror of
    PROD-01 leakage).
    """
    _patch_auth(monkeypatch)
    project_a, user_a = await _seed_project(db_session, "leak-a")
    project_b, _ = await _seed_project(db_session, "leak-b")

    # Seed `(B, ip, 9.9.9.9)` in Project B only.
    iid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    await db_session.execute(
        text(
            "INSERT INTO iocs "
            "(id, project_id, type, value, normalized_value, status, confidence, "
            " ttl_days, source, first_seen, last_seen, created_at, updated_at) "
            "VALUES (:id, :pid, 'ip', '9.9.9.9', '9.9.9.9', 'active', 0.7, 30, "
            " 'manual', :ts, :ts, :ts, :ts)"
        ),
        {"id": iid, "pid": project_b, "ts": now},
    )
    await db_session.commit()

    jwt = _mint(user_a, "Analyst", [[str(project_a), PROJECT_ROLE_RANK["Lead"]]])
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/iocs/bulk-import",
            headers={**_bearer(jwt), "Content-Type": "text/csv"},
            params={"dry_run": "true", "project_id": str(project_a)},
            content=b"type,value\nip,9.9.9.9\n",
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["would_insert"] == 1, body
    assert body["would_update"] == 0, (
        "Project B's row must NOT count as a duplicate from Project A's "
        "perspective - would expose cross-project IOC presence"
    )


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_csv_project_id_mismatch_422(db_session, monkeypatch):
    """Revision checker fix #4 - CSV row.project_id != route project_id (non-admin)
    must be rejected so a Lead can't smuggle rows into other projects via the
    optional CSV column.
    """
    _patch_auth(monkeypatch)
    project_a, user_a = await _seed_project(db_session, "mismatch-a")
    project_b, _ = await _seed_project(db_session, "mismatch-b")

    jwt = _mint(user_a, "Analyst", [[str(project_a), PROJECT_ROLE_RANK["Lead"]]])

    csv_blob = (
        f"type,value,project_id\nip,7.7.7.7,{project_b}\n"
    ).encode()
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/iocs/bulk-import",
            headers={**_bearer(jwt), "Content-Type": "text/csv"},
            params={"project_id": str(project_a)},
            content=csv_blob,
        )
    assert r.status_code == 422, r.text
    assert "row_project_id_mismatch" in r.json()["detail"]


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_csv_admin_global_upload_accepts_global(db_session, monkeypatch):
    """Admin can upload a CSV with project_id='global' (→ None) without
    `?project_id`; the row is accepted and the import enqueued.
    """
    _patch_auth(monkeypatch)
    admin_jwt = await _seed_admin(db_session)

    csv_blob = b"type,value,project_id\nip,1.2.3.4,global\n"
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/iocs/bulk-import",
            headers={**_bearer(admin_jwt), "Content-Type": "text/csv"},
            content=csv_blob,
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rows_accepted"] == 1

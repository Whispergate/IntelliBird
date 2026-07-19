"""IOC-07 admin backfill endpoint + idempotency + seed_iocs CLI - Plan 22-04 Task 3.

The backfill admin endpoint enqueues `backfill_iocs_actor` (Dramatiq) - for
deterministic test runs we drive the actor's underlying body directly via
`backfill_iocs_actor.fn(...)` (Dramatiq exposes `.fn` as the inner callable
on every actor decorator) so we get synchronous execution against the
testcontainer DB without spinning up a worker process.
"""
from __future__ import annotations

import hashlib
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

from app.security.jwt import mint_access_token_with_pm

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
    jwt, _ = mint_access_token_with_pm(
        user_id, "Admin", ["red", "blue"], 0, TEST_SIGNING_KEY, [], False,
    )
    return jwt


async def _seed_project(db_session, name: str) -> uuid.UUID:
    pid = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO projects (id, name, engagement_type, created_by, archived) "
            "VALUES (:id, :n, 'internal', :cb, false)"
        ),
        {"id": pid, "n": name, "cb": str(uuid.uuid4())},
    )
    await db_session.commit()
    return pid


async def _seed_event(
    db_session, project_id, title: str, source_id: uuid.UUID | None = None,
) -> uuid.UUID:
    eid = uuid.uuid4()
    obs = datetime.now(timezone.utc)
    ch = hashlib.sha256(f"{eid}-{title}".encode()).hexdigest()
    await db_session.execute(
        text(
            "INSERT INTO events "
            "(id, stix_type, project_id, source_id, observed_at, title, "
            " content_hash, visibility) "
            "VALUES (:id, 'observed-data', :pid, :sid, :obs, :t, :ch, 'shared')"
        ),
        {
            "id": eid, "pid": project_id, "sid": source_id, "obs": obs,
            "t": title, "ch": ch,
        },
    )
    return eid


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_backfill_admin_endpoint_returns_202_and_job_id(db_session, monkeypatch):
    _patch_auth(monkeypatch)
    pid = await _seed_project(db_session, "bf-prj-1")
    await _seed_event(db_session, pid, "incident with 1.2.3.4 in body")
    await _seed_event(db_session, pid, "domain evil.example seen")
    await db_session.commit()

    admin_jwt = await _seed_admin(db_session)
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/admin/iocs/backfill",
            headers={"Authorization": f"Bearer {admin_jwt}"},
        )
        assert r.status_code == 202, r.text
        body = r.json()
        assert "job_id" in body
        # Validate UUID shape.
        uuid.UUID(body["job_id"])

    # Drive the actor body synchronously to assert it produces rows.
    from app.workers.iocs import _async_backfill
    await _async_backfill(body["job_id"], None)

    ioc_count = (
        await db_session.execute(text("SELECT COUNT(*) FROM iocs"))
    ).scalar_one()
    assert ioc_count > 0, "backfill should have produced IOC rows"


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_backfill_idempotent_second_run_zero_inserts(db_session):
    pid = await _seed_project(db_session, "bf-idem")
    await _seed_event(db_session, pid, "host 8.8.4.4 noted")
    await db_session.commit()

    from app.workers.iocs import _async_backfill

    await _async_backfill(str(uuid.uuid4()), None)
    first_count = (
        await db_session.execute(text("SELECT COUNT(*) FROM iocs"))
    ).scalar_one()
    assert first_count >= 1

    # Second run - UNIQUE NULLS NOT DISTINCT + on_conflict_do_update preserves
    # confidence; net new rows should be 0.
    await _async_backfill(str(uuid.uuid4()), None)
    second_count = (
        await db_session.execute(text("SELECT COUNT(*) FROM iocs"))
    ).scalar_one()
    assert second_count == first_count, (
        f"second backfill must add 0 rows, got delta {second_count - first_count}"
    )


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_backfill_inherits_source_confidence_with_legacy_fallback(db_session):
    """Backfill confidence inheritance:
      * source.confidence=0.9 → IOC.confidence=0.9
      * source_id IS NULL    → IOC.confidence=0.5 (LEGACY fallback)
    """
    pid = await _seed_project(db_session, "bf-conf")
    sid = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO sources (id, name, feed_type, url, enabled, confidence, "
            " poll_interval_sec) "
            "VALUES (:id, :n, 'rss', 'http://example.invalid/feed.xml', true, 0.9, 600)"
        ),
        {"id": sid, "n": f"src-{sid.hex[:8]}"},
    )
    await db_session.commit()

    await _seed_event(db_session, pid, "high-conf 5.5.5.5 indicator", source_id=sid)
    await _seed_event(db_session, pid, "legacy 6.6.6.6 indicator", source_id=None)
    await db_session.commit()

    from app.workers.iocs import _async_backfill
    await _async_backfill(str(uuid.uuid4()), None)

    high = (
        await db_session.execute(
            text("SELECT confidence FROM iocs WHERE normalized_value = '5.5.5.5'")
        )
    ).scalar_one()
    legacy = (
        await db_session.execute(
            text("SELECT confidence FROM iocs WHERE normalized_value = '6.6.6.6'")
        )
    ).scalar_one()
    assert high == Decimal("0.90"), f"expected 0.90 from source, got {high!r}"
    assert legacy == Decimal("0.50"), f"expected 0.50 LEGACY default, got {legacy!r}"


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_seed_iocs_cli_idempotent(db_session):
    """Calling `app.scripts.seed_iocs.main()` twice produces zero net new rows
    on the second invocation.
    """
    pid = await _seed_project(db_session, "bf-cli")
    await _seed_event(db_session, pid, "cli scan 7.7.7.7 sighting")
    await db_session.commit()

    # Drive the CLI's inner coroutine directly - `cli.main()` calls
    # `asyncio.run(_run())` which can't nest inside pytest-asyncio's loop.
    # The CLI itself is exercised by the entrypoint at boot; this test
    # asserts the underlying idempotence contract.
    from app.scripts.seed_iocs import _run

    result1 = await _run()
    assert result1["events_processed"] >= 1
    first = (
        await db_session.execute(text("SELECT COUNT(*) FROM iocs"))
    ).scalar_one()
    assert first >= 1

    result2 = await _run()
    assert result2["events_processed"] >= 1
    second = (
        await db_session.execute(text("SELECT COUNT(*) FROM iocs"))
    ).scalar_one()
    assert second == first, (
        f"seed_iocs second run must be idempotent, delta={second - first}"
    )

"""IOC-08 linked-events ordering tests.

Implemented by Plan 22-03 Task 2.

Covers BOTH directions of the IOC ↔ Event relationship:
  * GET /api/iocs/{id}/events returns linked events sorted by observed_at DESC
    (Plan/spec mentions `published_at`; Event model in this repo names the
    field `observed_at` — TimescaleDB partition column. Sort semantics are
    identical: most-recent-first.)
  * GET /api/events/{id}/iocs returns ALL linked IOCs (used by Plan 22-06's
    EventDetailDrawer §Surface 5 — concrete event-side endpoint replacing the
    earlier "embed in event payload" hedge).
"""
from __future__ import annotations

import hashlib
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


async def _client():
    from app.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
async def _truncate_iocs(db_session):
    await db_session.execute(text("TRUNCATE TABLE ioc_event_links, iocs RESTART IDENTITY CASCADE"))
    await db_session.commit()
    yield


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_linked_events_endpoint_sorted_observed_at_desc(db_session, monkeypatch):
    """Insert 3 events at t-2h, t-1h, t-now; link to one IOC. Assert the route
    returns them most-recent-first.
    """
    _patch_auth(monkeypatch)

    pid = uuid.uuid4()
    user_id = str(uuid.uuid4())
    await db_session.execute(
        text(
            "INSERT INTO projects (id, name, engagement_type, created_by, archived) "
            "VALUES (:id, :name, 'internal', :cb, false)"
        ),
        {"id": pid, "name": "linked-evt-ordering", "cb": user_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO users (id, username, role) VALUES (:id, :u, 'Analyst') "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": user_id, "u": "linked-evt-user"},
    )

    now = datetime.now(timezone.utc)
    ioc_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO iocs "
            "(id, project_id, type, value, normalized_value, status, confidence, "
            " ttl_days, source, first_seen, last_seen, created_at, updated_at) "
            "VALUES (:id, :pid, 'ip', '5.5.5.5', '5.5.5.5', 'active', 0.9, 30, 'manual', "
            "        :now, :now, :now, :now)"
        ),
        {"id": ioc_id, "pid": pid, "now": now},
    )

    events_in_order: list[uuid.UUID] = []
    # Newest first in `events_in_order`: t-now, t-1h, t-2h.
    for i, hours_ago in enumerate([0, 1, 2]):
        eid = uuid.uuid4()
        events_in_order.append(eid)
        observed = now - timedelta(hours=hours_ago)
        ch = hashlib.sha256(f"{eid}".encode()).hexdigest()
        await db_session.execute(
            text(
                "INSERT INTO events "
                "(id, stix_type, project_id, observed_at, title, content_hash, visibility) "
                "VALUES (:id, 'observed-data', :pid, :obs, :t, :ch, 'shared')"
            ),
            {"id": eid, "pid": pid, "obs": observed, "t": f"evt-{i}", "ch": ch},
        )
        await db_session.execute(
            text(
                "INSERT INTO ioc_event_links (id, ioc_id, event_id, observed_at, source_field) "
                "VALUES (:id, :ioc, :evt, :now, 'title')"
            ),
            {"id": uuid.uuid4(), "ioc": ioc_id, "evt": eid, "now": observed},
        )
    await db_session.commit()

    pm = [[str(pid), PROJECT_ROLE_RANK["Lead"]]]
    jwt, _ = mint_access_token_with_pm(
        user_id, "Analyst", ["red", "blue"], 0, TEST_SIGNING_KEY, pm, False,
    )

    async with await _client() as c:
        r = await c.get(f"/api/iocs/{ioc_id}/events", headers=_bearer(jwt))
        assert r.status_code == 200, r.text
        rows = r.json()
        assert len(rows) == 3, f"Expected 3 linked events, got {len(rows)}: {rows}"
        returned_ids = [row["id"] for row in rows]
        # Assert DESC order: events_in_order[0] (newest) first.
        assert returned_ids == [str(eid) for eid in events_in_order], (
            f"Linked events not sorted by observed_at DESC.\n"
            f"  expected: {[str(e) for e in events_in_order]}\n"
            f"  got:      {returned_ids}"
        )


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_event_iocs_endpoint_returns_all_linked_iocs(db_session, monkeypatch):
    """Inverse direction: 3 IOCs linked to one event; GET /api/events/{id}/iocs
    surfaces all 3.
    """
    _patch_auth(monkeypatch)

    pid = uuid.uuid4()
    user_id = str(uuid.uuid4())
    await db_session.execute(
        text(
            "INSERT INTO projects (id, name, engagement_type, created_by, archived) "
            "VALUES (:id, :name, 'internal', :cb, false)"
        ),
        {"id": pid, "name": "evt-iocs-fanout", "cb": user_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO users (id, username, role) VALUES (:id, :u, 'Analyst') "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": user_id, "u": "evt-iocs-user"},
    )

    now = datetime.now(timezone.utc)
    eid = uuid.uuid4()
    ch = hashlib.sha256(f"{eid}".encode()).hexdigest()
    await db_session.execute(
        text(
            "INSERT INTO events "
            "(id, stix_type, project_id, observed_at, title, content_hash, visibility) "
            "VALUES (:id, 'observed-data', :pid, :obs, :t, :ch, 'shared')"
        ),
        {"id": eid, "pid": pid, "obs": now, "t": "fanout-evt", "ch": ch},
    )

    seeded_iocs: list[uuid.UUID] = []
    for ioc_type, value in [("ip", "8.8.8.8"), ("domain", "evil.test"), ("sha256", "a" * 64)]:
        iid = uuid.uuid4()
        seeded_iocs.append(iid)
        await db_session.execute(
            text(
                "INSERT INTO iocs "
                "(id, project_id, type, value, normalized_value, status, confidence, "
                " ttl_days, source, first_seen, last_seen, created_at, updated_at) "
                "VALUES (:id, :pid, :t, :v, :nv, 'active', 0.7, 30, 'manual', "
                "        :now, :now, :now, :now)"
            ),
            {"id": iid, "pid": pid, "t": ioc_type, "v": value, "nv": value.lower(), "now": now},
        )
        await db_session.execute(
            text(
                "INSERT INTO ioc_event_links (id, ioc_id, event_id, observed_at, source_field) "
                "VALUES (:id, :ioc, :evt, :now, 'description')"
            ),
            {"id": uuid.uuid4(), "ioc": iid, "evt": eid, "now": now},
        )
    await db_session.commit()

    pm = [[str(pid), PROJECT_ROLE_RANK["Lead"]]]
    jwt, _ = mint_access_token_with_pm(
        user_id, "Analyst", ["red", "blue"], 0, TEST_SIGNING_KEY, pm, False,
    )

    async with await _client() as c:
        r = await c.get(f"/api/events/{eid}/iocs", headers=_bearer(jwt))
        assert r.status_code == 200, r.text
        rows = r.json()
        assert len(rows) == 3, f"Expected 3 IOCs, got {len(rows)}: {rows}"
        returned = {row["id"] for row in rows}
        assert returned == {str(iid) for iid in seeded_iocs}, (
            f"Event-side IOC list mismatch: expected={seeded_iocs} got={returned}"
        )

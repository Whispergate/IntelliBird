"""Integration tests for Phase 31 Case Management — CASE-01, CASE-02, CASE-03."""
from __future__ import annotations

import os
import uuid

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = pytest.mark.asyncio

TEST_SIGNING_KEY = "j" * 64  # matches two_project.py fixture mint key


# ---------------------------------------------------------------------------
# Auth harness — mirrors test_prod01_cross_project_leakage._patch_auth
# ---------------------------------------------------------------------------


def _patch_auth(monkeypatch) -> None:
    """Enable AUTH_ENABLED, pin signing key, stub token_version/jti checks."""
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
    """Async httpx client wrapping the real FastAPI app."""
    from app.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# CASE-01: Case CRUD — create and retrieve a case
# Tests POST /api/projects/{id}/cases and GET /api/projects/{id}/cases/{case_id}
# ---------------------------------------------------------------------------


async def test_create_case(two_project_fixture, monkeypatch):
    """CASE-01: POST /api/projects/{id}/cases creates a new case.

    Contributor JWT posts {title: "Test Investigation", severity: "high"} to the project
    cases endpoint. Asserts 201 response with an `id` field in the body.
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture
    project_a_id = fx.project_a.id

    async with await _client() as c:
        r = await c.post(
            f"/api/projects/{project_a_id}/cases",
            headers=_bearer(fx.jwt_a),
            json={"title": "Test Investigation", "severity": "high"},
        )

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["title"] == "Test Investigation"
    assert body["status"] == "open"
    assert "id" in body
    assert body["project_id"] == str(project_a_id)
    assert body["severity"] == "high"


# ---------------------------------------------------------------------------
# CASE-01: Retrieve a case by ID
# Tests GET /api/projects/{id}/cases/{case_id}
# ---------------------------------------------------------------------------


async def test_get_case(two_project_fixture, monkeypatch):
    """CASE-01: GET /api/projects/{id}/cases/{case_id} returns the case.

    Observer JWT retrieves a previously-created case by its ID.
    Asserts 200 response with the correct title returned in the body.
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture
    project_a_id = fx.project_a.id

    # Create a case first as Contributor (jwt_a has Lead rank ≥ Contributor)
    async with await _client() as c:
        create_r = await c.post(
            f"/api/projects/{project_a_id}/cases",
            headers=_bearer(fx.jwt_a),
            json={"title": "Retrieve Me Case"},
        )
    assert create_r.status_code == 201, create_r.text
    case_id = create_r.json()["id"]

    # GET the case (jwt_a has Lead rank ≥ Observer)
    async with await _client() as c:
        r = await c.get(
            f"/api/projects/{project_a_id}/cases/{case_id}",
            headers=_bearer(fx.jwt_a),
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == case_id
    assert body["title"] == "Retrieve Me Case"


# ---------------------------------------------------------------------------
# CASE-01: Patch case status
# Tests PATCH /api/projects/{id}/cases/{case_id}
# ---------------------------------------------------------------------------


async def test_patch_case_status(two_project_fixture, monkeypatch):
    """CASE-01: PATCH /api/projects/{id}/cases/{case_id} updates the status field.

    Contributor JWT patches the case with {status: "in_progress"}.
    Asserts 200 response with `status == "in_progress"` in the response body.
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture
    project_a_id = fx.project_a.id

    # Create a case
    async with await _client() as c:
        create_r = await c.post(
            f"/api/projects/{project_a_id}/cases",
            headers=_bearer(fx.jwt_a),
            json={"title": "Status Patch Case"},
        )
    assert create_r.status_code == 201, create_r.text
    case_id = create_r.json()["id"]

    # Patch status to in_progress
    async with await _client() as c:
        r = await c.patch(
            f"/api/projects/{project_a_id}/cases/{case_id}",
            headers=_bearer(fx.jwt_a),
            json={"status": "in_progress"},
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "in_progress"
    assert body["id"] == case_id


# ---------------------------------------------------------------------------
# CASE-02: Attach events to a case
# Tests POST /api/projects/{id}/cases/{case_id}/events
# ---------------------------------------------------------------------------


async def test_attach_events(two_project_fixture, monkeypatch):
    """CASE-02: POST /api/projects/{id}/cases/{case_id}/events attaches events.

    Contributor JWT posts {event_ids: [<event_uuid>]} to the case events endpoint.
    Asserts 200 response. Then GET /api/projects/{id}/cases/{case_id}/events
    returns the attached event in the list.
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture
    project_a_id = fx.project_a.id
    # Use one of the events seeded by two_project_fixture for Project A
    event_id = fx.events_a[0]

    # Create a case
    async with await _client() as c:
        create_r = await c.post(
            f"/api/projects/{project_a_id}/cases",
            headers=_bearer(fx.jwt_a),
            json={"title": "Event Evidence Case"},
        )
    assert create_r.status_code == 201, create_r.text
    case_id = create_r.json()["id"]

    # Attach an event
    async with await _client() as c:
        attach_r = await c.post(
            f"/api/projects/{project_a_id}/cases/{case_id}/events",
            headers=_bearer(fx.jwt_a),
            json={"event_ids": [str(event_id)]},
        )
    assert attach_r.status_code == 200, attach_r.text
    assert attach_r.json()["attached"] == 1

    # GET events attached to the case
    async with await _client() as c:
        list_r = await c.get(
            f"/api/projects/{project_a_id}/cases/{case_id}/events",
            headers=_bearer(fx.jwt_a),
        )
    assert list_r.status_code == 200, list_r.text
    items = list_r.json()
    assert len(items) == 1
    assert items[0]["event_id"] == str(event_id)


# ---------------------------------------------------------------------------
# CASE-02: Attach IOCs to a case
# Tests POST /api/projects/{id}/cases/{case_id}/iocs
# ---------------------------------------------------------------------------


async def test_attach_iocs(two_project_fixture, db_session, monkeypatch):
    """CASE-02: POST /api/projects/{id}/cases/{case_id}/iocs attaches IOCs.

    Seeds a minimal IOC row directly, then Contributor JWT posts {ioc_ids: [<ioc_uuid>]}
    to the case IOCs endpoint. Asserts 200 response. Then GET returns the attached IOC.
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture
    project_a_id = fx.project_a.id

    # Seed a minimal IOC row for Project A
    ioc_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO iocs "
            "(id, project_id, type, value, normalized_value, status, confidence, ttl_days, source) "
            "VALUES (:id, :pid, 'ip', '10.0.0.1', '10.0.0.1', 'active', 0.7, 90, 'manual')"
        ),
        {"id": ioc_id, "pid": project_a_id},
    )
    await db_session.commit()

    # Create a case
    async with await _client() as c:
        create_r = await c.post(
            f"/api/projects/{project_a_id}/cases",
            headers=_bearer(fx.jwt_a),
            json={"title": "IOC Evidence Case"},
        )
    assert create_r.status_code == 201, create_r.text
    case_id = create_r.json()["id"]

    # Attach the IOC
    async with await _client() as c:
        attach_r = await c.post(
            f"/api/projects/{project_a_id}/cases/{case_id}/iocs",
            headers=_bearer(fx.jwt_a),
            json={"ioc_ids": [str(ioc_id)]},
        )
    assert attach_r.status_code == 200, attach_r.text
    assert attach_r.json()["attached"] == 1

    # GET IOCs attached to the case
    async with await _client() as c:
        list_r = await c.get(
            f"/api/projects/{project_a_id}/cases/{case_id}/iocs",
            headers=_bearer(fx.jwt_a),
        )
    assert list_r.status_code == 200, list_r.text
    items = list_r.json()
    assert len(items) == 1
    assert items[0]["ioc_id"] == str(ioc_id)


# ---------------------------------------------------------------------------
# CASE-03: Case activity log
# Tests GET /api/projects/{id}/cases/{case_id}/activity
# ---------------------------------------------------------------------------


async def test_case_activity_log(two_project_fixture, monkeypatch):
    """CASE-03: GET /api/projects/{id}/cases/{case_id}/activity returns audit entries.

    After creating a case and patching its status, the activity endpoint must
    return at least 2 audit log entries with `action` keys present.
    Activity log queried via GET /api/projects/{id}/cases/{case_id}/activity.
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture
    project_a_id = fx.project_a.id

    # Create a case (logs "create" action)
    async with await _client() as c:
        create_r = await c.post(
            f"/api/projects/{project_a_id}/cases",
            headers=_bearer(fx.jwt_a),
            json={"title": "Activity Log Case"},
        )
    assert create_r.status_code == 201, create_r.text
    case_id = create_r.json()["id"]

    # Patch status (logs "status_changed" action)
    async with await _client() as c:
        patch_r = await c.patch(
            f"/api/projects/{project_a_id}/cases/{case_id}",
            headers=_bearer(fx.jwt_a),
            json={"status": "in_progress"},
        )
    assert patch_r.status_code == 200, patch_r.text

    # GET activity log
    async with await _client() as c:
        activity_r = await c.get(
            f"/api/projects/{project_a_id}/cases/{case_id}/activity",
            headers=_bearer(fx.jwt_a),
        )

    assert activity_r.status_code == 200, activity_r.text
    entries = activity_r.json()
    assert len(entries) >= 2, (
        f"Expected at least 2 activity log entries (create + status_changed), got {len(entries)}: {entries}"
    )
    # Every entry must have an "action" key
    for entry in entries:
        assert "action" in entry, f"Activity entry missing 'action' key: {entry}"
    # Verify actions include "create" and "status_changed"
    actions = {e["action"] for e in entries}
    assert "create" in actions, f"Expected 'create' action in activity log. Got: {actions}"
    assert "status_changed" in actions, f"Expected 'status_changed' action in activity log. Got: {actions}"

"""Integration tests for Phase 31 Case Management — CASE-01, CASE-02, CASE-03."""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# CASE-01: Case CRUD — create and retrieve a case
# Tests POST /api/projects/{id}/cases and GET /api/projects/{id}/cases/{case_id}
# Implemented by 31-03-PLAN (cases router + DB migration).
# ---------------------------------------------------------------------------


async def test_create_case(two_project_fixture, monkeypatch):
    """CASE-01: POST /api/projects/{id}/cases creates a new case.

    Contributor JWT posts {title: "Test Case", severity: "high"} to the project
    cases endpoint. Asserts 201 response with an `id` field in the body.
    """
    pytest.skip("not yet implemented — plan 31-03 will turn this green")


# ---------------------------------------------------------------------------
# CASE-01: Retrieve a case by ID
# Tests GET /api/projects/{id}/cases/{case_id}
# Implemented by 31-03-PLAN.
# ---------------------------------------------------------------------------


async def test_get_case(two_project_fixture, monkeypatch):
    """CASE-01: GET /api/projects/{id}/cases/{case_id} returns the case.

    Observer JWT retrieves a previously-created case by its ID.
    Asserts 200 response with the correct title returned in the body.
    """
    pytest.skip("not yet implemented — plan 31-03 will turn this green")


# ---------------------------------------------------------------------------
# CASE-01: Patch case status
# Tests PATCH /api/projects/{id}/cases/{case_id}
# Implemented by 31-03-PLAN.
# ---------------------------------------------------------------------------


async def test_patch_case_status(two_project_fixture, monkeypatch):
    """CASE-01: PATCH /api/projects/{id}/cases/{case_id} updates the status field.

    Contributor JWT patches the case with {status: "in_progress"}.
    Asserts 200 response with `status == "in_progress"` in the response body.
    """
    pytest.skip("not yet implemented — plan 31-03 will turn this green")


# ---------------------------------------------------------------------------
# CASE-02: Attach events to a case
# Tests POST /api/projects/{id}/cases/{case_id}/events
# Implemented by 31-03-PLAN (evidence attach endpoints).
# ---------------------------------------------------------------------------


async def test_attach_events(two_project_fixture, monkeypatch):
    """CASE-02: POST /api/projects/{id}/cases/{case_id}/events attaches events.

    Contributor JWT posts {event_ids: [<event_uuid>]} to the case events endpoint.
    Asserts 200 response. Then GET /api/projects/{id}/cases/{case_id}/events
    returns the attached event in the list.
    """
    pytest.skip("not yet implemented — plan 31-03 will turn this green")


# ---------------------------------------------------------------------------
# CASE-02: Attach IOCs to a case
# Tests POST /api/projects/{id}/cases/{case_id}/iocs
# Implemented by 31-03-PLAN (evidence attach endpoints).
# ---------------------------------------------------------------------------


async def test_attach_iocs(two_project_fixture, monkeypatch):
    """CASE-02: POST /api/projects/{id}/cases/{case_id}/iocs attaches IOCs.

    Contributor JWT posts {ioc_ids: [<ioc_uuid>]} to the case IOCs endpoint.
    Asserts 200 response. Then GET /api/projects/{id}/cases/{case_id}/iocs
    returns the attached IOC in the list.
    """
    pytest.skip("not yet implemented — plan 31-03 will turn this green")


# ---------------------------------------------------------------------------
# CASE-03: Case activity log
# Tests GET /api/projects/{id}/cases/{case_id}/activity
# Implemented by 31-03-PLAN (audit log integration).
# ---------------------------------------------------------------------------


async def test_case_activity_log(two_project_fixture, monkeypatch):
    """CASE-03: GET /api/projects/{id}/cases/{case_id}/activity returns audit entries.

    After creating a case and patching its status, the activity endpoint must
    return at least 2 audit log entries with `resource_type == "case"`.
    Activity log queried via GET /api/projects/{id}/cases/{case_id}/activity.
    """
    pytest.skip("not yet implemented — plan 31-03 will turn this green")

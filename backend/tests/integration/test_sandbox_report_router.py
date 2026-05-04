"""
SANDBOX-04 — GET /api/projects/{project_id}/events/{event_id}/sandbox-report returns normalised schema when report exists.
Implemented in: backend/app/routers/projects/sandbox.py (Phase 27 Plan 06)
"""
import pytest


@pytest.mark.xfail(reason="not yet implemented — Phase 27 Plan 06")
def test_get_sandbox_report_returns_report_when_complete():
    """GET /api/projects/{project_id}/events/{event_id}/sandbox-report returns 200 with normalised SandboxReportRead schema."""
    raise NotImplementedError


@pytest.mark.xfail(reason="not yet implemented — Phase 27 Plan 06")
def test_get_sandbox_report_returns_404_when_no_report():
    """GET /api/projects/{project_id}/events/{event_id}/sandbox-report returns 404 when no sandbox_reports row exists."""
    raise NotImplementedError


@pytest.mark.xfail(reason="not yet implemented — Phase 27 Plan 06")
def test_get_sandbox_report_acl_rejects_wrong_project():
    """GET /api/projects/{project_id}/events/{event_id}/sandbox-report with wrong project JWT returns 403."""
    raise NotImplementedError

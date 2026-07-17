"""
TIMELINE-01..03 — Pattern-of-life timeline router returns bucketed series
                  data and heatmap cells with correct structure and project
                  isolation.

Implemented in: backend/app/routers/timeline.py
"""
import os
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

timeline_router = pytest.importorskip(
    "app.routers.timeline",
    reason="timeline router not yet implemented",
)


@pytest.fixture()
def client():
    """Async test client for the timeline router mounted on a minimal FastAPI app."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(timeline_router.router, prefix="/api/projects/{project_id}")
    return TestClient(app)


def test_series_returns_bucket_structure(client):
    """GET /timeline/series returns JSON with 'buckets' (list) and 'tags' (list).

    The response schema must be: {"buckets": [...], "tags": [...]} regardless
    of whether there are any events.
    """
    from unittest.mock import patch, MagicMock

    project_id = "00000000-0000-0000-0000-000000000001"
    mock_db = MagicMock()

    with patch.object(timeline_router, "_query_series_buckets", return_value=([], [])):
        response = client.get(
            f"/api/projects/{project_id}/timeline/series?range_days=7",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    data = response.json()
    assert "buckets" in data
    assert "tags" in data
    assert isinstance(data["buckets"], list)
    assert isinstance(data["tags"], list)


def test_heatmap_returns_168_cells(client):
    """GET /timeline/heatmap returns exactly 168 cells (24 hours * 7 days).

    Every hour-of-week slot is included even when count is 0.
    """
    from unittest.mock import patch

    project_id = "00000000-0000-0000-0000-000000000001"

    # 168 cells: dow 0-6, hour 0-23
    fake_cells = [
        {"hour": h, "dow": d, "count": 0}
        for d in range(7)
        for h in range(24)
    ]

    with patch.object(timeline_router, "_query_heatmap_cells", return_value=fake_cells):
        response = client.get(
            f"/api/projects/{project_id}/timeline/heatmap",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    data = response.json()
    assert "cells" in data
    assert len(data["cells"]) == 168


def test_heatmap_cell_shape(client):
    """Each heatmap cell has keys 'hour' (0-23), 'dow' (0-6), 'count' (>= 0)."""
    from unittest.mock import patch

    project_id = "00000000-0000-0000-0000-000000000001"

    fake_cells = [
        {"hour": h, "dow": d, "count": 0}
        for d in range(7)
        for h in range(24)
    ]

    with patch.object(timeline_router, "_query_heatmap_cells", return_value=fake_cells):
        response = client.get(
            f"/api/projects/{project_id}/timeline/heatmap",
            headers={"Authorization": "Bearer test-token"},
        )

    data = response.json()
    for cell in data["cells"]:
        assert "hour" in cell
        assert "dow" in cell
        assert "count" in cell
        assert 0 <= cell["hour"] <= 23
        assert 0 <= cell["dow"] <= 6
        assert cell["count"] >= 0


def test_project_isolation(client):
    """Timeline series for project_A does not include events from project_B.

    The router must scope all DB queries by project_id from the path.
    """
    from unittest.mock import patch, MagicMock

    project_a = "aaaaaaaa-0000-0000-0000-000000000001"
    project_b = "bbbbbbbb-0000-0000-0000-000000000002"

    project_b_event_id = "evt-from-project-b"
    captured_calls = []

    def fake_query_series(session, project_id, range_days, **kwargs):
        captured_calls.append(project_id)
        return [], []

    with patch.object(timeline_router, "_query_series_buckets", side_effect=fake_query_series):
        client.get(
            f"/api/projects/{project_a}/timeline/series?range_days=7",
            headers={"Authorization": "Bearer test-token"},
        )

    # All DB queries must have been scoped to project_A, never project_B
    assert all(str(pid) == project_a for pid in captured_calls), (
        f"Expected all queries scoped to {project_a}, got: {captured_calls}"
    )


def test_series_adaptive_bucket_7d(client):
    """GET /timeline/series?range_days=7 returns bucket_interval='hour'."""
    from unittest.mock import patch

    project_id = "00000000-0000-0000-0000-000000000001"

    def fake_query(session, project_id, range_days, **kwargs):
        return [], []

    with patch.object(timeline_router, "_query_series_buckets", side_effect=fake_query):
        response = client.get(
            f"/api/projects/{project_id}/timeline/series?range_days=7",
            headers={"Authorization": "Bearer test-token"},
        )

    data = response.json()
    assert data.get("bucket_interval") == "hour"


def test_series_adaptive_bucket_30d(client):
    """GET /timeline/series?range_days=30 returns bucket_interval='day'."""
    from unittest.mock import patch

    project_id = "00000000-0000-0000-0000-000000000001"

    def fake_query(session, project_id, range_days, **kwargs):
        return [], []

    with patch.object(timeline_router, "_query_series_buckets", side_effect=fake_query):
        response = client.get(
            f"/api/projects/{project_id}/timeline/series?range_days=30",
            headers={"Authorization": "Bearer test-token"},
        )

    data = response.json()
    assert data.get("bucket_interval") == "day"

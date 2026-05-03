"""Unit tests for TAXII 2.1 router — Phase 26 / TAXII-01, TAXII-05."""
from __future__ import annotations

import inspect
import os
import uuid
from unittest.mock import MagicMock

# Must be set before any app.* import (settings singleton validates at module load)
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.taxii_auth import require_taxii_client
from app.routers.taxii import router


def _make_app(client_override=None) -> FastAPI:
    """Build a minimal FastAPI app with the TAXII router for unit testing."""
    app = FastAPI()
    app.include_router(router, prefix="/taxii2")
    if client_override is not None:
        app.dependency_overrides[require_taxii_client] = lambda: client_override
    return app


def _mock_taxii_client(
    project_id: uuid.UUID | None = None,
    tlp_max_level: str = "green",
    rate_limit_rpm: int = 60,
) -> MagicMock:
    m = MagicMock()
    m.id = uuid.uuid4()
    m.label = "Test Partner"
    m.project_id = project_id or uuid.uuid4()
    m.tlp_max_level = tlp_max_level
    m.rate_limit_rpm = rate_limit_rpm
    m.revoked = False
    return m


def test_discovery_response():
    """TAXII-01: GET /taxii2/ returns spec-correct JSON with title + api_roots."""
    client = _mock_taxii_client()
    app = _make_app(client)
    with TestClient(app) as tc:
        resp = tc.get("/taxii2/")
    assert resp.status_code == 200
    data = resp.json()
    assert "title" in data
    assert "api_roots" in data
    assert isinstance(data["api_roots"], list)
    assert len(data["api_roots"]) >= 1


def test_discovery_requires_auth():
    """TAXII-01: GET /taxii2/ without credentials requires the client dependency.

    In unit tests without a DB we verify the dependency is declared on the
    endpoint signature rather than attempting a live auth flow.
    """
    from app.routers.taxii import get_discovery

    sig = inspect.signature(get_discovery)
    params = list(sig.parameters.values())
    dep_names = [p.name for p in params]
    assert "client" in dep_names, (
        "get_discovery must have 'client' parameter from require_taxii_client"
    )


def test_content_type_header():
    """TAXII-05: Every TAXII response carries Content-Type: application/taxii+json;version=2.1."""
    client = _mock_taxii_client()
    app = _make_app(client)
    with TestClient(app) as tc:
        resp = tc.get("/taxii2/")
    assert resp.status_code == 200
    ct = resp.headers.get("content-type", "")
    assert "application/taxii+json" in ct, f"Expected TAXII content type, got: {ct}"
    assert "version=2.1" in ct, f"Expected version=2.1 in content type, got: {ct}"


def test_page_cap_100():
    """TAXII-05: Query param limit=200 is rejected with 422; PAGE_CAP constant is 100."""
    from app.routers.taxii import PAGE_CAP

    assert PAGE_CAP == 100

    # Verify the router rejects limit > 100 with 422 (le=PAGE_CAP validator)
    client = _mock_taxii_client()
    project_id = client.project_id
    app = _make_app(client)
    with TestClient(app) as tc:
        resp = tc.get(f"/taxii2/api/collections/{project_id}/objects/?limit=200")
    assert resp.status_code == 422, "limit=200 should be rejected as out of range (le=100)"

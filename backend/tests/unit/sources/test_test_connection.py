"""Unit tests for source probe helpers and /test-connection endpoint (SRC-03).

Probe helper tests (Task 1 — RED/GREEN):
 9 tests covering _probe_rss, _probe_nvd, _probe_taxii

Endpoint tests (Task 2 — RED/GREEN):
 8 tests covering route contract, HTTP 200 on probe failure, arg forwarding

Environment: tests run without a live Postgres/Redis — endpoint tests use a
mini FastAPI with only the sources router mounted.
"""
from __future__ import annotations

import os
import uuid
from typing import AsyncIterator
from unittest.mock import MagicMock

import pytest

# Ensure Settings can initialize before any app import touches it.
os.environ.setdefault("SECRET_KEY", "a" * 64)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

# ---------------------------------------------------------------------------
# Probe helper tests
# ---------------------------------------------------------------------------


class TestProbeRss:
    def test_probe_rss_success(self, monkeypatch):
        """parse_rss_feed returns 2 entries → (True, >=0, 2, None)."""
        from app.services.source_probes import _probe_rss

        fake_parsed = MagicMock()
        fake_parsed.entries = [{"x": 1}, {"x": 2}]
        fake_parsed.bozo = 0
        monkeypatch.setattr(
            "app.ingest.rss_parser.parse_rss_feed", lambda url, **kw: fake_parsed
        )
        ok, latency, count, err = _probe_rss("http://example.com/feed")
        assert ok is True
        assert latency >= 0
        assert count == 2
        assert err is None

    def test_probe_rss_network_error(self, monkeypatch):
        """parse_rss_feed raises ConnectionError → (False, >=0, 0, 'boom')."""
        from app.services.source_probes import _probe_rss

        def _raise(url, **kw):
            raise ConnectionError("boom")

        monkeypatch.setattr("app.ingest.rss_parser.parse_rss_feed", _raise)
        ok, latency, count, err = _probe_rss("http://example.com/feed")
        assert ok is False
        assert latency >= 0
        assert count == 0
        assert err == "boom"

    def test_probe_rss_parse_error(self, monkeypatch):
        """bozo=1, entries=[] → (False, >=0, 0, 'malformed')."""
        from app.services.source_probes import _probe_rss

        fake_parsed = MagicMock()
        fake_parsed.bozo = 1
        fake_parsed.bozo_exception = Exception("malformed")
        fake_parsed.entries = []
        monkeypatch.setattr(
            "app.ingest.rss_parser.parse_rss_feed", lambda url, **kw: fake_parsed
        )
        ok, latency, count, err = _probe_rss("http://example.com/feed")
        assert ok is False
        assert count == 0
        assert err == "malformed"


class TestProbeNvd:
    def test_probe_nvd_success(self, monkeypatch):
        """nvdlib returns 1 result → (True, >=0, 1, None)."""
        import nvdlib

        monkeypatch.setattr(nvdlib, "searchCVE_V2", lambda **kw: iter([object()]))
        from app.services.source_probes import _probe_nvd

        ok, latency, count, err = _probe_nvd(None)
        assert ok is True
        assert latency >= 0
        assert count == 1
        assert err is None

    def test_probe_nvd_rate_limit(self, monkeypatch):
        """nvdlib raises 429 rate limit → (False, >=0, 0, '429 rate limit')."""
        import nvdlib

        def _raise(**kw):
            raise Exception("429 rate limit")

        monkeypatch.setattr(nvdlib, "searchCVE_V2", _raise)
        from app.services.source_probes import _probe_nvd

        ok, latency, count, err = _probe_nvd(None)
        assert ok is False
        assert count == 0
        assert "429 rate limit" in err


class TestProbeTaxii:
    def test_probe_taxii_success_with_basic_auth(self, monkeypatch):
        """Server with basic auth + 3 api_roots → (True, >=0, 3, None); Server called with user/password."""
        import taxii2client.v21 as taxii_v21

        captured_kwargs: dict = {}

        class _FakeServer:
            def __init__(self, url, **kwargs):
                captured_kwargs.update(kwargs)
                self.api_roots = [1, 2, 3]

        monkeypatch.setattr(taxii_v21, "Server", _FakeServer)

        from app.services.source_probes import _probe_taxii

        creds = {"type": "basic", "username": "u", "password": "p"}
        ok, latency, count, err = _probe_taxii("https://taxii.example.com/taxii/", creds)
        assert ok is True
        assert count == 3
        assert err is None
        assert captured_kwargs.get("user") == "u"
        assert captured_kwargs.get("password") == "p"

    def test_probe_taxii_no_api_roots(self, monkeypatch):
        """Server returns empty api_roots → (False, >=0, 0, 'no api_roots...')."""
        import taxii2client.v21 as taxii_v21

        class _FakeServer:
            def __init__(self, url, **kwargs):
                self.api_roots = []

        monkeypatch.setattr(taxii_v21, "Server", _FakeServer)

        from app.services.source_probes import _probe_taxii

        ok, latency, count, err = _probe_taxii("https://taxii.example.com/taxii/", None)
        assert ok is False
        assert count == 0
        assert "no api_roots" in err

    def test_probe_taxii_bearer_header(self, monkeypatch):
        """credentials type=bearer → Server called with headers={'Authorization': 'Bearer t'}."""
        import taxii2client.v21 as taxii_v21

        captured_kwargs: dict = {}

        class _FakeServer:
            def __init__(self, url, **kwargs):
                captured_kwargs.update(kwargs)
                self.api_roots = ["root1"]

        monkeypatch.setattr(taxii_v21, "Server", _FakeServer)

        from app.services.source_probes import _probe_taxii

        creds = {"type": "bearer", "token": "t"}
        ok, latency, count, err = _probe_taxii("https://taxii.example.com/taxii/", creds)
        assert ok is True
        assert captured_kwargs.get("headers") == {"Authorization": "Bearer t"}

    def test_probe_taxii_network_error(self, monkeypatch):
        """Server constructor raises → (False, >=0, 0, error message)."""
        import taxii2client.v21 as taxii_v21

        class _FakeServer:
            def __init__(self, url, **kwargs):
                raise ConnectionError("connection refused")

        monkeypatch.setattr(taxii_v21, "Server", _FakeServer)

        from app.services.source_probes import _probe_taxii

        ok, latency, count, err = _probe_taxii("https://taxii.example.com/taxii/", None)
        assert ok is False
        assert count == 0
        assert "connection refused" in err


# ---------------------------------------------------------------------------
# Endpoint tests — use a mini FastAPI with only the sources router
# ---------------------------------------------------------------------------


@pytest.fixture()
def mini_app():
    """Mini FastAPI with only the sources router — no DB required for test-connection."""
    from fastapi import FastAPI
    from app.routers.admin.sources import router

    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture()
def test_client(mini_app):
    from fastapi.testclient import TestClient

    return TestClient(mini_app)


class TestEndpointContract:
    def test_endpoint_rss_ok(self, monkeypatch, test_client):
        """Successful RSS probe → 200 + correct body."""
        import app.routers.admin.sources as _mod

        monkeypatch.setattr(_mod, "_probe_rss", lambda url: (True, 42, 5, None))
        resp = test_client.post(
            "/admin/sources/test-connection",
            json={"feed_type": "rss", "url": "https://x", "credentials": None},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["latency_ms"] == 42
        assert body["item_count_sampled"] == 5
        assert body["error_detail"] is None

    def test_endpoint_rss_failure_returns_200_not_5xx(self, monkeypatch, test_client):
        """Failed probe → HTTP 200 (not 500); ok=false in body."""
        import app.routers.admin.sources as _mod

        monkeypatch.setattr(_mod, "_probe_rss", lambda url: (False, 100, 0, "boom"))
        resp = test_client.post(
            "/admin/sources/test-connection",
            json={"feed_type": "rss", "url": "https://x"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["error_detail"] == "boom"

    def test_endpoint_nvd_extracts_api_key_from_credentials(self, monkeypatch, test_client):
        """NVD probe called with the api_key extracted from credentials."""
        import app.routers.admin.sources as _mod

        captured = {}

        def _fake_probe_nvd(api_key):
            captured["api_key"] = api_key
            return (True, 10, 1, None)

        monkeypatch.setattr(_mod, "_probe_nvd", _fake_probe_nvd)
        resp = test_client.post(
            "/admin/sources/test-connection",
            json={
                "feed_type": "nvd",
                "url": "https://nvd.nist.gov",
                "credentials": {"type": "apiKey", "key": "ABC"},
            },
        )
        assert resp.status_code == 200
        assert captured["api_key"] == "ABC"

    def test_endpoint_nvd_null_credentials_passes_none_key(self, monkeypatch, test_client):
        """NVD with null credentials → _probe_nvd called with None."""
        import app.routers.admin.sources as _mod

        captured = {}

        def _fake_probe_nvd(api_key):
            captured["api_key"] = api_key
            return (True, 10, 1, None)

        monkeypatch.setattr(_mod, "_probe_nvd", _fake_probe_nvd)
        resp = test_client.post(
            "/admin/sources/test-connection",
            json={"feed_type": "nvd", "url": "https://nvd.nist.gov", "credentials": None},
        )
        assert resp.status_code == 200
        assert captured["api_key"] is None

    def test_endpoint_taxii_forwards_credentials_dict(self, monkeypatch, test_client):
        """TAXII probe receives the credentials dict intact."""
        import app.routers.admin.sources as _mod

        captured = {}

        def _fake_probe_taxii(url, credentials):
            captured["credentials"] = credentials
            return (True, 30, 2, None)

        monkeypatch.setattr(_mod, "_probe_taxii", _fake_probe_taxii)
        creds = {"type": "bearer", "token": "t"}
        resp = test_client.post(
            "/admin/sources/test-connection",
            json={"feed_type": "taxii", "url": "https://taxii.example.com", "credentials": creds},
        )
        assert resp.status_code == 200
        assert captured["credentials"] == creds

    def test_endpoint_invalid_feed_type_422(self, test_client):
        """Unknown feed_type → 422 Unprocessable Entity."""
        resp = test_client.post(
            "/admin/sources/test-connection",
            json={"feed_type": "bogus", "url": "https://x"},
        )
        assert resp.status_code == 422

    def test_endpoint_missing_url_422(self, test_client):
        """Missing url field → 422."""
        resp = test_client.post(
            "/admin/sources/test-connection",
            json={"feed_type": "rss"},
        )
        assert resp.status_code == 422

    def test_endpoint_does_not_touch_db(self, monkeypatch, mini_app, test_client):
        """test-connection handler has no DB dependency — get_session never called."""
        import app.routers.admin.sources as _mod
        from app.database import get_session

        db_calls = []

        async def _spy():
            db_calls.append(True)
            yield MagicMock()

        mini_app.dependency_overrides[get_session] = _spy

        monkeypatch.setattr(_mod, "_probe_rss", lambda url: (True, 5, 0, None))
        try:
            resp = test_client.post(
                "/admin/sources/test-connection",
                json={"feed_type": "rss", "url": "https://x"},
            )
            assert resp.status_code == 200
            assert db_calls == [], "test-connection handler must NOT use the DB session"
        finally:
            mini_app.dependency_overrides.pop(get_session, None)

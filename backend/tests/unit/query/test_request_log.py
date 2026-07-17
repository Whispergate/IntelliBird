"""Unit tests for RequestLogMiddleware — SYS-04."""
from __future__ import annotations

import structlog
import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.logging import configure_logging
from app.middleware.request_log import RequestLogMiddleware


@pytest.fixture(autouse=True)
def _logging():
    configure_logging()


@pytest.fixture
def app_with_middleware():
    app = FastAPI()
    app.add_middleware(RequestLogMiddleware)

    @app.get("/hello")
    async def hello():
        _log = structlog.get_logger("hello")
        _log.info("inner_handler_log")
        return {"ok": True}

    @app.get("/boom")
    async def boom():
        raise ValueError("kapow")

    return app


@pytest.mark.asyncio
async def test_middleware_echoes_x_request_id_header(app_with_middleware):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_middleware), base_url="http://t"
    ) as c:
        r = await c.get("/hello")
        assert r.status_code == 200
        assert "x-request-id" in [h.lower() for h in r.headers.keys()]


@pytest.mark.asyncio
async def test_middleware_uses_incoming_x_request_id(app_with_middleware):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_middleware), base_url="http://t"
    ) as c:
        r = await c.get("/hello", headers={"X-Request-Id": "client-chosen-abc"})
        assert r.headers["X-Request-Id"] == "client-chosen-abc"


@pytest.mark.asyncio
async def test_middleware_generates_request_id_when_absent(app_with_middleware):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_middleware), base_url="http://t"
    ) as c:
        r = await c.get("/hello")
        assert len(r.headers["X-Request-Id"]) >= 32  # UUID-ish


def _render_caplog(caplog) -> str:
    """Join all caplog records into a single string for substring assertions.

    note: middleware log records (structlog → stdlib bridge) flow
    through the Python logging system and are captured by caplog regardless of
    where StreamHandler's stored sys.stdout reference points. Using caplog is
    resilient to the app.main pre-import that captures stdout before pytest's
    capsys replaces it (configure_logging in main runs once at module import).
    """
    return "\n".join(str(r.msg) for r in caplog.records)


@pytest.mark.asyncio
async def test_middleware_emits_http_request_event(app_with_middleware, caplog):
    import logging as _logging_mod
    caplog.set_level(_logging_mod.INFO)
    async with AsyncClient(
        transport=ASGITransport(app=app_with_middleware), base_url="http://t"
    ) as c:
        await c.get("/hello", headers={"X-Dashboard-Role": "red"})
    rendered = _render_caplog(caplog)
    # Middleware log record carries event="http_request" + method/path/status/duration_ms/dashboard_role
    assert "'event': 'http_request'" in rendered or '"event": "http_request"' in rendered
    assert "'method':" in rendered or '"method":' in rendered
    assert "'path':" in rendered or '"path":' in rendered
    assert "'status':" in rendered or '"status":' in rendered
    assert "'duration_ms':" in rendered or '"duration_ms":' in rendered
    assert "red" in rendered  # dashboard_role value


@pytest.mark.asyncio
async def test_middleware_reraises_exception_and_logs(app_with_middleware, caplog):
    """Exception should be logged then re-raised; test verifies log emission."""
    import logging as _logging_mod
    caplog.set_level(_logging_mod.INFO)
    with pytest.raises(Exception):
        async with AsyncClient(
            transport=ASGITransport(app=app_with_middleware), base_url="http://t"
        ) as c:
            await c.get("/boom")
    rendered = _render_caplog(caplog)
    assert "http_request_exception" in rendered


@pytest.mark.asyncio
async def test_middleware_binds_request_id_to_context(app_with_middleware, caplog):
    """Downstream log calls (inner_handler_log) should include request_id thanks to merge_contextvars."""
    import logging as _logging_mod
    caplog.set_level(_logging_mod.INFO)
    async with AsyncClient(
        transport=ASGITransport(app=app_with_middleware), base_url="http://t"
    ) as c:
        await c.get("/hello", headers={"X-Request-Id": "bind-test-xyz"})
    rendered = _render_caplog(caplog)
    # Both the middleware log and the inner log should carry request_id=bind-test-xyz
    assert "bind-test-xyz" in rendered
    # Find both event names in output
    assert "inner_handler_log" in rendered
    assert "http_request" in rendered

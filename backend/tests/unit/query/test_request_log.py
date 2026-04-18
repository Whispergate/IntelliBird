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


@pytest.mark.asyncio
async def test_middleware_emits_http_request_event(app_with_middleware, capsys):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_middleware), base_url="http://t"
    ) as c:
        await c.get("/hello", headers={"X-Dashboard-Role": "red"})
    captured = capsys.readouterr()
    # JSON log line includes event="http_request", method=GET, path=/hello, status=200, duration_ms, dashboard_role=red
    assert '"event": "http_request"' in captured.out or '"event":"http_request"' in captured.out
    assert '"method":' in captured.out.replace(" ", "")
    assert '"path":' in captured.out.replace(" ", "") or '"path": ' in captured.out
    assert '"status":' in captured.out.replace(" ", "")
    assert '"duration_ms":' in captured.out.replace(" ", "")
    assert "red" in captured.out  # dashboard_role value


@pytest.mark.asyncio
async def test_middleware_reraises_exception_and_logs(app_with_middleware, capsys):
    """Exception should be logged then re-raised; test verifies log emission."""
    with pytest.raises(Exception):
        async with AsyncClient(
            transport=ASGITransport(app=app_with_middleware), base_url="http://t"
        ) as c:
            await c.get("/boom")
    captured = capsys.readouterr()
    assert "http_request_exception" in captured.out


@pytest.mark.asyncio
async def test_middleware_binds_request_id_to_context(app_with_middleware, capsys):
    """Downstream log calls (inner_handler_log) should include request_id thanks to merge_contextvars."""
    async with AsyncClient(
        transport=ASGITransport(app=app_with_middleware), base_url="http://t"
    ) as c:
        await c.get("/hello", headers={"X-Request-Id": "bind-test-xyz"})
    captured = capsys.readouterr()
    # Both the middleware log and the inner log should carry request_id=bind-test-xyz
    assert "bind-test-xyz" in captured.out
    # Find both event names in output
    assert "inner_handler_log" in captured.out
    assert "http_request" in captured.out

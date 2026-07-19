"""Request-log middleware - SYS-04.

Emits one structlog JSON line per HTTP request with:
 ts, level, event='http_request', method, path, status, duration_ms,
 request_id, dashboard_role, client_ip.

Binds request_id to structlog.contextvars so downstream log calls
(events_listed, tags_patched, graph_queried,...) inherit it automatically
- backend/app/logging.py already includes structlog.contextvars.merge_contextvars
in the processor chain.

: BaseHTTPMiddleware can swallow exceptions. We try/except
around call_next, log explicitly, and re-raise so FastAPI exception handlers
still run.
"""
from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = structlog.get_logger(__name__)


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        # Pick or generate request_id
        incoming = request.headers.get("X-Request-Id")
        request_id = incoming if incoming else str(uuid.uuid4())

        # Bind BEFORE call_next so route handlers inherit request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        # PROD-03: the X-Dashboard-Role reads below are LOGGING-ONLY (observability
        # for forensic review of spoof attempts). They DO NOT influence role filtering
        # - role is derived from the JWT claim in AuthMiddleware + events_query.
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            duration_ms = int((time.perf_counter() - start) * 1000)
            log.exception(
                "http_request_exception",
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms,
                dashboard_role=request.headers.get("X-Dashboard-Role"),
                client_ip=request.client.host if request.client else None,
            )
            raise

        duration_ms = int((time.perf_counter() - start) * 1000)

        log.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=status_code,
            duration_ms=duration_ms,
            dashboard_role=request.headers.get("X-Dashboard-Role"),
            client_ip=request.client.host if request.client else None,
        )

        response.headers["X-Request-Id"] = request_id
        return response

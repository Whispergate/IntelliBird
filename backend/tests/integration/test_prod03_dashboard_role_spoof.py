"""PROD-03 defense-in-depth: X-Dashboard-Role header spoof protection.

Three tests cover both layers of the defense:

Test A — test_app_ignores_x_dashboard_role_header
  Directly against FastAPI (bypassing Caddy): an Analyst holding a JWT with
  dashboard_roles=['blue'] sends `X-Dashboard-Role: red`. The `/api/events`
  response MUST match the Blue-filtered baseline exactly — the header is
  ignored at the app layer.

Test B — test_caddy_strips_x_dashboard_role
  Through a real Caddy container (caddy_harness from plan 13-00). The
  harness's Caddyfile contains `request_header -X-Dashboard-Role` so the
  header never reaches the upstream echo server. An ASGI + uvicorn echo
  app is spun up on 0.0.0.0 inside the test host's network; Caddy proxies
  to it. Assertion: Caddy-forwarded headers do NOT include the spoof.

Test C — test_positive_control_red_jwt
  Same route + fixture as Test A, but with dashboard_roles=['red']. The
  filtered event set MUST differ from the Blue baseline (otherwise Test A
  is a false positive — would pass even if filtering were broken).

Seeded events have discriminating `visibility` values:
  - 'shared' (20 baseline events per project from two_project_fixture)
  - 'red_only' (seeded inline — 5 per project)
  - 'blue_only' (seeded inline — 5 per project)

Blue-claim visibility set: {'shared', 'blue_only'}
Red-claim visibility set:  {'shared', 'red_only'}
No-claim (AUTH_ENABLED=false) visibility set: all three.

Test A + C use the `UserInjectMiddleware` pattern from
`test_events_query_claim.py` — injects request.state.user directly, avoiding
AuthMiddleware's DB-backed token_version cache. A real asyncpg session backs
the events route via the existing `db_session` fixture.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import socket
import threading
import time
import uuid
from contextlib import closing
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(dashboard_roles: list[str]) -> Any:
    """Build an AuthUser dataclass for injection into request.state."""
    from app.security.jwt import AuthUser

    return AuthUser(
        id=str(uuid.uuid4()),
        role="Analyst",
        dashboard_roles=dashboard_roles,
        jti=str(uuid.uuid4()),
        token_version=0,
    )


def _build_events_app_with_user(user_obj: Any, db_session: Any) -> Any:
    """Build a minimal FastAPI app for the events router wired to the live db_session.

    Uses the `UserInjectMiddleware` pattern from test_events_query_claim.py — avoids
    exercising the DB-backed AuthMiddleware (which would require user rows + redis).
    """
    from app.database import get_session
    from app.routers.events import router as events_router
    from starlette.types import ASGIApp, Receive, Scope, Send

    inner = FastAPI()
    inner.include_router(events_router, prefix="/api")

    async def _session_override():
        yield db_session

    inner.dependency_overrides[get_session] = _session_override

    class UserInjectMiddleware:
        def __init__(self, app: ASGIApp, user: Any) -> None:
            self.app = app
            self.user = user

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] == "http" and self.user is not None:
                scope.setdefault("state", {})
                scope["state"]["user"] = self.user
            await self.app(scope, receive, send)

    if user_obj is not None:
        return UserInjectMiddleware(inner, user_obj)
    return inner


async def _seed_visibility_discriminating_events(
    db_session: Any, project_id: uuid.UUID, n_per_visibility: int = 5
) -> None:
    """Add `red_only` and `blue_only` events to the given project.

    Two-project fixture only seeds `visibility='shared'` events. For the positive
    control (Test C) to discriminate Blue from Red, we need events that filter
    differently by dashboard_roles claim.
    """
    from datetime import datetime, timedelta, timezone

    base = datetime.now(timezone.utc) - timedelta(hours=1)
    for vis in ("red_only", "blue_only"):
        for i in range(n_per_visibility):
            eid = uuid.uuid4()
            ch = hashlib.sha256(f"{project_id}:{vis}:{i}:prod03".encode()).hexdigest()
            await db_session.execute(
                text(
                    "INSERT INTO events "
                    "(id, stix_type, project_id, observed_at, title, content_hash, visibility) "
                    "VALUES (:id, 'observed-data', :pid, :obs, :title, :ch, :vis)"
                ),
                {
                    "id": eid,
                    "pid": project_id,
                    "obs": base + timedelta(seconds=i),
                    "title": f"prod03-{vis}-{i}",
                    "ch": ch,
                    "vis": vis,
                },
            )
    await db_session.commit()


# ---------------------------------------------------------------------------
# Test A — FastAPI ignores spoofed X-Dashboard-Role
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_app_ignores_x_dashboard_role_header(two_project_fixture, db_session):
    """Blue-role JWT + spoofed X-Dashboard-Role: red MUST match Blue baseline."""
    fx = two_project_fixture
    await _seed_visibility_discriminating_events(db_session, fx.project_a.id)

    blue_user = _make_user(["blue"])
    app = _build_events_app_with_user(blue_user, db_session)

    # Do NOT pass `project_id` — the scope-intersection predicate returns
    # `false` when no ProjectScopeRow(intel_scope=true) rows exist, which
    # would mask the visibility-filter discriminator we're measuring here.
    # The visibility filter is orthogonal to project scoping, so this test
    # stays focused on the dashboard_roles claim path.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # Baseline: no spoof header.
        r_baseline = await c.get("/api/events", params={"limit": 500})
        assert r_baseline.status_code == 200, r_baseline.text
        baseline_items = r_baseline.json()["items"]
        baseline_ids = sorted(e["id"] for e in baseline_items)
        baseline_vis = {e["visibility"] for e in baseline_items}

        # Spoof: send X-Dashboard-Role: red while JWT claim is Blue.
        r_spoof = await c.get(
            "/api/events",
            params={"limit": 500},
            headers={"X-Dashboard-Role": "red"},
        )
        assert r_spoof.status_code == 200, r_spoof.text
        spoof_ids = sorted(e["id"] for e in r_spoof.json()["items"])

    # Must have events to assert anything meaningful.
    assert len(baseline_ids) > 0, "baseline returned 0 events — fixture seed likely failed"

    assert spoof_ids == baseline_ids, (
        "Spoof header altered response — FastAPI is reading X-Dashboard-Role. "
        f"baseline={len(baseline_ids)} spoof={len(spoof_ids)}"
    )
    # Positive discriminator within this test: Blue view must NEVER include
    # red_only visibility events and MUST include blue_only events (proving
    # the filter is actually running).
    assert "red_only" not in baseline_vis, (
        f"Blue-role response leaked red_only events: {baseline_vis}"
    )
    assert "blue_only" in baseline_vis, (
        f"Blue-role response missing blue_only events: {baseline_vis}"
    )


# ---------------------------------------------------------------------------
# Test C — positive control (Red JWT returns a discriminating shape)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_positive_control_red_jwt(two_project_fixture, db_session):
    """Red-role JWT produces a DIFFERENT filtered set than Blue-role JWT.

    Confirms the visibility filter actually discriminates by dashboard_roles —
    rules out a false-positive in Test A where Blue == Red would let a broken
    filter pass silently.
    """
    fx = two_project_fixture
    await _seed_visibility_discriminating_events(db_session, fx.project_a.id)

    blue_user = _make_user(["blue"])
    red_user = _make_user(["red"])

    app_blue = _build_events_app_with_user(blue_user, db_session)
    app_red = _build_events_app_with_user(red_user, db_session)

    # No project_id filter — see explanation in test_app_ignores_...
    async with AsyncClient(
        transport=ASGITransport(app=app_blue), base_url="http://test"
    ) as c_blue:
        r_blue = await c_blue.get("/api/events", params={"limit": 500})
    async with AsyncClient(
        transport=ASGITransport(app=app_red), base_url="http://test"
    ) as c_red:
        r_red = await c_red.get("/api/events", params={"limit": 500})

    assert r_blue.status_code == 200, r_blue.text
    assert r_red.status_code == 200, r_red.text

    blue_vis = {e["visibility"] for e in r_blue.json()["items"]}
    red_vis = {e["visibility"] for e in r_red.json()["items"]}

    # Blue view: shared + blue_only (no red_only)
    assert "red_only" not in blue_vis, f"Blue leaked red_only: {blue_vis}"
    assert "blue_only" in blue_vis, f"Blue missing blue_only: {blue_vis}"
    # Red view: shared + red_only (no blue_only)
    assert "blue_only" not in red_vis, f"Red leaked blue_only: {red_vis}"
    assert "red_only" in red_vis, f"Red missing red_only: {red_vis}"

    # Hard discriminator: the id sets MUST differ — otherwise Test A proves nothing.
    blue_ids = {e["id"] for e in r_blue.json()["items"]}
    red_ids = {e["id"] for e in r_red.json()["items"]}
    assert blue_ids != red_ids, (
        "Blue and Red id sets are identical — the dashboard_roles filter does "
        "not discriminate, so the spoof test in Test A is a false positive."
    )


# ---------------------------------------------------------------------------
# Test B — Caddy strips X-Dashboard-Role at the edge
# ---------------------------------------------------------------------------

def _free_tcp_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("0.0.0.0", 0))
        return s.getsockname()[1]


def _host_ip_for_docker() -> str:
    """Return an IP that a Docker container on the default bridge can reach back to.

    On Linux CI runners `host.docker.internal` is not guaranteed, so we resolve
    the local primary-route IP via a UDP socket trick (no packet sent).
    """
    with closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as s:
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


class _EchoAppServer:
    """A tiny uvicorn server that runs a FastAPI echo app on a background thread.

    Registered only inside this test module — it is NOT added to backend/app/main.py,
    so production router registration is unaffected.
    """

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._thread: threading.Thread | None = None
        self._server: Any = None

    def _build_app(self) -> FastAPI:
        app = FastAPI()

        @app.get("/_test/echo-headers")
        async def echo(req: Request) -> dict[str, Any]:
            return {"received_headers": dict(req.headers)}

        return app

    def start(self) -> None:
        import uvicorn

        config = uvicorn.Config(
            self._build_app(),
            host=self.host,
            port=self.port,
            log_level="warning",
            lifespan="off",
        )
        self._server = uvicorn.Server(config)

        def _run() -> None:
            asyncio.run(self._server.serve())

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

        # Wait for server to bind — poll TCP connect up to ~5s.
        deadline = time.time() + 5.0
        while time.time() < deadline:
            try:
                with closing(socket.create_connection((self.host, self.port), timeout=0.5)):
                    return
            except OSError:
                time.sleep(0.05)
        raise RuntimeError(f"echo server did not start on {self.host}:{self.port}")

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5.0)


@pytest_asyncio.fixture
async def _echo_server():
    """Spin an ephemeral echo FastAPI server, bound 0.0.0.0 on a free port."""
    port = _free_tcp_port()
    server = _EchoAppServer(host="0.0.0.0", port=port)
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.mark.asyncio
async def test_caddy_strips_x_dashboard_role(_echo_server):
    """Caddy must strip X-Dashboard-Role before forwarding to the upstream api."""
    from tests.integration.fixtures.caddy_harness import caddy_harness

    upstream_host = _host_ip_for_docker()

    # CI / local envs may not have caddy:2.8-alpine pre-pulled — allow override
    # via env var. Default falls back to a commonly present 2.x tag.
    caddy_image = os.environ.get("PROD03_CADDY_IMAGE", "caddy:2-alpine")
    with caddy_harness(
        upstream_host=upstream_host,
        upstream_port=_echo_server.port,
        image=caddy_image,
    ) as harness:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Give Caddy a moment to be ready (wait_for_logs already tried).
            r = await client.get(
                f"{harness.proxy_url}/_test/echo-headers",
                headers={"X-Dashboard-Role": "red"},
            )
    assert r.status_code == 200, r.text
    received = r.json()["received_headers"]
    received_lower = {k.lower() for k in received.keys()}
    assert "x-dashboard-role" not in received_lower, (
        "Caddy did not strip X-Dashboard-Role — the edge defense layer is broken. "
        f"received headers: {sorted(received_lower)}"
    )

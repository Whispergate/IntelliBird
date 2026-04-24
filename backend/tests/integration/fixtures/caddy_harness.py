"""PROD-03 Caddy testcontainer harness.

Spins a Caddy container that reverse-proxies to an upstream (test api host/port)
with the PROD-03 `request_header -X-Dashboard-Role` strip applied. Used by
Phase 13 plan 03 to assert Caddy strips the spoofed header before it reaches
the FastAPI app.

Important:
- No ACME / Let's Encrypt. Uses `auto_https off` + plain `http://` site address
  so the harness works in CI (per Phase 13 RESEARCH §Pitfall 3).
- No top-level I/O — the Caddyfile is only written when the context manager is
  entered, so merely importing this module has zero side effects.
- Idempotent: multiple enters create fresh Caddyfile tempfiles.

Usage:
    with caddy_harness(upstream_host="host.docker.internal", upstream_port=8000) as h:
        r = httpx.get(h.proxy_url + "/api/events", headers={"X-Dashboard-Role": "red"})
        # FastAPI at :8000 will NOT see the X-Dashboard-Role header.
"""
from __future__ import annotations

import contextlib
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator

CADDY_IMAGE = "caddy:2.8-alpine"
CADDYFILE_TEMPLATE = """\
{{
    auto_https off
    admin off
}}

:80 {{
    # PROD-03: strip client-supplied role hint at the edge (defense in depth).
    # FastAPI also ignores this header; this strip is belt-and-braces.
    request_header -X-Dashboard-Role

    reverse_proxy {upstream_host}:{upstream_port}
}}
"""


def _write_caddyfile(upstream_host: str, upstream_port: int) -> Path:
    tmpdir = Path(tempfile.mkdtemp(prefix="prod03-caddy-"))
    caddyfile = tmpdir / "Caddyfile"
    caddyfile.write_text(
        CADDYFILE_TEMPLATE.format(
            upstream_host=upstream_host, upstream_port=upstream_port
        )
    )
    return caddyfile


@contextlib.contextmanager
def caddy_harness(
    upstream_host: str,
    upstream_port: int,
    image: str = CADDY_IMAGE,
) -> Iterator[SimpleNamespace]:
    """Start a Caddy container proxying to upstream_host:upstream_port.

    Yields a SimpleNamespace with:
      .proxy_url — `http://{host}:{mapped_port}` the test client should call
      .container — the underlying DockerContainer (if caller needs logs)
      .stop()    — explicit stop hook (also called on exit)

    The container is cleaned up on `__exit__` regardless of exception.
    """
    # Import lazily — avoids requiring testcontainers at module import time.
    from testcontainers.core.container import DockerContainer
    from testcontainers.core.waiting_utils import wait_for_logs

    caddyfile = _write_caddyfile(upstream_host, upstream_port)

    container = (
        DockerContainer(image)
        .with_bind_ports(80, None)
        .with_volume_mapping(str(caddyfile), "/etc/caddy/Caddyfile", "ro")
    )
    container.start()
    try:
        # Caddy 2.x logs "serving initial configuration" once ready.
        try:
            wait_for_logs(container, "serving initial configuration", timeout=20)
        except Exception:
            # Fall back to any log-line heuristic; image tags vary across releases.
            pass

        mapped = container.get_exposed_port(80)
        host = container.get_container_host_ip()
        proxy_url = f"http://{host}:{mapped}"

        def _stop() -> None:
            try:
                container.stop()
            except Exception:
                pass

        yield SimpleNamespace(
            proxy_url=proxy_url,
            container=container,
            stop=_stop,
        )
    finally:
        try:
            container.stop()
        except Exception:
            pass

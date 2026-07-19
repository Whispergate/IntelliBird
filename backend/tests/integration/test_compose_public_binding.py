"""PROD-07: docker-compose public-binding matrix.

Asserts that after plan 13-04, only the `caddy` service publishes host
ports 80/443 and the `api`/`web` services no longer publish any host port.
Parses `docker compose -f ops/docker-compose.yml config --format json` and
inspects the normalised `ports` array on each service.

Skips cleanly if `docker compose` is unavailable (CI without docker). Does
NOT skip if docker is present - a real failure of this test is a PROD-07
regression.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_FILE = REPO_ROOT / "ops" / "docker-compose.yml"


def _docker_compose_available() -> bool:
    docker = shutil.which("docker")
    if docker is None:
        return False
    try:
        result = subprocess.run(
            [docker, "compose", "version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


pytestmark = pytest.mark.skipif(
    not _docker_compose_available(),
    reason="docker compose not available on this host",
)


def _load_compose_config() -> dict:
    assert COMPOSE_FILE.exists(), f"compose file missing at {COMPOSE_FILE}"
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "config", "--format", "json"],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(COMPOSE_FILE.parent),
    )
    return json.loads(result.stdout)


def _published_ports(svc_def: dict) -> list[str]:
    """Return the set of published host ports (as strings) for a service."""
    out: list[str] = []
    for p in svc_def.get("ports", []) or []:
        # Compose v2 `config --format json` normalises ports to objects with
        # `published`, `target`, `protocol`, `mode`, `host_ip` keys. Older
        # formats / string short-syntax may also appear.
        if isinstance(p, dict):
            pub = p.get("published")
            if pub is not None:
                out.append(str(pub))
        elif isinstance(p, str):
            # short syntax "80:80" or "127.0.0.1:8000:8000"
            parts = p.split(":")
            if len(parts) >= 2:
                out.append(parts[-2])
    return out


def _public_port_publishers(config: dict) -> set[str]:
    """Return the set of service names that publish host port 80 or 443."""
    services = config.get("services", {})
    publishers: set[str] = set()
    for name, svc in services.items():
        pubs = _published_ports(svc)
        if any(p in ("80", "443") for p in pubs):
            publishers.add(name)
    return publishers


def test_only_caddy_publishes_public_ports() -> None:
    """Exactly the caddy service publishes 80 / 443 on the host."""
    config = _load_compose_config()
    publishers = _public_port_publishers(config)
    assert publishers == {"caddy"}, (
        f"expected {{'caddy'}} to be the sole publisher of 80/443; got {publishers}. "
        "PROD-07 requires Caddy to be the single public edge."
    )


def test_api_service_has_no_host_publish() -> None:
    """api service has no host-port publish at the top level (compose-network-internal)."""
    config = _load_compose_config()
    api = config["services"]["api"]
    pubs = _published_ports(api)
    assert pubs == [], (
        f"api service must not publish any host port at top level; got {pubs}. "
        "PROD-07 flip: api is reachable only via the caddy reverse proxy."
    )


def test_web_service_has_no_host_publish() -> None:
    """web service has no host-port publish at the top level."""
    config = _load_compose_config()
    web = config["services"]["web"]
    pubs = _published_ports(web)
    assert pubs == [], (
        f"web service must not publish any host port at top level; got {pubs}. "
        "PROD-07 flip: web is reachable only via the caddy reverse proxy."
    )


def test_caddy_publishes_both_80_and_443() -> None:
    """caddy publishes BOTH 80 and 443 (ACME HTTP-01 needs 80; TLS needs 443)."""
    config = _load_compose_config()
    caddy = config["services"].get("caddy")
    assert caddy is not None, "caddy service missing from compose"
    pubs = set(_published_ports(caddy))
    assert {"80", "443"}.issubset(pubs), (
        f"caddy must publish both 80 and 443; got {pubs}"
    )

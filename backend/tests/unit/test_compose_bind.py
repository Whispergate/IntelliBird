"""Compose bind-address regression test.

Validates FN + FN: the compose file declares all six
services and every host-side port publish is bound to 127.0.0.1 only.

This is a static test over ops/docker-compose.yml — no containers are
launched.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_PATH = REPO_ROOT / "ops" / "docker-compose.yml"

# Core services required for the M1/M2 stack. Phase 9 added Authentik
# (authentik-db/server/worker) + GeoIP auto-update (geoip-update). This assertion
# requires the core set be present; additional services are tolerated.
REQUIRED_SERVICES = {"db", "redis", "api", "worker", "scheduler", "web"}


@pytest.fixture(scope="module")
def compose() -> dict:
    assert COMPOSE_PATH.exists(), f"Missing {COMPOSE_PATH}"
    return yaml.safe_load(COMPOSE_PATH.read_text())


def test_all_six_services_present(compose: dict) -> None:
    actual = set(compose["services"].keys())
    missing = REQUIRED_SERVICES - actual
    assert not missing, f"missing required services: {missing}"


def test_every_port_is_loopback_only(compose: dict) -> None:
    offenders: list[tuple[str, str]] = []
    for name, svc in compose["services"].items():
        for entry in svc.get("ports", []):
            p = entry if isinstance(entry, str) else entry.get("published", "")
            if not str(p).startswith("127.0.0.1:"):
                offenders.append((name, str(entry)))
    assert not offenders, f"non-loopback port bindings: {offenders}"


def test_db_redis_api_have_healthchecks(compose: dict) -> None:
    for name in ("db", "redis", "api"):
        assert "healthcheck" in compose["services"][name], f"{name} missing healthcheck"


def test_worker_scheduler_depend_on_healthy_api(compose: dict) -> None:
    for name in ("worker", "scheduler"):
        deps = compose["services"][name].get("depends_on", {})
        assert "api" in deps, f"{name} must depend_on api"
        assert deps["api"]["condition"] == "service_healthy", (
            f"{name}.depends_on.api must require service_healthy"
        )

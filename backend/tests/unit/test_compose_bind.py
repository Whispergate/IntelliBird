"""Compose bind-address regression test.

Validates FND-01 + FND-04: the compose file declares all six Phase 1
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

REQUIRED_SERVICES = {"db", "redis", "api", "worker", "scheduler", "web"}


@pytest.fixture(scope="module")
def compose() -> dict:
    assert COMPOSE_PATH.exists(), f"Missing {COMPOSE_PATH}"
    return yaml.safe_load(COMPOSE_PATH.read_text())


def test_all_six_services_present(compose: dict) -> None:
    actual = set(compose["services"].keys())
    assert actual == REQUIRED_SERVICES, f"services mismatch: {actual}"


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

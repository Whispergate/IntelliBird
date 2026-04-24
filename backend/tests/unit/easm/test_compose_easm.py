"""Regression tests for ops/docker-compose.yml — easm-worker isolation.

Guards PITFALLS §Pitfall 7: /var/run/docker.sock MUST be scoped to easm-worker only.
Two-layer defence (YAML structure + service-by-service check) so an accidental
copy-paste of the mount to api/worker/scheduler fails this regression test.
"""
from __future__ import annotations
from pathlib import Path
import yaml

COMPOSE_PATH = Path(__file__).resolve().parents[4] / "ops" / "docker-compose.yml"

DOCKER_SOCK = "/var/run/docker.sock"


def _load_compose() -> dict:
    with COMPOSE_PATH.open() as f:
        return yaml.safe_load(f)


def test_easm_worker_service_exists():
    compose = _load_compose()
    assert "easm-worker" in compose.get("services", {}), (
        f"easm-worker service missing from {COMPOSE_PATH}"
    )


def test_easm_worker_command_targets_easm_queue_only():
    compose = _load_compose()
    cmd = compose["services"]["easm-worker"].get("command", "")
    # command may be string OR list; normalise
    cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
    assert "--queues easm" in cmd_str, f"easm-worker must run dramatiq on easm queue only; got: {cmd_str}"


def test_easm_worker_mounts_docker_sock():
    compose = _load_compose()
    volumes = compose["services"]["easm-worker"].get("volumes", [])
    assert any(DOCKER_SOCK in str(v) for v in volumes), (
        f"easm-worker missing {DOCKER_SOCK} mount — cannot launch BBOT subprocess"
    )


def test_easm_worker_mounts_bbot_scans_volume():
    compose = _load_compose()
    volumes = compose["services"]["easm-worker"].get("volumes", [])
    assert any("bbot_scans:/bbot/scans" in str(v) for v in volumes), (
        "easm-worker missing bbot_scans volume mount"
    )


def test_easm_worker_depends_on_redis_and_db():
    compose = _load_compose()
    dep = compose["services"]["easm-worker"].get("depends_on", [])
    # depends_on may be list or dict
    dep_names = list(dep.keys()) if isinstance(dep, dict) else list(dep)
    assert "redis" in dep_names, f"easm-worker must depend on redis; got {dep_names}"
    assert "db" in dep_names, f"easm-worker must depend on db; got {dep_names}"


def test_bbot_scans_volume_declared_at_root():
    compose = _load_compose()
    volumes_root = compose.get("volumes", {}) or {}
    assert "bbot_scans" in volumes_root, (
        "bbot_scans named volume not declared in root volumes: section"
    )


def test_docker_sock_not_mounted_on_api_service():
    compose = _load_compose()
    api_volumes = compose["services"].get("api", {}).get("volumes", []) or []
    for v in api_volumes:
        assert DOCKER_SOCK not in str(v), (
            f"PITFALLS §Pitfall 7: api service MUST NOT mount {DOCKER_SOCK}; "
            f"docker socket access is elevated-privilege and easm-worker only"
        )


def test_docker_sock_not_mounted_on_worker_service():
    compose = _load_compose()
    worker_volumes = compose["services"].get("worker", {}).get("volumes", []) or []
    for v in worker_volumes:
        assert DOCKER_SOCK not in str(v), (
            f"PITFALLS §Pitfall 7: worker service MUST NOT mount {DOCKER_SOCK}"
        )


def test_docker_sock_not_mounted_on_scheduler_service():
    compose = _load_compose()
    if "scheduler" not in compose["services"]:
        return  # scheduler may be merged into worker in some configs
    sched_volumes = compose["services"]["scheduler"].get("volumes", []) or []
    for v in sched_volumes:
        assert DOCKER_SOCK not in str(v), (
            f"PITFALLS §Pitfall 7: scheduler service MUST NOT mount {DOCKER_SOCK}"
        )

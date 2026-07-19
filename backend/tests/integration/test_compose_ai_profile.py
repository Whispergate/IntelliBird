"""AI-05 - docker-compose --profile ai YAML validation tests.

Covers:
  - Ollama service has profiles: [ai]
  - ollama_models named volume is declared and mounted at /root/.ollama
  - GPU deploy.resources.reservations.devices block with driver: nvidia is present
    (commented-out block counts - we read the raw YAML text for this assertion)
  - api service has OLLAMA_BASE_URL environment variable

Uses `docker compose -f ops/docker-compose.yml --profile ai config --format json`
to parse the normalised config, plus a direct raw YAML text check for the
GPU block (which is commented-out by default).

Skips cleanly when `docker compose` is unavailable on the runner (mirrors the
test_compose_public_binding.py pattern).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_FILE = REPO_ROOT / "ops" / "docker-compose.yml"

pytestmark = pytest.mark.integration


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


_HAS_DOCKER_COMPOSE = _docker_compose_available()


def _load_compose_config_with_ai_profile() -> dict:
    """Return the normalised JSON config with --profile ai active."""
    assert COMPOSE_FILE.exists(), f"compose file missing at {COMPOSE_FILE}"
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "--profile",
            "ai",
            "config",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(COMPOSE_FILE.parent),
        env={
            # Provide mandatory env vars so the config step doesn't fail on
            # missing required variables (e.g. JWT_SIGNING_KEY required)
            **__import__("os").environ,
            "JWT_SIGNING_KEY": "ci-test-signing-key",
            "AUTH_SECRET": "ci-test-auth-secret",
            "AUTHENTIK_PG_PASS": "ci-test-pg-pass",
            "AUTHENTIK_SECRET_KEY": "ci-test-authentik-key",
        },
    )
    return json.loads(result.stdout)


def test_ollama_service_has_profile_ai() -> None:
    """docker-compose.yml defines an 'ollama' service with profiles: [ai]."""
    if not _HAS_DOCKER_COMPOSE:
        pytest.skip("docker compose not available on this host")

    config = _load_compose_config_with_ai_profile()
    services = config.get("services", {})

    assert "ollama" in services, (
        "Expected 'ollama' service in docker-compose.yml --profile ai config; "
        f"found services: {list(services.keys())}"
    )

    ollama_svc = services["ollama"]
    profiles = ollama_svc.get("profiles") or []
    assert "ai" in profiles, (
        f"ollama service must have profiles: [ai] but got profiles={profiles!r}"
    )


def test_ollama_models_named_volume() -> None:
    """Ollama service uses a named volume 'ollama_models' mounted at /root/.ollama."""
    if not _HAS_DOCKER_COMPOSE:
        pytest.skip("docker compose not available on this host")

    config = _load_compose_config_with_ai_profile()
    services = config.get("services", {})
    assert "ollama" in services, "ollama service missing from compose config"

    ollama_svc = services["ollama"]
    volumes = ollama_svc.get("volumes") or []

    # Normalised Compose v2 JSON: volumes are objects with 'source', 'target', 'type'
    # or short strings "name:/path". Handle both.
    volume_mounts = []
    for v in volumes:
        if isinstance(v, dict):
            volume_mounts.append((v.get("source", ""), v.get("target", "")))
        elif isinstance(v, str):
            parts = v.split(":")
            if len(parts) >= 2:
                volume_mounts.append((parts[0], parts[1]))
            else:
                volume_mounts.append((v, ""))

    sources = [src for src, _ in volume_mounts]
    [tgt for _, tgt in volume_mounts]

    assert "ollama_models" in sources, (
        f"ollama service must mount the 'ollama_models' named volume; "
        f"found volume sources: {sources!r}"
    )

    # Also verify it mounts to /root/.ollama
    matched_target = next(
        (tgt for src, tgt in volume_mounts if src == "ollama_models"), None
    )
    assert matched_target == "/root/.ollama", (
        f"ollama_models volume must be mounted at /root/.ollama; "
        f"got target={matched_target!r}"
    )

    # The named volume must appear in the top-level volumes declaration
    top_volumes = config.get("volumes") or {}
    assert "ollama_models" in top_volumes, (
        f"'ollama_models' must be declared in the top-level volumes section; "
        f"found: {list(top_volumes.keys())}"
    )


def test_gpu_deploy_block_documented_or_present() -> None:
    """GPU deploy block (driver: nvidia) is present or commented-out in docker-compose.yml.

    The default CPU-only deployment ships with the block commented so operators
    can uncomment after installing nvidia-container-toolkit. We validate the
    raw YAML text rather than the parsed config (comments are stripped from JSON).
    """
    assert COMPOSE_FILE.exists(), f"compose file missing at {COMPOSE_FILE}"
    raw = COMPOSE_FILE.read_text()

    # Look for nvidia driver reference in the ollama service block
    # Accept both active YAML and the commented-out form: '# - driver: nvidia'
    has_nvidia_block = (
        "driver: nvidia" in raw
        or "driver:nvidia" in raw
    )
    assert has_nvidia_block, (
        "ops/docker-compose.yml must contain a GPU passthrough block "
        "(driver: nvidia) under the ollama service - "
        "either active or commented-out for CPU-only hosts. "
        "See docs/ops/ai-providers.md §GPU passthrough."
    )


def test_api_service_has_ollama_base_url_env() -> None:
    """api service in docker-compose.yml has OLLAMA_BASE_URL environment variable."""
    if not _HAS_DOCKER_COMPOSE:
        pytest.skip("docker compose not available on this host")

    config = _load_compose_config_with_ai_profile()
    services = config.get("services", {})
    assert "api" in services, "api service missing from compose config"

    api_svc = services["api"]
    env = api_svc.get("environment") or {}
    # Normalised compose JSON: environment is a dict or list of "KEY=val" strings.
    if isinstance(env, list):
        env_keys = {item.split("=", 1)[0] for item in env if "=" in item}
    else:
        env_keys = set(env.keys())

    assert "OLLAMA_BASE_URL" in env_keys, (
        f"api service must declare OLLAMA_BASE_URL in its environment block; "
        f"found keys: {sorted(env_keys)}"
    )

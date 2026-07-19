"""Compose / Dockerfile regression: brand-monitor queue + dnstwist installed.

Static validation over ops/docker-compose.yml + ops/api.Dockerfile +
backend/pyproject.toml. No containers are launched.

Guards against future drift of the BRP-02 ops wiring:

1. The `worker` service command must include the `brand-monitor` queue in its
   Dramatiq `--queues` list (co-located with ingest/maintenance/webhooks -
   dnstwist runs in-process; no docker.sock mount contrast BBOT).

2. `dnstwist` must be a declared dependency of the runtime image. The project
   uses `uv sync` against `backend/pyproject.toml` inside api.Dockerfile, so
   the authoritative dependency declaration lives in `pyproject.toml`. We also
   tolerate a `requirements.txt` fallback or an explicit `pip install dnstwist`
   line in the Dockerfile to stay flexible across packaging strategies.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_PATH = REPO_ROOT / "ops" / "docker-compose.yml"
DOCKERFILE_PATH = REPO_ROOT / "ops" / "api.Dockerfile"
PYPROJECT_PATH = REPO_ROOT / "backend" / "pyproject.toml"
REQUIREMENTS_PATH = REPO_ROOT / "backend" / "requirements.txt"


@pytest.fixture(scope="module")
def compose() -> dict:
    assert COMPOSE_PATH.exists(), f"Missing {COMPOSE_PATH}"
    return yaml.safe_load(COMPOSE_PATH.read_text())


def _cmd_tokens(svc: dict) -> list[str]:
    """Normalise a compose service `command` (list or shell-string) into tokens."""
    cmd = svc.get("command")
    if cmd is None:
        return []
    if isinstance(cmd, list):
        # Flatten any embedded whitespace tokens (e.g. ["sh", "-c", "a b"])
        out: list[str] = []
        for item in cmd:
            out.extend(str(item).split())
        return out
    return str(cmd).split()


def test_worker_queues_include_brand_monitor(compose: dict) -> None:
    worker = compose["services"]["worker"]
    tokens = _cmd_tokens(worker)
    assert "--queues" in tokens, (
        f"worker command missing --queues flag: {worker.get('command')!r}"
    )
    # Everything after --queues up to the next flag is the queue list.
    qs_start = tokens.index("--queues") + 1
    queues: list[str] = []
    for tok in tokens[qs_start:]:
        if tok.startswith("--"):
            break
        queues.append(tok)
    assert "brand-monitor" in queues, (
        f"worker --queues list missing 'brand-monitor' (got {queues!r})"
    )


def test_brand_monitor_queue_not_on_easm_worker(compose: dict) -> None:
    """brand-monitor must NOT be on easm-worker - that service holds the
    docker.sock mount and is scoped to the `easm` queue only."""
    easm = compose["services"].get("easm-worker")
    if easm is None:  # easm-worker may be behind a profile in some environments
        pytest.skip("easm-worker not declared in this compose file")
    tokens = _cmd_tokens(easm)
    if "--queues" in tokens:
        qs_start = tokens.index("--queues") + 1
        queues: list[str] = []
        for tok in tokens[qs_start:]:
            if tok.startswith("--"):
                break
            queues.append(tok)
        assert "brand-monitor" not in queues, (
            "brand-monitor must not be handled by easm-worker (scope/privilege leak)"
        )


def test_dnstwist_is_installed_in_image() -> None:
    sources: list[str] = []
    if DOCKERFILE_PATH.exists():
        sources.append(DOCKERFILE_PATH.read_text())
    if PYPROJECT_PATH.exists():
        sources.append(PYPROJECT_PATH.read_text())
    if REQUIREMENTS_PATH.exists():
        sources.append(REQUIREMENTS_PATH.read_text())
    haystack = "\n".join(sources)
    assert "dnstwist" in haystack, (
        "dnstwist not found in api.Dockerfile, pyproject.toml, or requirements.txt"
    )
    # Stronger check: a real dependency declaration exists somewhere, not
    # just a bare mention in a Dockerfile comment. pyproject.toml entries
    # look like 'dnstwist>=...' or 'dnstwist = ...'. requirements.txt lines
    # start with 'dnstwist'. Dockerfile pip install lines contain 'pip'
    # and 'dnstwist' on the same line.
    strong_match = False
    if PYPROJECT_PATH.exists():
        py = PYPROJECT_PATH.read_text()
        for line in py.splitlines():
            stripped = line.strip().lstrip('"').lstrip("'")
            if stripped.startswith("dnstwist"):
                strong_match = True
                break
    if not strong_match and REQUIREMENTS_PATH.exists():
        for line in REQUIREMENTS_PATH.read_text().splitlines():
            if line.strip().lower().startswith("dnstwist"):
                strong_match = True
                break
    if not strong_match and DOCKERFILE_PATH.exists():
        for line in DOCKERFILE_PATH.read_text().splitlines():
            low = line.lower()
            if "pip install" in low and "dnstwist" in low:
                strong_match = True
                break
    assert strong_match, (
        "dnstwist must be a real dependency declaration (pyproject.toml / "
        "requirements.txt / pip install line), not only mentioned in comments"
    )

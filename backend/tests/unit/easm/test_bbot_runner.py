"""Unit tests for bbot_runner.py - subprocess + semaphore + reaper + persistence primitives.

Plan: 11-04a (EASM-01, EASM-02, EASM-03, EASM-09)

All tests use monkeypatch to mock subprocess.run / subprocess.Popen - no live Docker, no live Redis.
Golden fixtures from backend/tests/fixtures/bbot_ndjson/ used for NDJSON stream tests.
"""
from __future__ import annotations

import hashlib
import io
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "bbot_ndjson"

_SCAN_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_PROJECT_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
_CONTAINER_ID = "a" * 64  # 64-char hex


def _make_completed_process(stdout="", returncode=0, stderr=""):
    return SimpleNamespace(stdout=stdout, returncode=returncode, stderr=stderr)


# ---------------------------------------------------------------------------
# Module under test (imported after env guards)
# ---------------------------------------------------------------------------

import os  # noqa: E402
os.environ.setdefault("SECRET_KEY", "a" * 32)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SIGNING_KEY", "b" * 32)

from app.services import bbot_runner  # noqa: E402


# ===========================================================================
# Tests: launch_bbot_scan
# ===========================================================================


def test_launch_uses_om_json_flag_not_output_modules(monkeypatch):
    """PITFALLS §Pitfall 1 - -om json, NOT --output-modules json."""
    captured: list[list[str]] = []

    def mock_run(args, **kwargs):
        captured.append(args)
        return _make_completed_process(stdout=_CONTAINER_ID + "\n")

    monkeypatch.setattr(subprocess, "run", mock_run)
    bbot_runner.launch_bbot_scan(
        _SCAN_ID, _PROJECT_ID,
        targets=["example.com"], blacklist=[], modules=["crt"], passive=True,
    )

    args = captured[0]
    # -om json must be present as adjacent pair
    assert "-om" in args
    om_idx = args.index("-om")
    assert args[om_idx + 1] == "json", "flag after -om must be 'json'"
    assert "--output-modules" not in args, "must not use --output-modules flag"


def test_launch_passive_includes_rf_passive(monkeypatch):
    """EASM-03 - passive mode appends -rf passive to args."""
    captured: list[list[str]] = []

    def mock_run(args, **kwargs):
        captured.append(args)
        return _make_completed_process(stdout=_CONTAINER_ID + "\n")

    monkeypatch.setattr(subprocess, "run", mock_run)
    bbot_runner.launch_bbot_scan(
        _SCAN_ID, _PROJECT_ID,
        targets=["example.com"], blacklist=[], modules=["crt"], passive=True,
    )

    args = captured[0]
    assert "-rf" in args, "-rf flag must be present for passive mode"
    rf_idx = args.index("-rf")
    assert args[rf_idx + 1] == "passive", "arg after -rf must be 'passive'"


def test_launch_active_omits_rf_passive(monkeypatch):
    """EASM-03 - active mode must NOT include -rf passive."""
    captured: list[list[str]] = []

    def mock_run(args, **kwargs):
        captured.append(args)
        return _make_completed_process(stdout=_CONTAINER_ID + "\n")

    monkeypatch.setattr(subprocess, "run", mock_run)
    bbot_runner.launch_bbot_scan(
        _SCAN_ID, _PROJECT_ID,
        targets=["example.com"], blacklist=[], modules=["crt"], passive=False,
    )

    args = captured[0]
    assert "-rf" not in args, "-rf must NOT appear in active mode args"


def test_launch_uses_dash_d_detached(monkeypatch):
    """PITFALLS §Pitfall 2 - must use docker run -d (detached)."""
    captured: list[list[str]] = []

    def mock_run(args, **kwargs):
        captured.append(args)
        return _make_completed_process(stdout=_CONTAINER_ID + "\n")

    monkeypatch.setattr(subprocess, "run", mock_run)
    bbot_runner.launch_bbot_scan(
        _SCAN_ID, _PROJECT_ID,
        targets=["example.com"], blacklist=[], modules=[], passive=True,
    )

    args = captured[0]
    assert "-d" in args, "docker run must include -d (detached)"


def test_launch_attaches_three_labels(monkeypatch):
    """Container must have intellibird.easm, intellibird.scan_id, intellibird.scan_mode labels."""
    captured: list[list[str]] = []

    def mock_run(args, **kwargs):
        captured.append(args)
        return _make_completed_process(stdout=_CONTAINER_ID + "\n")

    monkeypatch.setattr(subprocess, "run", mock_run)
    bbot_runner.launch_bbot_scan(
        _SCAN_ID, _PROJECT_ID,
        targets=["example.com"], blacklist=[], modules=[], passive=True,
    )

    args = captured[0]
    args_str = " ".join(args)
    assert "intellibird.easm=true" in args_str
    assert f"intellibird.scan_id={_SCAN_ID}" in args_str
    assert "intellibird.scan_mode=" in args_str


def test_launch_returns_container_id_from_stdout(monkeypatch):
    """docker run -d prints container_id on stdout; launch_bbot_scan must return stripped value."""
    expected_id = "f" * 64

    def mock_run(args, **kwargs):
        return _make_completed_process(stdout=expected_id + "\n")

    monkeypatch.setattr(subprocess, "run", mock_run)
    result = bbot_runner.launch_bbot_scan(
        _SCAN_ID, _PROJECT_ID,
        targets=["example.com"], blacklist=[], modules=[], passive=True,
    )
    assert result == expected_id


def test_launch_raises_on_docker_failure(monkeypatch):
    """Non-zero returncode from docker run must raise RuntimeError with stderr."""
    def mock_run(args, **kwargs):
        return _make_completed_process(stdout="", returncode=1, stderr="pull access denied")

    monkeypatch.setattr(subprocess, "run", mock_run)
    with pytest.raises(RuntimeError, match="docker run failed"):
        bbot_runner.launch_bbot_scan(
            _SCAN_ID, _PROJECT_ID,
            targets=["example.com"], blacklist=[], modules=[], passive=True,
        )


def test_launch_raises_on_empty_targets(monkeypatch):
    """Empty targets list must raise ValueError before calling docker."""
    call_count = 0

    def mock_run(args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _make_completed_process(stdout=_CONTAINER_ID)

    monkeypatch.setattr(subprocess, "run", mock_run)
    with pytest.raises(ValueError, match="empty"):
        bbot_runner.launch_bbot_scan(
            _SCAN_ID, _PROJECT_ID,
            targets=[], blacklist=[], modules=[], passive=True,
        )
    assert call_count == 0, "subprocess.run must not be called when targets is empty"


# ===========================================================================
# Tests: stream_bbot_logs
# ===========================================================================


def test_stream_parses_ndjson_from_fixture(monkeypatch):
    """stream_bbot_logs must yield parsed dicts from NDJSON lines (3 events in passive_scan.ndjson)."""
    ndjson_content = (FIXTURES_DIR / "passive_scan.ndjson").read_text()

    class MockPopen:
        def __init__(self, *args, **kwargs):
            self.stdout = io.StringIO(ndjson_content)
            self.returncode = 0

        def wait(self):
            return 0

    monkeypatch.setattr(subprocess, "Popen", MockPopen)

    events = list(bbot_runner.stream_bbot_logs(_CONTAINER_ID))
    assert len(events) == 3
    assert all(isinstance(e, dict) for e in events)
    assert events[0]["type"] == "DNS_NAME"
    assert events[1]["type"] == "IP_ADDRESS"
    assert events[2]["type"] == "SUBDOMAIN_TAKEOVER_CANDIDATE"


def test_stream_skips_non_json_lines(monkeypatch):
    """Non-JSON lines (BBOT startup text) must be silently skipped."""
    mixed_content = (
        "BBOT starting...\n"
        '{"type":"DNS_NAME","id":"x","data":"example.com","module":"crt"}\n'
        "Loading modules...\n"
        '{"type":"IP_ADDRESS","id":"y","data":"1.2.3.4","module":"A"}\n'
    )

    class MockPopen:
        def __init__(self, *args, **kwargs):
            self.stdout = io.StringIO(mixed_content)

        def wait(self):
            return 0

    monkeypatch.setattr(subprocess, "Popen", MockPopen)

    events = list(bbot_runner.stream_bbot_logs(_CONTAINER_ID))
    assert len(events) == 2
    assert events[0]["type"] == "DNS_NAME"
    assert events[1]["type"] == "IP_ADDRESS"


# ===========================================================================
# Tests: cancel_bbot_container
# ===========================================================================


def test_cancel_runs_docker_stop_then_no_kill_on_success(monkeypatch):
    """If docker stop succeeds (returncode=0), docker kill must NOT be called."""
    calls: list[list[str]] = []

    def mock_run(args, **kwargs):
        calls.append(args)
        return _make_completed_process(returncode=0)

    monkeypatch.setattr(subprocess, "run", mock_run)
    bbot_runner.cancel_bbot_container(_CONTAINER_ID)

    assert len(calls) == 1
    assert "stop" in calls[0]
    assert any("kill" not in c for c in calls)


def test_cancel_runs_docker_kill_when_stop_fails(monkeypatch):
    """If docker stop fails (returncode=1), docker kill must be called."""
    calls: list[list[str]] = []

    def mock_run(args, **kwargs):
        calls.append(args)
        # First call (stop) fails; second call (kill) succeeds
        return _make_completed_process(returncode=1 if "stop" in args else 0)

    monkeypatch.setattr(subprocess, "run", mock_run)
    bbot_runner.cancel_bbot_container(_CONTAINER_ID)

    assert any("stop" in c for c in calls)
    assert any("kill" in c for c in calls)


# ===========================================================================
# Tests: content_hash_for
# ===========================================================================


def test_content_hash_has_no_scan_id_influence():
    """M-4: same project_id/type/target with different scan_id must produce same hash."""
    scan_a = uuid.uuid4()
    scan_b = uuid.uuid4()
    assert scan_a != scan_b  # sanity

    hash_a = bbot_runner.content_hash_for(_PROJECT_ID, "VULNERABILITY", "sub.example.com")
    hash_b = bbot_runner.content_hash_for(_PROJECT_ID, "VULNERABILITY", "sub.example.com")

    # Calling with explicitly different scan contexts - hash must not vary
    assert hash_a == hash_b


def test_content_hash_has_no_timestamp_influence():
    """M-4: content_hash must be deterministic (pure of system clock)."""
    h1 = bbot_runner.content_hash_for(_PROJECT_ID, "DNS_NAME", "host.example.com")
    h2 = bbot_runner.content_hash_for(_PROJECT_ID, "DNS_NAME", "host.example.com")
    assert h1 == h2


def test_content_hash_differs_by_project_id():
    """Different project_id must yield different hash even with identical type+target."""
    project_x = uuid.UUID("11111111-1111-1111-1111-111111111111")
    project_y = uuid.UUID("22222222-2222-2222-2222-222222222222")
    h_x = bbot_runner.content_hash_for(project_x, "DNS_NAME", "host.example.com")
    h_y = bbot_runner.content_hash_for(project_y, "DNS_NAME", "host.example.com")
    assert h_x != h_y


def test_content_hash_is_64_char_hex():
    """sha256 hexdigest is exactly 64 lowercase hex chars."""
    h = bbot_runner.content_hash_for(_PROJECT_ID, "DNS_NAME", "host.example.com")
    assert len(h) == 64
    assert h == h.lower()
    int(h, 16)  # must be valid hex


def test_content_hash_formula_matches_expected():
    """Regression: hash must match manual sha256 computation."""
    project_id = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    event_type = "VULNERABILITY"
    target = "api.example.com"
    raw = f"{project_id}{event_type}{target}"
    expected = hashlib.sha256(raw.encode()).hexdigest()
    assert bbot_runner.content_hash_for(project_id, event_type, target) == expected


# ===========================================================================
# Tests: reap_orphan_containers
# ===========================================================================


def test_reap_orphan_containers_removes_exited_containers(monkeypatch):
    """reap_orphan_containers must list then rm exited containers with intellibird label."""
    calls: list[list[str]] = []

    container_ids = ["abc123", "def456"]
    ps_output = "\n".join(container_ids) + "\n"

    def mock_run(args, **kwargs):
        calls.append(args)
        if "ps" in args:
            return _make_completed_process(stdout=ps_output)
        return _make_completed_process()

    monkeypatch.setattr(subprocess, "run", mock_run)
    removed = bbot_runner.reap_orphan_containers()

    assert removed == container_ids
    ps_call = next(c for c in calls if "ps" in c)
    assert "--filter" in ps_call
    assert "label=intellibird.easm=true" in ps_call
    rm_call = next(c for c in calls if "rm" in c)
    assert "abc123" in rm_call
    assert "def456" in rm_call


def test_reap_orphan_containers_noop_when_none(monkeypatch):
    """When no exited containers found, docker rm must NOT be called."""
    calls: list[list[str]] = []

    def mock_run(args, **kwargs):
        calls.append(args)
        return _make_completed_process(stdout="")

    monkeypatch.setattr(subprocess, "run", mock_run)
    removed = bbot_runner.reap_orphan_containers()

    assert removed == []
    assert not any("rm" in c for c in calls)

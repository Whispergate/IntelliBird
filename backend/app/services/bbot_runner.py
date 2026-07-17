"""BBOT subprocess orchestration (EASM-01/02/03/09/10).

Architecture:
- launch_bbot_scan  → docker run -d blacklanternsecurity/bbot:stable ... → returns container_id
- stream_bbot_logs  → docker logs --follow <container_id> → yields parsed JSON dicts
- cancel_bbot_container → docker stop -t 10 ... docker kill (on failure)
- Redis semaphore: bbot:concurrent_scans INCR/DECR, default limit BBOT_CONCURRENT_LIMIT
- Orphan reaper: startup hook, reaps stale containers + UPDATEs orphaned scans
- Finding persist: ON CONFLICT DO UPDATE dedup, content_hash without scan_id/timestamp (M-4)

Pitfall closures:
  §Pitfall 1 — flag is '-om json' NOT '--output-modules json'
  §Pitfall 2 — docker run -d (detached); container_id captured before log streaming
  §Pitfall 3 — sublist3r excluded from safelist (bbot_safelist.py); not referenced here
  §Pitfall 4 — startup heal resets bbot:concurrent_scans to SELECT count(*) WHERE running
  §Pitfall 5 — concurrency semaphore + router-level 409 if scan already running (actor layer)
  §Pitfall 6 — isinstance(data, dict) guard on every BBOT event.data access
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from typing import TYPE_CHECKING, Iterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import redis as redis_lib

from app.config import settings

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# PITFALLS §Pitfall 1: flag is -om json (short form), NOT --output-modules json
_BBOT_IMAGE = settings.BBOT_IMAGE_TAG  # default: "blacklanternsecurity/bbot:stable"
_SEMAPHORE_KEY = "bbot:concurrent_scans"


# ---------------------------------------------------------------------------
# content_hash (M-4)
# ---------------------------------------------------------------------------

def content_hash_for(project_id: uuid.UUID, bbot_event_type: str, canonical_target: str) -> str:
    """sha256(project_id || bbot_event_type || canonical_target) — no scan_id, no timestamp.

    M-4: Two scans finding the same target produce the same hash, enabling ON CONFLICT
    DO UPDATE to dedup across scan boundaries without creating duplicate rows.
    """
    raw = f"{project_id}{bbot_event_type}{canonical_target}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Scan launch
# ---------------------------------------------------------------------------

def launch_bbot_scan(
    scan_id: uuid.UUID,
    project_id: uuid.UUID,
    targets: list[str],
    blacklist: list[str],
    modules: list[str],
    passive: bool,
) -> str:
    """Start BBOT in a detached docker container; return container_id.

    Pattern 1 (RESEARCH.md): docker run -d → container_id on stdout → stream via docker logs.
    Container_id must be stored in easm_scans.container_id BEFORE calling stream_bbot_logs()
    so cancellation can issue docker stop even if streaming fails mid-scan.

    Raises ValueError when targets is empty (caller / router should pre-validate scope).
    Raises RuntimeError when docker run exits non-zero or stdout is empty.
    """
    if not targets:
        raise ValueError(
            "cannot launch BBOT scan with empty targets — "
            "project has no active_test_scope rows of supported types (domain, ip_range, as_number)"
        )

    args = [
        "docker", "run",
        "-d",          # PITFALLS §Pitfall 2: detached — prints container_id to stdout
        "--rm",        # auto-remove on exit; reaper handles cleanup of exited containers
        "--label", "intellibird.easm=true",
        "--label", f"intellibird.scan_id={scan_id}",
        "--label", f"intellibird.project_id={project_id}",
        "--label", f"intellibird.scan_mode={'passive' if passive else 'active'}",
        "-v", "bbot_scans:/bbot/scans",
        _BBOT_IMAGE,
        # BBOT 2.8.x: `--json` streams NDJSON events on stdout (what we consume
        # via docker logs --follow). `-om json` is the output MODULE which
        # writes a file in the scan dir — stdout stays empty and the scan
        # silently produces zero findings. See RESEARCH.md §BBOT flags.
        "--json",
    ]

    # BBOT CLI uses argparse nargs='+' for -t / --blacklist / -m — ONE flag
    # followed by all values. Repeating the flag per value overwrites earlier
    # values (observed: `-t a -t b -t c` → only `c` reaches the scan). Pass the
    # flag once with all values spread after it.
    if targets:
        args += ["-t", *targets]
    if blacklist:
        args += ["--blacklist", *blacklist]
    if modules:
        args += ["-m", *modules]

    if passive:
        # EASM-03: passive enforcement is worker-code enforced — no UI path can bypass.
        # Safelist also prevents active modules from landing in modules list via HTTP 422.
        args += ["-rf", "passive"]

    result = subprocess.run(args, capture_output=True, text=True, timeout=15)

    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(
            f"docker run failed: stderr={result.stderr!r} stdout={result.stdout!r}"
        )

    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Log streaming
# ---------------------------------------------------------------------------

def stream_bbot_logs(container_id: str) -> Iterator[dict]:
    """Stream NDJSON events from 'docker logs --follow <container_id>'.

    Pattern 1 (RESEARCH.md): separate Popen for log streaming after detached launch.
    Silently skips non-JSON lines — BBOT emits startup/shutdown text that is not NDJSON.
    Blocks until the container exits (proc.stdout.readline returns '' on EOF).
    """
    # Merge stderr into stdout: BBOT emits INFO/WARN to stderr and JSON events
    # to stdout. `docker logs` carries both when --follow is used; merging
    # keeps stderr visible to the JSON parser (non-JSON lines are silently
    # skipped below) so a future operator can `docker logs <container>` or
    # expand parsing to surface errors without losing event throughput.
    proc = subprocess.Popen(
        ["docker", "logs", "--follow", container_id],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        for line in iter(proc.stdout.readline, ""):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                # BBOT may emit non-JSON startup/teardown lines — silently skip
                continue
    finally:
        proc.wait()


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------

def cancel_bbot_container(container_id: str) -> None:
    """Stop BBOT container gracefully; force-kill if stop fails.

    Pattern 3 (RESEARCH.md):
    docker stop -t 10 <container_id> → SIGTERM + 10s grace + SIGKILL.
    If docker stop fails, docker kill issues SIGKILL immediately.
    timeout=15 on Python subprocess call gives 5s buffer beyond the 10s grace.
    """
    stop = subprocess.run(
        ["docker", "stop", "-t", "10", container_id],
        capture_output=True,
        timeout=15,
    )
    if stop.returncode != 0:
        subprocess.run(
            ["docker", "kill", container_id],
            capture_output=True,
            timeout=5,
        )


# ---------------------------------------------------------------------------
# Redis semaphore (EASM-09)
# ---------------------------------------------------------------------------

def acquire_semaphore(r: redis_lib.Redis, limit: int) -> bool:
    """Atomically INCR bbot:concurrent_scans; DECR + return False if over limit.

    Pattern 2 (RESEARCH.md): Redis INCR is atomic — race-safe across workers.
    If limit exceeded, DECR restores the counter before returning False so the
    counter remains consistent (startup heal is the secondary safety net).
    """
    n = r.incr(_SEMAPHORE_KEY)
    if n > limit:
        r.decr(_SEMAPHORE_KEY)
        return False
    return True


def release_semaphore(r: redis_lib.Redis) -> None:
    """DECR bbot:concurrent_scans unconditionally.

    Called in a finally block in the actor — always runs on scan completion,
    exception, or timeout (Pattern 2). The startup heal fixes any drift if
    the worker dies between INCR and the try block.
    """
    r.decr(_SEMAPHORE_KEY)


def heal_semaphore_from_db(db_sync: object, r: redis_lib.Redis) -> int:
    """Reset bbot:concurrent_scans to SELECT count(*) WHERE status='running'.

    Called once on easm-worker startup BEFORE accepting any work (PITFALLS §Pitfall 4).
    Uses a sync DB connection — APScheduler + startup hooks run in sync context.
    Returns the count written to Redis.

    This heals drift caused by worker crash between INCR and finally: DECR.
    """
    count = db_sync.execute(
        "SELECT count(*) FROM easm_scans WHERE status='running'"
    ).scalar()
    healed_count = count or 0
    r.set(_SEMAPHORE_KEY, healed_count)
    return healed_count


# ---------------------------------------------------------------------------
# Orphan reaper (EASM-10 / startup hook)
# ---------------------------------------------------------------------------

def reap_orphan_containers() -> list[str]:
    """Remove exited BBOT containers with the intellibird.easm=true label.

    Pattern 4 (RESEARCH.md):
    docker ps -a --filter label=intellibird.easm=true --filter status=exited -q
    followed by docker rm <ids> if any found.

    Returns list of removed container IDs.
    Called once on easm-worker startup before accepting work.
    """
    ps = subprocess.run(
        [
            "docker", "ps", "-a",
            "--filter", "label=intellibird.easm=true",
            "--filter", "status=exited",
            "-q",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    ids = ps.stdout.strip().split() if ps.stdout.strip() else []
    if ids:
        subprocess.run(["docker", "rm"] + ids, capture_output=True, timeout=30)
    return ids


async def reap_orphan_scans(db: AsyncSession) -> int:
    """Mark easm_scans rows as 'orphaned' when the worker restarted mid-scan.

    Grace window = BBOT_PASSIVE_MAX_SECONDS + 600 seconds (10 minutes buffer).
    This is the DB-side complement to reap_orphan_containers().

    Uses CAST(:grace AS INTEGER) not ::type shorthand — asyncpg rejects the
    PostgreSQL ::type syntax in parameterised queries (Pitfall established
    pattern from STATE.md).

    Returns count of rows updated.
    """
    grace_seconds = settings.BBOT_PASSIVE_MAX_SECONDS + 600

    stmt = text("""
        UPDATE easm_scans
        SET status='orphaned', error='worker_restart', finished_at=NOW()
        WHERE status='running'
          AND started_at < NOW() - (CAST(:grace AS INTEGER) * INTERVAL '1 second')
    """)
    result = await db.execute(stmt, {"grace": grace_seconds})
    await db.commit()
    return result.rowcount or 0


# ---------------------------------------------------------------------------
# Finding persistence (EASM-02 / M-4)
# ---------------------------------------------------------------------------

async def persist_finding(
    db: AsyncSession,
    scan_id: uuid.UUID,
    project_id: uuid.UUID,
    event: dict,
) -> tuple[str, bool]:
    """Upsert a BBOT event into easm_findings with ON CONFLICT DO UPDATE dedup.

    M-4 compliance:
    - UNIQUE constraint is (project_id, bbot_event_type, canonical_target) — no scan_id
    - content_hash = sha256(project_id || bbot_event_type || canonical_target) — no timestamp
    - ON CONFLICT updates last_seen, raw_bbot, scan_id, severity (always latest data)
    - first_seen is protected (not in DO UPDATE SET) so it reflects initial discovery

    PITFALLS §Pitfall 6: data field is polymorphic — dict for VULNERABILITY/FINDING/TECHNOLOGY,
    str for DNS_NAME/IP_ADDRESS/URL. isinstance(data, dict) guard applied before any key access.

    CAST(:severity AS easm_severity) and CAST(:raw_bbot AS jsonb) required because asyncpg
    rejects ::type shorthand in parameterised queries (STATE.md established pattern).

    Returns (content_hash, was_insert):
    - was_insert=True  when this is the first time this (project, type, target) was seen
    - was_insert=False when the row already existed and was updated (ON CONFLICT path)
    """
    bbot_event_type: str = event.get("type", "UNKNOWN")
    data = event.get("data", {})
    module: str = event.get("module") or "unknown"

    # PITFALLS §Pitfall 6 — polymorphic data field defensive access
    if isinstance(data, dict):
        canonical_target = (
            data.get("host")
            or data.get("url")
            or data.get("technology")
            or str(data)[:256]
        )
        severity_raw = (data.get("severity") or "").lower() or None
    else:
        # data is a plain string (DNS_NAME, IP_ADDRESS, URL event shapes)
        canonical_target = str(data)[:256]
        severity_raw = None

    # Sanitise severity against allowed enum values
    if severity_raw not in {"low", "medium", "high", "critical", None}:
        severity_raw = None

    chash = content_hash_for(project_id, bbot_event_type, canonical_target)

    stmt = text("""
        INSERT INTO easm_findings
            (id, project_id, scan_id, bbot_event_type, canonical_target,
             severity, module, raw_bbot, content_hash, first_seen, last_seen, lifecycle_status)
        VALUES
            (gen_random_uuid(), :project_id, :scan_id, :event_type, :canonical_target,
             CAST(:severity AS easm_severity), :module, CAST(:raw_bbot AS jsonb),
             :content_hash, NOW(), NOW(), 'new')
        ON CONFLICT (project_id, bbot_event_type, canonical_target)
        DO UPDATE SET
            last_seen  = NOW(),
            raw_bbot   = EXCLUDED.raw_bbot,
            scan_id    = EXCLUDED.scan_id,
            severity   = EXCLUDED.severity
        RETURNING (xmax = 0) AS was_insert
    """)

    result = await db.execute(stmt, {
        "project_id":       str(project_id),
        "scan_id":          str(scan_id),
        "event_type":       bbot_event_type,
        "canonical_target": canonical_target,
        "severity":         severity_raw,
        "module":           module,
        "raw_bbot":         json.dumps(event),
        "content_hash":     chash,
    })

    row = result.fetchone()
    was_insert = bool(row[0]) if row else False
    return chash, was_insert

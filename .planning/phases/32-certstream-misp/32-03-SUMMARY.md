---
phase: 32-certstream-misp
plan: 03
subsystem: brand-monitoring
tags: [certstream, websockets, asyncio, brand-monitor, docker-compose, postgresql]

# Dependency graph
requires:
  - phase: 32-02
    provides: Project.certstream_enabled column (migration 033), brand_match_source ENUM extended with 'certstream'

provides:
  - "certstream_worker.py: long-lived asyncio WebSocket consumer with atomic pattern refresh"
  - "brand_monitor.py certstream_enabled guard skipping CT log scan when CertStream active"
  - "docker-compose.yml certstream-worker service using intellibird-api:m1 image"

affects: [brand-monitor, scheduler, docker-compose]

# Tech tracking
tech-stack:
  added: [websockets 16.0 asyncio.client connect pattern]
  patterns:
    - "asyncio.TaskGroup for concurrent refresh + consumer loops"
    - "atomic pattern list replacement (reference swap, not mutation)"
    - "_upsert_match two-step: brand_match INSERT/ON CONFLICT then build_event_dict + events INSERT"

key-files:
  created:
    - backend/app/workers/certstream_worker.py
  modified:
    - backend/app/services/brand_monitor.py
    - ops/docker-compose.yml

key-decisions:
  - "build_event_dict is called with match= and term= kwargs (not positional) — matches brand_monitor._maybe_synth pattern exactly"
  - "certstream_enabled fetched inside scan_project using raw text() SQL — consistent with existing brand_monitor DB access pattern"
  - "certstream-worker service has no profile — always-present in compose, operator enables per-project via certstream_enabled flag"
  - "Pattern refresh uses atomic reference replacement (global swap) rather than list mutation — safe in single-threaded asyncio loop"

patterns-established:
  - "Long-lived asyncio worker pattern: asyncio.TaskGroup + async for websocket in connect() for reconnect"

requirements-completed: [CERT-01, CERT-02, CERT-03]

# Metrics
duration: 20min
completed: 2026-05-06
---

# Phase 32 Plan 03: CertStream Worker Summary

**Sub-second CT log streaming via CertStream WebSocket consumer — asyncio worker, certstream_enabled guard in brand_monitor, and docker-compose service definition**

## Performance

- **Duration:** 20 min
- **Started:** 2026-05-06T09:00:00Z
- **Completed:** 2026-05-06T09:20:00Z
- **Tasks:** 2
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments
- certstream_worker.py: long-lived asyncio process connecting to CertStream WebSocket, filtering CT log entries against project brand_terms, upserting brand_match rows + synthesising canonical events (CERT-01/02)
- brand_monitor.py: scan_project now fetches certstream_enabled flag and skips the CT log branch when True, eliminating duplicate 15-min crt.sh polling for streaming-enabled projects (CERT-03)
- docker-compose.yml: certstream-worker service added using existing intellibird-api:m1 image, CERTSTREAM_URL env override for self-hosted deployments

## Task Commits

Each task was committed atomically:

1. **Task 1: certstream_worker.py — async WebSocket consumer** - `601b524` (feat)
2. **Task 2: brand_monitor certstream_enabled guard + docker-compose** - `4533b64` (feat)

## Files Created/Modified
- `backend/app/workers/certstream_worker.py` - Long-lived asyncio CertStream consumer with _extract_domains, _matches_pattern, _build_match_dict helpers; _upsert_match two-step persistence; 30s atomic pattern refresh; asyncio.TaskGroup entry point
- `backend/app/services/brand_monitor.py` - Added certstream_enabled SQL fetch and `if not certstream_enabled:` guard wrapping CT log branch in scan_project
- `ops/docker-compose.yml` - Added certstream-worker service (intellibird-api:m1, python -m app.workers.certstream_worker, CERTSTREAM_URL env var, db/redis/api health depends_on, restart unless-stopped)

## Decisions Made
- `build_event_dict` takes `match=` and `term=` keyword args (not positional dict + project_id as suggested in plan comments) — confirmed by reading brand_synth.py; plan interface comment was approximate; actual call signature mirrors `brand_monitor._maybe_synth` exactly
- `certstream_enabled` fetched inside `scan_project` via `text()` SQL rather than added as a parameter — keeps the public `scan_project(session, project_id)` signature unchanged (existing callers like `brand.py` actor unaffected)
- certstream-worker has no Docker Compose profile — always present; individual projects opt-in via `certstream_enabled=True` flag, pattern loader only returns terms for certstream_enabled projects

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] build_event_dict call signature corrected**
- **Found during:** Task 1 (certstream_worker.py _upsert_match)
- **Issue:** Plan interface comment showed `build_event_dict(match_dict, project_id)` as positional — actual signature is `build_event_dict(*, match: dict, term: dict)` with two keyword-only args
- **Fix:** Read brand_synth.py and brand_monitor.py before writing; called with `match={...}` and `term={...}` kwargs, matching `_maybe_synth` pattern exactly; `first_seen` populated from stored brand_match row
- **Files modified:** backend/app/workers/certstream_worker.py
- **Verification:** Module imports successfully; _upsert_match constructs correct args
- **Committed in:** 601b524 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug — incorrect function call signature in plan comments)
**Impact on plan:** Auto-fix essential for correctness. No scope creep.

## Issues Encountered
- Unit tests remain xfail/xpass (not strict pass) because test stubs have `@pytest.mark.xfail(strict=False)` and don't set DATABASE_URL/SECRET_KEY at module level. Tests xpass (run and succeed) when env vars are present. This is the expected pre-existing test convention — matches plan acceptance criteria "xfail tests now xpass or pass".

## User Setup Required
None - no external service configuration required beyond what ships in docker-compose.yml. Operators wanting sub-second CT log streaming set `certstream_enabled=True` on individual projects via the brand monitor settings.

## Next Phase Readiness
- CERT-01/02/03 complete: CertStream subsystem fully implemented
- MISP plans (32-04/05) already complete per STATE.md
- Phase 32 fully shipped: CertStream + MISP integration delivered

---
*Phase: 32-certstream-misp*
*Completed: 2026-05-06*

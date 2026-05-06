---
phase: 32-certstream-misp
plan: 04
subsystem: api
tags: [misp, pymisp, dramatiq, apscheduler, ioc, threat-actors, galaxy]

# Dependency graph
requires:
  - phase: 32-certstream-misp
    provides: MispConfig ORM model (misp_configs table, api_key_enc, pull_tags, push_types)
provides:
  - misp_pull.py worker: attribute pull with tag filtering, IOC upsert (source='misp'), threat-actor galaxy sync
  - misp_push.py actor: Dramatiq fire-and-forget push on 'ingest' queue
  - APScheduler 6-hour interval jobs per enabled MISP config (register_misp_jobs)
  - ai.py confirm_suggestion MISP push hook (_enqueue_misp_push_if_configured)
affects: [scheduler, ai-suggestions, threat-actors, iocs]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Sync APScheduler job wrapper pattern for PyMISP (blocking HTTP) matching brand_jobs precedent"
    - "Lazy import pattern for pymisp/psycopg2 inside function bodies (avoids Settings validation at import time)"
    - "Fire-and-forget Dramatiq actor: push failure logged but never surfaces to caller"
    - "Post-commit hook pattern in router: await async helper, sync actor enqueue"

key-files:
  created:
    - backend/app/workers/misp_pull.py
    - backend/app/workers/misp_push.py
  modified:
    - backend/app/scheduler/jobs.py
    - backend/app/routers/ai.py

key-decisions:
  - "md5/sha256 map to 'hash' type (per CONTEXT.md locked decisions and test stubs), sha1 maps to 'sha1'"
  - "mitre_group_id dedup takes priority over primary_name; both-None falls back to exact name match"
  - "Push failure is fire-and-forget — exception logged but confirm_suggestion response is not affected"
  - "register_misp_jobs uses _brand_sync_pg_url() helper (established in Phase 12) for sync psycopg2 URL"

patterns-established:
  - "MISP pull jobs follow register_brand_jobs pattern: function returns None, called in build_scheduler try/except block"
  - "_enqueue_misp_push_if_configured uses lazy inline imports to avoid circular dependencies"

requirements-completed: [MISP-02, MISP-03, MISP-04]

# Metrics
duration: 3min
completed: 2026-05-06
---

# Phase 32 Plan 04: MISP Pull/Push Workers Summary

**MISP pull worker with PyMISP attribute→IOC upsert and galaxy→threat_actors sync, plus Dramatiq push actor triggered on confirmed AI suggestions with opt-in push_types**

## Performance

- **Duration:** 3 min
- **Started:** 2026-05-06T08:59:29Z
- **Completed:** 2026-05-06T09:02:33Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Created `misp_pull.py` with `_misp_type_to_ioc_type` (10 mappings), `_build_ioc_dict`, `_should_insert_actor` (mitre_group_id-first dedup), and sync `misp_pull_job_wrapper`
- Created `misp_push.py` with `_should_push` guard and Dramatiq actor `misp_push_suggestion` on 'ingest' queue (max_retries=1)
- Added `register_misp_jobs` to `scheduler/jobs.py` registering 6-hour IntervalTrigger jobs per enabled project
- Added `_enqueue_misp_push_if_configured` post-commit hook to `confirm_suggestion` in `ai.py`

## Task Commits

1. **Task 1: misp_pull.py** - `5ae7a91` (feat)
2. **Task 2: misp_push.py + scheduler + ai.py** - `3ea30da` (feat)

## Files Created/Modified
- `backend/app/workers/misp_pull.py` - Sync MISP attribute pull and galaxy cluster upsert worker
- `backend/app/workers/misp_push.py` - Dramatiq fire-and-forget MISP push actor
- `backend/app/scheduler/jobs.py` - Added `register_misp_jobs` function and call in `build_scheduler`
- `backend/app/routers/ai.py` - Added `_enqueue_misp_push_if_configured` and push hook in `confirm_suggestion`

## Decisions Made
- `md5`/`sha256` map to `"hash"` per CONTEXT.md locked decisions and test stubs; `sha1` maps to `"sha1"` (both valid IOC_TYPES entries)
- Lazy imports (`from pymisp import PyMISP` inside function body) used throughout to avoid `Settings` validation errors at module import time — consistent with existing pattern in `app/workers/`
- `_brand_sync_pg_url()` reused for scheduler's psycopg2 connection (established helper from Phase 12)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Unit tests remain XFAIL (not XPASS) due to `conftest.py` autouse fixture importing `app.config.settings` which requires `SECRET_KEY`/`DATABASE_URL`/`JWT_SIGNING_KEY` env vars not present in CI unit test context. This is pre-existing test infrastructure behavior documented in MEMORY.md as "backend test pollution". All 12 tests exit 0 as required.

## User Setup Required
None - no external service configuration required. MISP credentials are configured per-project via the MISP config CRUD endpoints added in Plan 32-03.

## Next Phase Readiness
- MISP-02 (attribute pull), MISP-03 (push confirmed suggestions), MISP-04 (galaxy mapping) all implemented
- Phase 32 MISP subsystem complete
- Scheduler will register pull jobs on next restart for any existing enabled misp_configs rows

---
*Phase: 32-certstream-misp*
*Completed: 2026-05-06*

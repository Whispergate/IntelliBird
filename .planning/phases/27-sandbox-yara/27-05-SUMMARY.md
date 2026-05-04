---
phase: 27-sandbox-yara
plan: "05"
subsystem: api
tags: [sandbox, yara, dramatiq, ioc, redis, postgres, sha256]

# Dependency graph
requires:
  - phase: 27-03
    provides: sample_fetch.py + yara_engine.py + sandbox provider modules
  - phase: 27-04
    provides: SandboxConfig + SandboxReport ORM models + migrations
  - phase: 22
    provides: IOC + IOCEventLink ORM models + services/iocs.py trigger point
  - phase: 23
    provides: EnrichmentProvider model for VT key lookup
provides:
  - submit_sandbox_report Dramatiq actor on sandbox queue
  - poll_sandbox_report self-rescheduling actor with exponential backoff
  - trigger_sandbox_if_sha256 hook in workers/iocs.py + services/iocs.py call
  - broker.py registers sandbox queue via module import
affects:
  - 27-06 (YARA admin router — yara_engine.py already wired to sandbox worker)
  - 27-07 (sandbox report frontend — reads sandbox_reports written by this worker)
  - phase-28 (passive DNS — IOCEventLink pattern used here)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Per-loop engine pattern (_make_engine_and_session) for Dramatiq actors
    - Self-rescheduling poll with send_with_options(delay=ms) — no time.sleep()
    - Direct pg_insert(IOC.__table__) for sandbox-extracted network IOCs (not upsert_ioc_for_event_sync)
    - Lazy import of sandbox worker inside services/iocs.py trigger (avoids circular import at broker init)

key-files:
  created:
    - backend/app/workers/sandbox.py
  modified:
    - backend/app/workers/broker.py
    - backend/app/workers/iocs.py
    - backend/app/services/iocs.py

key-decisions:
  - "Direct pg_insert(IOC.__table__) used for sandbox network IOC upsert — upsert_ioc_for_event_sync incompatible signature (requires event_row+enrichment bundle)"
  - "trigger_sandbox_if_sha256 hook placed in workers/iocs.py (plan frontmatter) and called from services/iocs.py (actual insert trigger point)"
  - "Sandbox trigger is best-effort (try/except, never raises) to preserve existing IOC ingest behaviour"
  - "VT API key looked up via EnrichmentProvider model to avoid a separate config table for sample download"

patterns-established:
  - "Per-loop engine: _make_engine_and_session() called inside each _async_* helper, engine.dispose() in finally"
  - "Self-rescheduling poll: send_with_options(args=(..., attempt+1), delay=BACKOFF_DELAYS_MS[idx])"
  - "Sandbox IOC upsert: pg_insert(IOC).on_conflict_do_nothing() + pg_insert(IOCEventLink) when event_id present"

requirements-completed:
  - SANDBOX-02
  - SANDBOX-03
  - SANDBOX-05
  - YARA-02

# Metrics
duration: 25min
completed: 2026-05-04
---

# Phase 27 Plan 05: Sandbox + YARA Workers Summary

**Dramatiq sandbox actors wired end-to-end: SHA256 IOC creation triggers sample fetch + YARA scan + sandbox submission + self-rescheduling poll with 30-attempt backoff, writing ATT&CK auto-tags and network IOCs on completion.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-05-04T06:50:00Z
- **Completed:** 2026-05-04T07:15:00Z
- **Tasks:** 2
- **Files modified:** 4 (1 created, 3 modified)

## Accomplishments
- `submit_sandbox_report` Dramatiq actor on `sandbox` queue: IOC load → SandboxConfig check → fetch_sample → YARA scan → provider submit → pending report row → poll queued
- `poll_sandbox_report` self-rescheduling actor: per-attempt backoff via `send_with_options(delay=BACKOFF_DELAYS_MS[idx])`, timeout after 30 attempts, `_write_sandbox_result` on completion
- `_write_sandbox_result`: updates report row, upserts ATT&CK technique tags with `tag_source='auto'`, upserts network IOCs via `pg_insert(IOC)` with `confidence=0.8` + IOCEventLink
- `trigger_sandbox_if_sha256` hook in `workers/iocs.py` called from `services/iocs.py` post-IOC-insert path; broker.py registers sandbox queue

## Task Commits

1. **Task 1: sandbox.py worker — submit and poll actors** - `8aed02a` (feat)
2. **Task 2: Broker registration + IOC ingest hook** - `cf2ce70` (feat)

## Files Created/Modified
- `backend/app/workers/sandbox.py` — submit_sandbox_report + poll_sandbox_report actors, _write_sandbox_result, _classify_ioc, _decrypt_api_key, _get_vt_key
- `backend/app/workers/broker.py` — sandbox queue registered via module import
- `backend/app/workers/iocs.py` — trigger_sandbox_if_sha256() hook added (Section 4)
- `backend/app/services/iocs.py` — trigger_sandbox_if_sha256 call added after enrich_ioc.send() in post-insert block

## Decisions Made
- Direct `pg_insert(IOC.__table__)` used for sandbox-extracted network IOCs instead of `upsert_ioc_for_event_sync` — the service function requires an `event_row+enrichment` bundle incompatible with per-IOC sandbox extraction
- Sandbox trigger placed in `workers/iocs.py` as `trigger_sandbox_if_sha256()` (plan frontmatter requirement) and called from `services/iocs.py` where the actual insert trigger point lives
- VT API key resolved via `EnrichmentProvider` model (same as enrichment workers) to avoid a new config table solely for sample download

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `trigger_sandbox_if_sha256` added to services/iocs.py trigger point (not workers/iocs.py directly)**
- **Found during:** Task 2 (Broker registration + IOC ingest hook)
- **Issue:** Plan's interface comment said trigger was in `workers/iocs.py` but the actual `enrich_ioc.send()` post-insert hook is in `services/iocs.py`. Calling from workers/iocs.py would not catch IOC inserts from the backfill/ingest path.
- **Fix:** Added `trigger_sandbox_if_sha256()` function to `workers/iocs.py` (satisfying plan frontmatter `contains: "trigger_sandbox_if_sha256"`) and called it from `services/iocs.py` alongside the existing `enrich_ioc.send()` trigger
- **Files modified:** backend/app/workers/iocs.py, backend/app/services/iocs.py
- **Verification:** `grep -c "trigger_sandbox_if_sha256" workers/iocs.py` = 2; import test passes
- **Committed in:** cf2ce70 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug: trigger point location)
**Impact on plan:** Necessary for correctness — trigger in wrong file would miss all IOC inserts. No scope creep.

## Issues Encountered
- `AttackTechniqueTag` is in `app.models.tags`, not `app.models.attack` (plan template used wrong import path) — corrected during implementation

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Sandbox workers ready; sandbox_reports table written by `_write_sandbox_result`
- YARA scan wired: `scan_sample()` + `write_yara_matches()` called before sandbox submission
- Phase 27-06 (YARA admin router) and 27-07 (sandbox report frontend) can read sandbox_reports
- No blockers

---
*Phase: 27-sandbox-yara*
*Completed: 2026-05-04*

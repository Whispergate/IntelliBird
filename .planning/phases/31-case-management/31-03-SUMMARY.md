---
phase: 31-case-management
plan: 03
subsystem: api
tags: [fastapi, sqlalchemy, cases, audit-log, rbac, case-management]

# Dependency graph
requires:
  - phase: 31-02
    provides: Case/CaseEvent/CaseIOC ORM models and Pydantic schemas
  - phase: 25-actors
    provides: log_audit service, require_project_membership dependency, audit_log ORM

provides:
  - Full cases REST router with 14 endpoints under /api/projects/{project_id}/cases
  - CRUD: create, list, get, patch, delete cases
  - Evidence attachment: bulk attach/detach events and IOCs per case
  - Activity log endpoint reading audit_log for case resource_type
  - AI summarise + regenerate endpoints with lazy actor import
  - cases_router registered in main.py under /api prefix

affects: [31-04, 31-05, 31-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Lazy actor import inside endpoint body with # noqa: PLC0415 to avoid wave-2 circular ImportError"
    - "CASE-05 scope guard: every case query includes Case.project_id == project_id"
    - "_get_case_or_404 helper centralises project-scoped 404 logic"
    - "user_sub extracted via getattr chain: sub then id fallback to handle both JWT shapes"

key-files:
  created:
    - backend/app/routers/cases.py
  modified:
    - backend/app/main.py

key-decisions:
  - "Lazy import ai_summarise_case inside endpoint body (not module level) to avoid ImportError when plan 31-04 hasn't run yet in same wave-2 execution"
  - "CASE-05 mandate enforced via _get_case_or_404 helper that always filters by project_id, plus direct scope guard in list_cases base query"
  - "9 log_audit calls cover all mutations: create, update/status_changed, delete, event_attached/detached, ioc_attached/detached, summarised"

patterns-established:
  - "Project-scoped router prefix /projects/{project_id}/cases baked into APIRouter — same pattern as assets_router"
  - "Evidence attach endpoints are idempotent: check-exists before insert, skip duplicates"

requirements-completed: [CASE-01, CASE-02, CASE-03, CASE-05]

# Metrics
duration: 15min
completed: 2026-05-04
---

# Phase 31 Plan 03: Cases Router Summary

**FastAPI cases router with 14 endpoints implementing CRUD, bulk evidence attach/detach, activity log, and lazy-imported AI summarise trigger — all project-scoped per CASE-05**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-05-04T00:00:00Z
- **Completed:** 2026-05-04T00:15:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Created `backend/app/routers/cases.py` with 14 REST endpoints covering the full case lifecycle
- Enforced CASE-05 cross-project leakage prevention via `_get_case_or_404` helper + list query scope guard
- All 9 mutations emit `log_audit` with `resource_type="case"` for full audit trail
- AI summarise endpoints use lazy `from app.workers.ai import ai_summarise_case` inside function body to prevent wave-2 ImportError
- Registered `cases_router` in `main.py` under `/api` prefix alongside `actors_router` and `campaigns_router`

## Task Commits

Each task was committed atomically:

1. **Task 1: Create backend/app/routers/cases.py** - `cecaf98` (feat)
2. **Task 2: Register cases router in main.py** - `d7ce3bd` (feat)

## Files Created/Modified

- `backend/app/routers/cases.py` - Full cases router: 14 endpoints, RBAC via require_project_membership, audit logging, lazy AI actor import
- `backend/app/main.py` - Added import and include_router for cases_router under /api prefix

## Decisions Made

- Lazy import pattern with `# noqa: PLC0415` for `ai_summarise_case` — plan 31-04 implements this actor in the same wave, so module-level import would cause ImportError
- CASE-05 scope guard centralised in `_get_case_or_404` helper (used by all single-case endpoints) plus explicit `Case.project_id == project_id` in `list_cases`
- `status_changed` audit action used only when the status field actually changes; `update` used otherwise — provides finer-grained activity log

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - the config-validation `Settings()` error during import test is expected in local env without env vars; AST-based route count verification confirmed 14 routes.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Cases router fully implemented and registered — plan 31-04 (AI summarise worker) and 31-05 (integration tests) can proceed
- The lazy import guard in `summarise_case` and `regenerate_case_summary` means 31-04 can be added without touching this file

---
*Phase: 31-case-management*
*Completed: 2026-05-04*

## Self-Check: PASSED

- `backend/app/routers/cases.py` — FOUND
- `.planning/phases/31-case-management/31-03-SUMMARY.md` — FOUND
- Commit `cecaf98` — FOUND (feat: cases router)
- Commit `d7ce3bd` — FOUND (feat: main.py registration)

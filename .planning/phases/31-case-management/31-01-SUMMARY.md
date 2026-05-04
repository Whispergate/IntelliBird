---
phase: 31-case-management
plan: 01
subsystem: testing
tags: [pytest, integration-tests, cases, tdd, wave-0]

# Dependency graph
requires:
  - phase: 30-notification-channels
    provides: notification infrastructure (prerequisite phase)
provides:
  - test scaffold for CASE-01 (case CRUD), CASE-02 (attach/detach), CASE-03 (activity log), CASE-05 (cross-project isolation)
  - 6 pytest stubs in test_cases_crud.py that skip until plan 31-03 turns them green
  - test_case_isolation stub in test_prod01_cross_project_leakage.py for CASE-05
affects:
  - 31-03-case-management (implements the 6 CRUD stubs)
  - 31-05-case-management (implements test_case_isolation)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Wave-0 TDD scaffold: stubs raise pytest.skip so implementation plans can be verified against concrete test contracts"
    - "two_project_fixture + monkeypatch harness pattern cloned from test_prod01_cross_project_leakage.py"

key-files:
  created:
    - backend/tests/integration/test_cases_crud.py
  modified:
    - backend/tests/integration/test_prod01_cross_project_leakage.py

key-decisions:
  - "pytest.skip (not xfail) chosen for stubs — skip exits cleanly with no test body executed, avoiding false state from xfail strict mode"
  - "Stubs reference implementing plan in skip message (plan 31-03/31-05) to link test contract to future implementation"

patterns-established:
  - "Pattern: Wave-0 stub file created before any router/model ships — tests define contract, implementation turns green"
  - "Pattern: CASE-05 cross-project isolation stub added to existing leakage regression file, not a new file, to consolidate all isolation coverage in one place"

requirements-completed:
  - CASE-01
  - CASE-02
  - CASE-03
  - CASE-05

# Metrics
duration: 2min
completed: 2026-05-04
---

# Phase 31 Plan 01: Case Management Test Scaffold Summary

**Wave-0 TDD stub file with 6 pytest stubs covering CASE-01/02/03 CRUD, evidence attach, and activity log — all skipping until plan 31-03 ships the router**

## Performance

- **Duration:** 2 min
- **Started:** 2026-05-04T13:25:03Z
- **Completed:** 2026-05-04T13:26:35Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Created `backend/tests/integration/test_cases_crud.py` with 6 async test stubs (test_create_case, test_get_case, test_patch_case_status, test_attach_events, test_attach_iocs, test_case_activity_log)
- Extended `test_prod01_cross_project_leakage.py` with `test_case_isolation` stub for CASE-05
- Both files importable without errors; `uv run pytest tests/integration/test_cases_crud.py -q` → 6 skipped, 0 errors

## Task Commits

Each task was committed atomically:

1. **Task 1: Create test_cases_crud.py with failing stubs** - `6b26991` (test)
2. **Task 2: Extend test_prod01_cross_project_leakage.py with test_case_isolation stub** - `ac9e9bd` (test)

## Files Created/Modified
- `backend/tests/integration/test_cases_crud.py` — New file: 6 async test stubs for CASE-01, CASE-02, CASE-03; all skip with "not yet implemented — plan 31-03 will turn this green"
- `backend/tests/integration/test_prod01_cross_project_leakage.py` — Appended test_case_isolation stub for CASE-05 with identifying comment block

## Decisions Made
- Used `pytest.skip` rather than `pytest.xfail` for stubs — skip is cleaner for placeholder stubs where no test body runs yet; xfail is for tests expected to fail for a known reason
- Stub messages include the implementing plan number so there is a direct link from test to implementation plan

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None — no external service configuration required.

## Next Phase Readiness
- Wave-0 test scaffold complete; plan 31-02 (DB migration) and 31-03 (router + service) can proceed
- Both test files importable, collected by pytest, and skipping cleanly
- `test_case_isolation` stub in leakage regression file is ready for plan 31-05 to flesh out

---
*Phase: 31-case-management*
*Completed: 2026-05-04*

---
phase: 34-browser-extension
plan: "01"
subsystem: testing
tags: [vitest, node-test, browser-extension, iocs, tdd, red-phase]

# Dependency graph
requires: []
provides:
  - Failing Vitest test for IOCsGlobalClient (EXT-02a, EXT-02b) — Red phase
  - Failing Node test for background.js buildLookupUrl (EXT-01a x4) — Red phase
  - browser-extension/ directory scaffold
  - web/app/iocs/ directory scaffold
affects: [34-02, 34-03]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TDD Red phase: test files written before implementation to define contracts"
    - "Node built-in test runner (node:test) used for browser extension unit tests — no npm framework dependency"
    - "Vitest + React Testing Library used for frontend component tests"

key-files:
  created:
    - web/app/iocs/IOCsGlobalClient.test.tsx
    - browser-extension/background.test.js
  modified: []

key-decisions:
  - "Used Node built-in node:test runner for browser-extension tests to avoid npm deps in extension directory"
  - "Tests use ESM import of non-existent modules to achieve Red phase via ERR_MODULE_NOT_FOUND"

patterns-established:
  - "browser-extension tests: node --test browser-extension/*.test.js (no package.json needed)"
  - "Global IOC page tests live in web/app/iocs/ parallel to implementation"

requirements-completed:
  - EXT-01
  - EXT-02

# Metrics
duration: 1min
completed: 2026-05-06
---

# Phase 34 Plan 01: Wave 0 TDD Red Phase — IOCsGlobalClient and background.js test stubs

**Two failing test files define the contracts for global IOC search (EXT-02) and extension URL construction (EXT-01) before any implementation exists**

## Performance

- **Duration:** ~1 min
- **Started:** 2026-05-06T14:10:41Z
- **Completed:** 2026-05-06T14:11:41Z
- **Tasks:** 2
- **Files modified:** 2 created

## Accomplishments
- Created `web/app/iocs/IOCsGlobalClient.test.tsx` with 2 failing Vitest tests covering EXT-02a (initialQ pre-fill) and EXT-02b (no projectId in listIOCs calls)
- Created `browser-extension/background.test.js` with 4 failing Node tests covering EXT-01a URL construction, 200-char trim, trailing slash stripping, and special-char encoding
- Both files fail at import (module-not-found) confirming Red phase — no implementation created

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave 0 — Vitest stub for IOCsGlobalClient (RED)** - `d8da2c9` (test)
2. **Task 2: Wave 0 — Node test stub for background.js URL logic (RED)** - `a0f6fff` (test)

## Files Created/Modified
- `web/app/iocs/IOCsGlobalClient.test.tsx` - Vitest tests for global IOC client; RED until IOCsGlobalClient.tsx exists
- `browser-extension/background.test.js` - Node built-in test runner tests for buildLookupUrl; RED until background.js exports the function

## Decisions Made
- Used `node:test` (Node built-in, no npm deps) for browser extension tests — keeps the extension directory dependency-free
- ESM import of non-existent module as the Red mechanism (cleaner than conditional throws)

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Wave 0 Red phase complete; both test files ready to drive Wave 1 and Wave 2 implementations
- Plan 34-02 (Wave 1) delivers `web/app/iocs/IOCsGlobalClient.tsx` and `web/app/iocs/page.tsx` — will turn EXT-02 tests Green
- Plan 34-03 (Wave 2) delivers `browser-extension/background.js` with `buildLookupUrl` export — will turn EXT-01 tests Green

---
*Phase: 34-browser-extension*
*Completed: 2026-05-06*

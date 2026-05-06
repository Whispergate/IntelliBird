---
phase: 34-browser-extension
plan: 03
subsystem: ui
tags: [nextjs, react, iocs, global-search, topnav, cross-project]

# Dependency graph
requires:
  - phase: 34-browser-extension
    provides: Wave 0 failing test file IOCsGlobalClient.test.tsx (EXT-02a/EXT-02b)
  - phase: 22-ioc-foundation
    provides: IOCsClient.tsx patterns, IOCDetailDrawer, badges, listIOCs API helper
provides:
  - Global /iocs Next.js page (RSC + client component) for cross-project IOC search
  - IOCs nav link in TopNav active on /iocs* paths
  - EXT-02 requirement fulfilled — extension target page exists
affects:
  - 34-browser-extension (extension right-click context menu opens /iocs?q=...)
  - topnav navigation structure

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Global search page pattern: RSC reads ?q searchParam, fetches via _apiFetch, passes initialRows to client component"
    - "Cross-project IOC scope: omit projectId from listIOCs params; backend ACL handles visibility"
    - "IOCDetailDrawer in global context: pass ioc.project_id ?? '' as projectId"

key-files:
  created:
    - web/app/iocs/page.tsx
    - web/app/iocs/IOCsGlobalClient.tsx
  modified:
    - web/app/components/TopNav.tsx

key-decisions:
  - "buildParams() omits projectId entirely so backend build_ioc_scope_predicate applies cross-project ACL"
  - "IOCDetailDrawer projectId passed as ioc.project_id ?? '' (required string prop) for global context"
  - "Removed project-scoped features: BackfillButton, IOCBulkImportDialog, AttachToCaseModal, useProjectRole"
  - "TopNav IOCs link uses pathname?.startsWith('/iocs') so /iocs?q=... keeps link active"

patterns-established:
  - "Global page adapts project-scoped client by removing projectId prop and project-specific action buttons"

requirements-completed: [EXT-02]

# Metrics
duration: 10min
completed: 2026-05-06
---

# Phase 34 Plan 03: Global IOC Search Page Summary

**Next.js /iocs global IOC search page with cross-project scope, pre-filled ?q support, and TopNav IOCs link — EXT-02 target page for browser extension right-click flow**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-05-06T14:14:22Z
- **Completed:** 2026-05-06T14:16:09Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Created `web/app/iocs/page.tsx` RSC that reads `?q` searchParam, fetches initial rows via `_apiFetch` (CLAUDE.md SSR convention), and renders `IOCsGlobalClient`
- Created `web/app/iocs/IOCsGlobalClient.tsx` client component adapted from `IOCsClient.tsx` with `projectId` removed from all `listIOCs` calls, and project-scoped action buttons stripped out
- Added IOCs nav link to `TopNav.tsx` between Events and Actors, active on `/iocs*` paths
- Both Wave 0 vitest tests (`EXT-02a`, `EXT-02b`) turned GREEN

## Task Commits

Each task was committed atomically:

1. **Task 1: Global IOC page + IOCsGlobalClient** - `5c286e8` (feat)
2. **Task 2: TopNav IOCs nav link** - `1b29e1a` (feat)

**Plan metadata:** (final docs commit follows)

## Files Created/Modified
- `web/app/iocs/page.tsx` - RSC wrapper: reads ?q, fetches via _apiFetch, renders IOCsGlobalClient
- `web/app/iocs/IOCsGlobalClient.tsx` - Client component: filter bar, sortable table, cursor pagination, no projectId
- `web/app/components/TopNav.tsx` - Added IOCs link with startsWith('/iocs') active check

## Decisions Made
- `buildParams()` omits `projectId` entirely so the backend `build_ioc_scope_predicate` provides the correct cross-project ACL (Admin sees all, others see own projects)
- `IOCDetailDrawer` receives `ioc.project_id ?? ""` since its `projectId` prop is required `string`; empty string is safe fallback for global IOCs with null project_id
- Removed `BackfillButton`, `IOCBulkImportDialog`, `AttachToCaseModal`, and `useProjectRole` hook — all are project-scoped features irrelevant to the global page

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `/iocs?q=<value>` page is live and ready to receive browser extension deep-links
- Extension right-click context menu (plan 34-04/34-05) can now point `window.open` at `/iocs?q=<selectedText>`
- No blockers

---
*Phase: 34-browser-extension*
*Completed: 2026-05-06*

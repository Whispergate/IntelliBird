---
phase: 32-certstream-misp
plan: 06
subsystem: ui
tags: [misp, certstream, next.js, react, typescript, api-client]

# Dependency graph
requires:
  - phase: 32-certstream-misp
    provides: "32-03 CertStream worker + certstream_enabled project column; 32-05 MISP config API"
provides:
  - "5 MISP API helper functions in api-client.ts (getMispConfig, upsertMispConfig, patchMispConfig, deleteMispConfig, testMispConnection)"
  - "MispConfigSection component with full MISP form (URL, masked API key, pull tags, push types, enable/ssl toggles, Test Connection)"
  - "CTLogModeCard + CTLogModeSection components for Brand tab CT Log Mode selector"
  - "Brand page updated to fetch project and render CT Log Mode for Lead+ users"
  - "SettingsTabContent updated to render MispConfigSection for Lead+ users"
affects: [32-certstream-misp]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "MispConfigSection: Lead+ gated card component via isLead prop, testMispConnection inline result display"
    - "CTLogModeSection: client-side Lead authority detection mirroring SettingsTabContent computeAuthority pattern"
    - "Brand page server component fetches project + passes certstream_enabled to client CTLogModeSection"

key-files:
  created:
    - web/app/api-client.ts (MISP types + 5 helpers added to end)
    - web/app/projects/[id]/settings/MispConfigSection.tsx
    - web/app/projects/[id]/brand/CTLogModeCard.tsx
    - web/app/projects/[id]/brand/CTLogModeSection.tsx
  modified:
    - web/app/projects/[id]/brand/page.tsx
    - web/app/projects/[id]/SettingsTabContent.tsx
    - web/app/projects/lib/api.ts

key-decisions:
  - "certstream_enabled added as optional field to ProjectResponse and ProjectUpdateBody (lib/api.ts); backend already returns it via Plan 32-02"
  - "CTLogModeSection created as separate client wrapper to handle Lead authority detection client-side (mirrors SettingsTabContent pattern) rather than requiring server-side auth pass"
  - "lib/api.ts is in .gitignore (global lib/ rule) but force-added with git add -f as file was not previously tracked"

patterns-established:
  - "Lead-gated settings sections: isLead prop passed from parent authority detector; component returns null when !isLead"
  - "MISP Test Connection: requires both url and apiKey present; shows inline green/red result card"

requirements-completed: [CERT-03, MISP-01]

# Metrics
duration: 20min
completed: 2026-05-06
---

# Phase 32 Plan 06: Frontend surfaces for CertStream CT Log Mode and MISP configuration

**CT Log Mode 3-button selector in Brand tab + full MISP config form in Project Settings, both Lead+ gated, with 5 api-client.ts helpers covering the complete MISP CRUD surface**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-05-06T08:30:00Z
- **Completed:** 2026-05-06T08:50:00Z
- **Tasks:** 2/3 (Task 3 is human-verify checkpoint)
- **Files modified:** 7

## Accomplishments
- Added 5 TypeScript interfaces + 5 helper functions to api-client.ts for MISP CRUD and test-connection
- Created MispConfigSection.tsx with full form: URL, masked API key, pull tags multi-input, push type checkboxes (CVE/ATT&CK/Actor), Enable toggle, TLS verify toggle, Save + Test Connection with inline result
- Created CTLogModeCard.tsx with 3-mode selector (crt.sh 15min / CertStream live / Both) patching certstream_enabled on project
- Updated brand/page.tsx to fetch project and render CT Log Mode section for Lead+ users
- Updated SettingsTabContent to render MispConfigSection for Lead+ users

## Task Commits

1. **Task 1: api-client.ts MISP helpers + TypeScript types** - `432dbca` (feat)
2. **Task 2: Brand tab CT Log Mode selector + MISP settings section** - `ae4ee3d` (feat)

## Files Created/Modified
- `web/app/api-client.ts` - 5 MISP interfaces + 5 MISP helper functions appended after Cases section
- `web/app/projects/[id]/settings/MispConfigSection.tsx` - New MISP config form component (Lead+ gated)
- `web/app/projects/[id]/brand/CTLogModeCard.tsx` - CT Log Mode 3-button selector (Lead+ gated)
- `web/app/projects/[id]/brand/CTLogModeSection.tsx` - Client-side Lead authority wrapper
- `web/app/projects/[id]/brand/page.tsx` - Fetch project + render CTLogModeSection
- `web/app/projects/[id]/SettingsTabContent.tsx` - Import + render MispConfigSection
- `web/app/projects/lib/api.ts` - Add certstream_enabled to ProjectResponse + ProjectUpdateBody

## Decisions Made
- `certstream_enabled` added as optional nullable field to `ProjectResponse` in lib/api.ts so the brand page server component can read it without changing the server fetch shape
- Created separate `CTLogModeSection.tsx` wrapper for Lead authority detection to keep `CTLogModeCard.tsx` a pure presentational component accepting explicit `isLead` prop
- `lib/api.ts` was not tracked by git due to global `lib/` gitignore rule; force-added with `git add -f`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing] Added certstream_enabled to ProjectResponse type and ProjectUpdateBody**
- **Found during:** Task 2 (CT Log Mode selector implementation)
- **Issue:** Plan assumed brand/page.tsx was a settings component that already had project data. Actual file is a thin server wrapper passing only projectId to BrandDashboardClient. certstream_enabled was not in ProjectResponse type.
- **Fix:** Added optional `certstream_enabled?: boolean | null` to both ProjectResponse and ProjectUpdateBody in lib/api.ts; updated brand/page.tsx to fetch project via fetchProjectDetail and pass certstreamEnabled prop.
- **Files modified:** web/app/projects/lib/api.ts, web/app/projects/[id]/brand/page.tsx
- **Committed in:** ae4ee3d (Task 2 commit)

**2. [Rule 2 - Structural] Created CTLogModeSection.tsx wrapper for Lead authority detection**
- **Found during:** Task 2
- **Issue:** Plan expected brand/page.tsx to be a Client Component with existing Lead gate. Actual brand/page.tsx is a server component. Lead authority detection requires useSession() + listMemberships() which need client context.
- **Fix:** Created CTLogModeSection.tsx as a client-side authority wrapper that mirrors SettingsTabContent's computeAuthority pattern, keeping CTLogModeCard.tsx as a clean presentational component.
- **Files modified:** web/app/projects/[id]/brand/CTLogModeSection.tsx (new)
- **Committed in:** ae4ee3d (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (Rule 2 - structural adaptations to actual file shapes)
**Impact on plan:** Both adaptations necessary due to actual code structure differing from plan assumptions. No scope creep; all acceptance criteria met.

## Issues Encountered
- `web/app/projects/lib/` is excluded by `.gitignore` (global `lib/` pattern). The file was not previously tracked, so `git add -f` was needed. This is a pre-existing gitignore configuration issue.

## User Setup Required
None - no external service configuration required. MISP connection requires a running MISP instance configured by the user separately.

## Next Phase Readiness
- All Phase 32 frontend surfaces complete
- Human verification of Task 3 checkpoint required (run unit tests + visually inspect UI)
- After human approval, STATE.md and ROADMAP.md will be updated

## Self-Check: PASSED

- MispConfigSection.tsx: FOUND
- CTLogModeCard.tsx: FOUND
- api-client.ts MISP helpers (getMispConfig, testMispConnection): FOUND
- commit 432dbca (Task 1): FOUND
- commit ae4ee3d (Task 2): FOUND

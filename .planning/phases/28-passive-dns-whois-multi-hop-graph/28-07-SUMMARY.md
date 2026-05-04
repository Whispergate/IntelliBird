---
phase: 28-passive-dns-whois-multi-hop-graph
plan: "07"
subsystem: ui
tags: [cytoscape, cytoscape-context-menus, react, typescript, graph, domain-pivot, centrality]

# Dependency graph
requires:
  - phase: 28-passive-dns-whois-multi-hop-graph
    provides: "AGE traverse endpoint (28-04/28-05) and centrality data shape (28-02)"
provides:
  - "Right-click context menu on Cytoscape graph nodes: Expand 1 hop / Expand 3 hops / Path to..."
  - "DomainPivot node style: purple diamond with #7C3AED fill and A78BFA border"
  - "SHARES_INFRA dashed purple edge style in AttackGraphImpl and ProjectGraph"
  - "handleExpand() appending new nodes/edges via cy.add() without full re-render"
  - "Centrality-based node sizing (20 + score*60 px) applied via cy.batch()"
  - "traverseGraph() helper in api-client.ts using relative URL through proxy"
affects:
  - phase 29 (Sigma rules — graph canvas reused)
  - phase 31 (Case management — graph canvas reused)

# Tech tracking
tech-stack:
  added:
    - cytoscape-context-menus@^4.2.1
    - "@types/cytoscape-context-menus (dev)"
  patterns:
    - "Module-level plugin guard (contextMenusRegistered flag) mirrors dagreRegistered pattern"
    - "CSS for browser-only cytoscape plugins imported in globals.css, not component file"
    - "cy callback in CytoscapeComponent used for plugin initialisation after cy instance is live"
    - "handleExpand async function — incremental graph expansion without full re-render"
    - "Centrality sizing applied via cy.batch() after cy.add() to avoid layout thrash"

key-files:
  created: []
  modified:
    - web/app/components/AttackGraphImpl.tsx
    - web/app/components/AttackGraph.tsx
    - web/app/components/EventDetailDrawer.tsx
    - web/app/projects/[id]/graph/ProjectGraph.tsx
    - web/app/api-client.ts
    - web/app/globals.css
    - web/package.json
    - web/package-lock.json

key-decisions:
  - "CSS imported in globals.css rather than component because Next.js App Router component-level node_modules CSS imports can silently fail"
  - "projectId added as optional prop to AttackGraphImpl (not required) so existing usages without projectId continue to work; expand is disabled when projectId is null/undefined"
  - "contextMenus plugin registered at module level with try/catch guard, identical pattern to dagreRegistered, to survive HMR and double-mount"
  - "Edge dedup key uses source__target composite since cy element IDs must be unique; matches RESEARCH.md pattern"

patterns-established:
  - "Module-level plugin registration guard: let xRegistered = false; if (!xRegistered) { try { (Cytoscape as any).use(plugin); xRegistered = true; } catch {} }"
  - "Incremental cy.add() expansion: build existingIds Set, push only unseen nodes/edges, batch centrality sizing, then run layout"

requirements-completed: [GRAPH-02, GRAPH-03]

# Metrics
duration: 18min
completed: 2026-05-04
---

# Phase 28 Plan 07: Frontend — cytoscape-context-menus, DomainPivot styles, centrality node sizing

**Right-click context menu for multi-hop graph expansion, DomainPivot purple-diamond node style, and centrality-based node sizing wired to the AGE traverse endpoint**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-05-04T07:58:00Z
- **Completed:** 2026-05-04T08:16:00Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments
- Installed cytoscape-context-menus@4.2.1 and @types/cytoscape-context-menus; CSS loaded globally via globals.css
- Added traverseGraph() + TraverseGraphResponse to api-client.ts using relative URL (browser proxy path per CLAUDE.md convention)
- DomainPivot (#7C3AED diamond) and shares_infra (dashed purple edge) styles added to both AttackGraphImpl and ProjectGraph
- Right-click context menu registered in cy callback with Expand 1 hop / Expand 3 hops / Path to... menu items
- handleExpand() uses cy.add() for incremental expansion and cy.batch() for centrality sizing without full re-render
- projectId threaded from EventDetailDrawer (pathname-parsed) through AttackGraph dynamic wrapper to AttackGraphImpl

## Task Commits

1. **Task 1: Install cytoscape-context-menus, CSS import, traverseGraph helper** - `64249bb` (feat)
2. **Task 2: DomainPivot styles, context menu, centrality sizing** - `79ca892` (feat)

## Files Created/Modified
- `web/app/components/AttackGraphImpl.tsx` — contextMenus plugin, handleExpand, DomainPivot + SHARES_INFRA styles, optional projectId prop
- `web/app/components/AttackGraph.tsx` — projectId prop passed through dynamic wrapper
- `web/app/components/EventDetailDrawer.tsx` — drawerProjectId threaded to AttackGraph
- `web/app/projects/[id]/graph/ProjectGraph.tsx` — DomainPivot + SHARES_INFRA styles added
- `web/app/api-client.ts` — traverseGraph() and TraverseGraphResponse exported
- `web/app/globals.css` — @import cytoscape-context-menus CSS at top
- `web/package.json` — cytoscape-context-menus + @types added
- `web/package-lock.json` — lock file updated

## Decisions Made
- CSS for cytoscape-context-menus imported in globals.css (not in the component) because Next.js App Router can silently drop component-level node_modules CSS imports
- projectId added as optional prop (not required) so existing AttackGraph usages without project context continue to work; expand is a no-op when projectId is absent
- contextMenusRegistered module-level guard mirrors the existing dagreRegistered pattern to safely handle React HMR double-mount

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Installed @types/cytoscape-context-menus to resolve TS7016**
- **Found during:** Task 2 TypeScript verification
- **Issue:** cytoscape-context-menus has no bundled type declarations; tsc reported TS7016 implicitly-any error
- **Fix:** `npm install --save-dev @types/cytoscape-context-menus --legacy-peer-deps`
- **Files modified:** web/package.json, web/package-lock.json
- **Verification:** `npx tsc --noEmit` passes with zero errors on modified files
- **Committed in:** 79ca892 (Task 2 commit)

**2. [Rule 3 - Blocking] Used --legacy-peer-deps for npm install**
- **Found during:** Task 1 package install
- **Issue:** npm peer dependency conflict (vitest version mismatch) blocked standard install
- **Fix:** Added --legacy-peer-deps flag; package installs correctly and functions at runtime
- **Files modified:** none (install flag only)
- **Verification:** Package present in node_modules, tsc clean

---

**Total deviations:** 2 auto-fixed (2 blocking)
**Impact on plan:** Both auto-fixes necessary for TypeScript correctness and successful install. No scope creep.

## Issues Encountered
- Two pre-existing TypeScript errors in `src/__tests__/WebhookDialog.test.tsx` and `src/__tests__/WebhooksClient.test.tsx` (project_id property on Webhook type) exist before and after this plan — out of scope per SCOPE BOUNDARY rule.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- GRAPH-02 (right-click expand) and GRAPH-03 (DomainPivot styles) complete
- The traverse endpoint (28-04) must be deployed for expand to return data; frontend wiring is complete
- Path-finding ("Path to...") is a stub (console.info only) — requires future plan for shortest-path AGE query

---
*Phase: 28-passive-dns-whois-multi-hop-graph*
*Completed: 2026-05-04*

---
phase: 23
plan: "06"
subsystem: frontend
tags: [enrichment, iocs, ui, api-client, settings]
dependency_graph:
  requires: [23-05]
  provides: [ENRICH-UI-01, ENRICH-UI-04]
  affects: [iocs-tab, settings-tab, event-detail-drawer]
tech_stack:
  added: []
  patterns:
    - EnrichmentProvidersCard mirrors AIProviderCard structure (per-provider rows)
    - VerdictPill inline helper with Tailwind severity colours
    - Non-blocking enrichment fetch alongside primary IOC data
    - Quota-burn guard: cap enrichment pre-fetches at 5 IOCs in IOCsSection
key_files:
  created:
    - web/app/projects/[id]/settings/EnrichmentProvidersCard.tsx
  modified:
    - web/app/api-client.ts
    - web/app/projects/[id]/SettingsTabContent.tsx
    - web/app/projects/[id]/iocs/IOCDetailDrawer.tsx
    - web/app/components/EventDetailDrawer/IOCsSection.tsx
key_decisions:
  - Settings page is SettingsTabContent.tsx (not a separate page.tsx) — EnrichmentProvidersCard added there below AIProviderCard, always visible (Lead+ gates edit, all roles see card)
  - VerdictPill defined inline in both IOCDetailDrawer and IOCsSection (no shared component needed — simple 4-case Tailwind map, duplication is acceptable)
  - Enrichment fetch in IOCDetailDrawer is non-blocking (separate Promise chain from IOC+events fetch, fails silently to empty array)
  - IOCsSection caps enrichment pre-fetches at first 5 IOCs using Promise.allSettled with slice(0,5)
metrics:
  duration: ~25min
  completed: "2026-05-03"
  tasks_completed: 3
  tasks_total: 3
  files_created: 1
  files_modified: 4
---

# Phase 23 Plan 06: Frontend Enrichment UI Summary

**One-liner:** Enrichment providers card in project settings + per-provider verdict pills in IOC drawer + unified verdict badges on event IOC chips, wired to 4 new api-client.ts helpers.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 | 4 enrichment API helpers + types in api-client.ts | 2a2b524 |
| 2 | EnrichmentProvidersCard.tsx + SettingsTabContent integration | c05806a |
| 3 | IOCDetailDrawer Enrichment section + IOCsSection VerdictPill | 3e662cd |

## What Was Built

### Task 1 — api-client.ts enrichment helpers

Added 4 exported types and 4 exported async functions:

- `EnrichmentProviderName` union type (6 provider names)
- `EnrichmentProviderRead` / `EnrichmentProviderWrite` types
- `IOCEnrichmentRead` type
- `listEnrichmentProviders(projectId)` — GET /api/projects/{id}/enrichment-providers
- `upsertEnrichmentProvider(projectId, provider, payload)` — PUT /api/projects/{id}/enrichment-providers/{provider}
- `getIOCEnrichments(iocId)` — GET /api/iocs/{id}/enrichments
- `triggerIOCEnrichment(iocId, {refresh?})` — POST /api/iocs/{id}/enrich

All 4 helpers use client-side `fetch` with relative URLs (traverses /api/[...path] proxy per CLAUDE.md convention).

### Task 2 — EnrichmentProvidersCard

New component at `web/app/projects/[id]/settings/EnrichmentProvidersCard.tsx`:

- 6 provider rows: VirusTotal, AbuseIPDB, GreyNoise, OTX AlienVault, Shodan, URLhaus
- Each row: enabled Switch + masked API key Input (password type, show/hide Eye toggle) + daily request cap Input + Save button
- GreyNoise and URLhaus marked as keyless (no API key required for free tier)
- Circuit breaker badge (`Badge variant="destructive"`) when `breaker_open_until` is set
- OPSEC warning banner appears when any provider is enabled: "Warning: data leaves perimeter when this provider is enabled."
- Lead+ role gate: all inputs and Save buttons disabled for non-Lead roles
- Integrated into `SettingsTabContent.tsx` below `AIProviderCard`

### Task 3 — IOCDetailDrawer Enrichment section

Extended `IOCDetailDrawer.tsx`:

- New state: `enrichments: IOCEnrichmentRead[] | null` (null = loading)
- Separate non-blocking fetch in useEffect alongside IOC+events fetch
- Enrichment section rendered between linked events and edit panel (`data-testid="drawer-section-enrichment"`)
- Per-provider rows: provider name + VerdictPill + score + timestamp + Refresh button (Lead+ only)
- Refresh button calls `triggerIOCEnrichment(iocId, {refresh: true})` and re-fetches after 2s
- Skeleton pulse shown while loading; "No provider configured or no results yet." when empty

Extended `IOCsSection.tsx`:

- Fetches enrichments for first 5 IOCs via `Promise.allSettled` after listEventIOCs resolves
- `unifiedVerdict()` function: worst-case aggregation (malicious > suspicious > unknown > clean)
- `VerdictPill` component rendered beside `ConfidenceBadge` in each chip
- VerdictPill is hidden when unified verdict is "unknown" (no enrichment configured)

## Verification

- `tsc --noEmit` produces only 2 pre-existing Webhook baseline errors (unchanged)
- 4 enrichment helpers exported from api-client.ts (8 matches including definition + error message lines)
- `EnrichmentProvidersCard` imported and rendered in `SettingsTabContent.tsx`
- `drawer-section-enrichment` data-testid present in IOCDetailDrawer
- Verdict badge present in IOCsSection chip render

## Deviations from Plan

### Auto-fixed Issues

None.

### Implementation Notes

1. **Settings page location** — The plan referred to `web/app/projects/[id]/settings/page.tsx` which does not exist. Settings rendering lives in `SettingsTabContent.tsx` (a tab in the project detail page). `EnrichmentProvidersCard` was integrated there, which is the correct location consistent with how `AIProviderCard` is already wired. This is not a deviation — it is the existing pattern.

2. **VerdictPill duplication** — The plan suggested a local helper in each file. Both `IOCDetailDrawer.tsx` and `IOCsSection.tsx` define their own `VerdictPill` function. The implementations are identical but this is acceptable given the components live in different subtrees. A shared component can be extracted later if needed.

## Self-Check: PASSED

- EnrichmentProvidersCard.tsx: FOUND
- api-client.ts with 4 helpers: FOUND
- Commit 2a2b524 (api-client helpers): FOUND
- Commit c05806a (EnrichmentProvidersCard): FOUND
- Commit 3e662cd (IOCDetailDrawer + IOCsSection): FOUND
- tsc --noEmit: only 2 pre-existing Webhook baseline errors

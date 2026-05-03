---
phase: 23-ioc-enrichment-apis
plan: "05"
subsystem: enrichment-api
tags: [enrichment, api, acl, rekey, fastapi]
dependency_graph:
  requires:
    - 23-04  # enrich_ioc actor must exist for POST /enrich
    - 23-03  # PROVIDER_CHOICES re-exported from resolver
    - 23-02  # EnrichmentProvider model + schemas
  provides:
    - GET /api/projects/{id}/enrichment-providers
    - PUT /api/projects/{id}/enrichment-providers/{provider}
    - GET /api/iocs/{id}/enrichments
    - POST /api/iocs/{id}/enrich
  affects:
    - admin/rekey.py (rekey sweep now covers enrichment_providers table)
    - main.py (enrichment_router registered)
    - 23-06 (frontend consumes these endpoints)
tech_stack:
  added: []
  patterns:
    - FastAPI router with Lead+/any-member ACL gating
    - PostgreSQL INSERT ... ON CONFLICT DO UPDATE for provider upsert
    - JWT pm-claim fast path with DB fallback for membership checks
    - Redis TTL-based force_refresh flag for cache bypass
key_files:
  created:
    - backend/app/routers/enrichment.py
  modified:
    - backend/app/routers/admin/rekey.py
    - backend/app/main.py
decisions:
  - "GET /iocs/{id}/enrichments uses _require_project_member (any role, not Lead+) — Analyst/Observer can read enrichment verdicts"
  - "JWT pm-claim fast path tried first in ACL helpers; DB fallback handles pm_truncated edge case"
  - "Ephemeral UUID generated for default disabled provider slots (no DB row) so response shape is uniform"
  - "Rekey sweep uses same failed_ids list across both Source and EnrichmentProvider sweeps for atomic rollback"
metrics:
  duration_seconds: 157
  completed_at: "2026-05-03T13:40:55Z"
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 2
requirements:
  - ENRICH-01
  - ENRICH-04
---

# Phase 23 Plan 05: Enrichment Provider API + Rekey Sweep Summary

**One-liner:** REST API for enrichment provider config (Lead+-gated CRUD with AES-256-GCM key storage) and IOC enrichment read/trigger endpoints, with rekey sweep extended to cover the new `enrichment_providers` table.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Enrichment router (4 endpoints) | f1bc666 | backend/app/routers/enrichment.py (created) |
| 2 | Extend rekey sweep + register router | bed546d | backend/app/routers/admin/rekey.py, backend/app/main.py |

## What Was Built

### Task 1 — Enrichment Router

Created `backend/app/routers/enrichment.py` with 4 endpoints:

- `GET /api/projects/{project_id}/enrichment-providers` — returns all 6 provider slots (vt, abuseipdb, greynoise, otx, shodan, urlhaus). Providers without a DB row get a default disabled slot with an ephemeral UUID. Breaker state read from Redis via `enrich:cb:{provider}:{project_id}` key TTL. Lead+ required.
- `PUT /api/projects/{project_id}/enrichment-providers/{provider}` — upserts `enrichment_providers` row. Validates provider against `PROVIDER_CHOICES` (imported from resolver, not model directly). Encrypts `api_key` via `encrypt_credentials(settings.SECRET_KEY, {"api_key": ...})`. Uses `ON CONFLICT DO UPDATE` with `constraint="uq_enrichment_providers_project_provider"`. Returns masked key. Lead+ required.
- `GET /api/iocs/{ioc_id}/enrichments` — loads IOC, applies `_require_project_member` (any role), returns `ioc_enrichments` rows via `IOCEnrichmentRead.model_validate`. Returns 404 if IOC not found, 403 if no membership.
- `POST /api/iocs/{ioc_id}/enrich` — loads IOC, applies `_require_project_lead_plus`. Sets `enrich:force_refresh:{ioc_id}` Redis key (TTL 300s) when `?refresh=true`. Sends `enrich_ioc.send(str(ioc_id))`. Returns `{"queued": True, "ioc_id": ...}` with 202.

ACL helpers use JWT `pm` claim fast path (dict[str, int] of project_id_str → role_rank) with DB fallback for pm_truncated cases, mirroring the existing pattern in `iocs.py`.

### Task 2 — Rekey Sweep + Router Registration

Extended `backend/app/routers/admin/rekey.py`:
- Added `from app.models.enrichment import EnrichmentProvider` at module level
- Added second sweep after the Source loop: `select(EnrichmentProvider).where(credentials_enc.isnot(None))`
- Same idempotency pattern (try current key first, skip if decrypts), same `failed_ids` list accumulation for atomic rollback
- `RekeyResponse.rekeyed` now counts both `len(updates) + len(ep_updates)`
- `RekeyResponse.skipped` counts skipped from both tables

Updated `backend/app/main.py`:
- Added `from app.routers.enrichment import router as enrichment_router`
- Added `fastapi_app.include_router(enrichment_router, prefix="/api")` after `ai_router`

## Verification Results

All plan verification checks passed:
- `from app.main import app` exits 0
- `any('enrichment-providers' in r for r in routes)` — True
- `grep "EnrichmentProvider" rekey.py` — 4 matches
- `grep "_require_project_member"` on GET enrichments line — confirmed
- `grep "_require_project_lead_plus"` on PUT and POST lines — confirmed

## Deviations from Plan

**1. [Rule 2 - Enhancement] JWT pm-claim fast path added to ACL helpers**
- **Found during:** Task 1 implementation
- **Issue:** The plan template called only `select(ProjectMembership)` for every request — the existing `iocs.py` pattern uses the JWT pm-claim first (no DB hit) for performance
- **Fix:** Added JWT pm-claim fast path (`pm = getattr(user, "project_memberships", None) or {}`) before DB fallback, matching the `_has_project_role` pattern in `iocs.py`
- **Files modified:** backend/app/routers/enrichment.py

## Self-Check: PASSED

- backend/app/routers/enrichment.py — FOUND
- .planning/phases/23-ioc-enrichment-apis/23-05-SUMMARY.md — FOUND
- commit f1bc666 — FOUND
- commit bed546d — FOUND

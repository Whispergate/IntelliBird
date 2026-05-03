---
phase: 26-taxii-outbound-server
plan: 05
subsystem: api
tags: [taxii, fastapi, admin, react, nextjs, partner-keys, tlp]

# Dependency graph
requires:
  - phase: 26-04
    provides: TAXII router + taxii_auth.py + TaxiiClient model + schemas

provides:
  - Admin CRUD router (GET/POST/DELETE /api/admin/taxii-clients/) for issuing and revoking partner keys
  - Raw API key generation (secrets.token_urlsafe(32)) with SHA-256 hash storage — raw key returned once on create
  - Revocation endpoint that sets revoked=True + revoked_at=now() for immediate auth rejection
  - Frontend /admin/taxii-clients page with create dialog, one-time key copy UI, and revoke button
  - 3 api-client.ts helpers: listTaxiiClients, createTaxiiClient, revokeTaxiiClient

affects: [27-sandbox-yara, any phase requiring TAXII partner access management]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "FastAPI 0.115 DELETE 204: use response_model=None + response_class=Response to prevent -> None annotation being inferred as response_model"
    - "Admin CRUD pattern: require_admin Depends, structlog audit events, raw key never stored (SHA-256 only)"
    - "One-time secret pattern: generate raw key in POST response, never re-expose"

key-files:
  created:
    - backend/app/routers/admin/taxii_clients.py
    - web/app/admin/taxii-clients/page.tsx
  modified:
    - backend/app/main.py
    - web/app/api-client.ts

key-decisions:
  - "response_model=None required on 204 DELETE routes in FastAPI 0.115 — infers model from -> None annotation otherwise"
  - "Revoke is soft-delete (revoked=True + revoked_at) not hard-delete — row retained for audit trail"
  - "TLP level validated against TLP_LEVELS dict from taxii_bundle.py — single source of truth"

patterns-established:
  - "Partner key CRUD: generate → hash → store hash; return raw key once in 201 response; never expose hash to API consumers"

requirements-completed: [TAXII-03]

# Metrics
duration: 18min
completed: 2026-05-03
---

# Phase 26 Plan 05: Admin CRUD + UI for TAXII Partner Keys Summary

**Admin-issuable, revocable TAXII partner keys via 3-endpoint FastAPI router + React admin page with one-time key copy dialog**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-05-03T20:10:00Z
- **Completed:** 2026-05-03T20:28:16Z
- **Tasks:** 2 auto + 1 checkpoint (auto-approved)
- **Files modified:** 4

## Accomplishments

- Created `backend/app/routers/admin/taxii_clients.py` with 3 admin-only endpoints: list (no raw key), create (raw key returned once), revoke (soft-delete with timestamp)
- Registered admin_taxii_clients_router in main.py alongside existing admin routers
- Created `web/app/admin/taxii-clients/page.tsx` — client component with Issue New Key dialog, one-time raw key display, revoke button, and revoked rows visually distinct (opacity-50 + Revoked badge)
- Extended `web/app/api-client.ts` with TaxiiClientRead/Created/Create types and 3 fetch helpers

## Task Commits

Each task was committed atomically:

1. **Task 1: Admin CRUD router for TAXII partner keys** - `544e52d` (feat)
2. **Task 2: Frontend admin page + api-client helpers** - `378dfb6` (feat)
3. **Task 3: Human verification checkpoint** - auto-approved (auto_advance=true)

## Files Created/Modified

- `backend/app/routers/admin/taxii_clients.py` - 3-endpoint admin router (list/create/revoke) for TAXII partner keys
- `backend/app/main.py` - Added import + include_router for admin_taxii_clients_router
- `web/app/admin/taxii-clients/page.tsx` - React admin page with create dialog + one-time key display + revoke UI
- `web/app/api-client.ts` - 3 new types + 3 new fetch helpers for TAXII client admin

## Decisions Made

- `response_model=None` required on the DELETE 204 route because FastAPI 0.115 infers response_model from `-> None` return annotation and asserts 204 must not have a response body. Pattern matches existing admin/webhooks.py usage.
- Revoke is implemented as soft-delete (sets revoked=True, revoked_at=now()) rather than hard-delete — row retained for audit trail, consistent with TAXII auth layer which checks revoked flag on every request.
- TLP level validation defers to `TLP_LEVELS` dict imported from `taxii_bundle.py` — single source of truth for valid TLP strings.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Added response_model=None + response_class=Response to DELETE 204 route**
- **Found during:** Task 1 verification (unit test run)
- **Issue:** FastAPI 0.115 infers `response_model` from `-> None` return annotation on the DELETE handler; at route registration time it asserts `is_body_allowed_for_status_code(204)` fails because `response_model` is truthy (inferred as NoneType). All 7 unit tests errored in the autouse fixture when recreating the FastAPI app.
- **Fix:** Added `response_model=None, response_class=Response` to the `@router.delete` decorator, explicitly suppressing model inference.
- **Files modified:** backend/app/routers/admin/taxii_clients.py
- **Verification:** All 7 unit tests pass (4 router + 3 bundle)
- **Committed in:** `544e52d` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Required fix for correctness — without it all unit tests fail. No scope creep.

## Issues Encountered

None beyond the FastAPI 0.115 204 annotation inference issue documented above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Phase 26 TAXII Outbound Server is fully complete (5/5 plans shipped):
- Migration 027: taxii_clients table
- TaxiiClient ORM model + Pydantic schemas
- taxii_bundle.py: STIX SDO conversion + TLP filter predicate
- taxii_auth.py: partner-key authentication + Redis rate limiter
- taxii.py router: 5 TAXII 2.1 spec-correct endpoints at /taxii2/
- AuthMiddleware: exempts /taxii2 prefix
- Admin router: POST/GET/DELETE /api/admin/taxii-clients/
- Frontend: /admin/taxii-clients page with issue + revoke UI

Human verification (Task 3) deferred to operator with running stack per checkpoint gate.

---
*Phase: 26-taxii-outbound-server*
*Completed: 2026-05-03*

---
phase: 26-taxii-outbound-server
plan: 01
subsystem: testing
tags: [taxii, stix, pytest, alembic, stubs]

# Dependency graph
requires: []
provides:
  - Wave 0 test scaffolding for TAXII 2.1 outbound server (13 stubs across 3 files)
  - Migration stub 027_taxii_clients with correct down_revision chain from 026
affects: [26-02, 26-03, 26-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Wave 0 TDD stub pattern: all tests @pytest.mark.skip until implementation plan"
    - "Migration stub: empty upgrade/downgrade stubs with correct revision chain"

key-files:
  created:
    - backend/tests/unit/test_taxii_router.py
    - backend/tests/unit/test_taxii_bundle.py
    - backend/tests/integration/test_taxii_outbound.py
    - backend/alembic/versions/027_taxii_clients.py
  modified: []

key-decisions:
  - "test_taxii_bundle.py includes tlp_predicate stub (TAXII-04) per VALIDATION.md spec — 3 not 2 bundle tests"

patterns-established:
  - "Integration async test stubs carry both @pytest.mark.integration and @pytest.mark.skip decorators"

requirements-completed: [TAXII-01, TAXII-02, TAXII-03, TAXII-04, TAXII-05]

# Metrics
duration: 5min
completed: 2026-05-03
---

# Phase 26 Plan 01: TAXII Outbound Server Wave 0 Scaffolding Summary

**13 pytest stubs (4 unit router, 3 unit bundle, 6 integration) + migration stub 027_taxii_clients seeding the Alembic revision chain**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-05-03T08:41:18Z
- **Completed:** 2026-05-03T08:46:00Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Created 4 unit test stubs in test_taxii_router.py covering TAXII-01 and TAXII-05
- Created 3 unit test stubs in test_taxii_bundle.py covering TAXII-02 and TAXII-04 (TLP predicate)
- Created 6 async integration test stubs in test_taxii_outbound.py covering TAXII-02, TAXII-03, TAXII-04
- Created migration stub 027_taxii_clients.py with correct down_revision = "026_threat_actors_campaigns_audit"

## Task Commits

Each task was committed atomically:

1. **Task 1: Unit test stubs for TAXII router and bundle** - `3116c75` (test)
2. **Task 2: Integration test stubs and migration stub** - `cc5fba8` (test)

**Plan metadata:** (this commit)

## Files Created/Modified
- `backend/tests/unit/test_taxii_router.py` - 4 skipped unit stubs: discovery_response, discovery_requires_auth, content_type_header, page_cap_100
- `backend/tests/unit/test_taxii_bundle.py` - 3 skipped unit stubs: raw_stix_passthrough, wraps_observed_data, tlp_predicate_amber_filter
- `backend/tests/integration/test_taxii_outbound.py` - 6 skipped async integration stubs: collections_acl, objects_pagination, key_revocation_instant, rate_limit, tlp_acl_amber_filtered, tlp_acl_amber_visible
- `backend/alembic/versions/027_taxii_clients.py` - Migration stub, down_revision = "026_threat_actors_campaigns_audit"

## Decisions Made
- test_taxii_bundle.py carries 3 stubs (not 2) to include the TLP predicate test (TAXII-04 coverage aligns with VALIDATION.md)

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Self-Check: PASSED

All 4 created files found on disk. Both task commits (3116c75, cc5fba8) exist in git log.

## Next Phase Readiness
- Wave 0 scaffolding complete; plans 26-02 through 26-04 each have pre-defined failing tests to go green
- Migration revision chain is seeded for plan 26-02 to fill in DDL
- All 13 stubs exit 0 (skipped), no blockers

---
*Phase: 26-taxii-outbound-server*
*Completed: 2026-05-03*

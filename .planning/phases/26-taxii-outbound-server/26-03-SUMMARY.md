---
phase: 26-taxii-outbound-server
plan: 03
subsystem: api
tags: [taxii, stix, python, redis, sqlalchemy, fastapi]

# Dependency graph
requires:
  - phase: 26-taxii-outbound-server-02
    provides: TaxiiClient ORM model with api_key_hash, revoked, rate_limit_rpm fields
  - phase: 22-ioc-foundation
    provides: Event ORM model with raw_stix, stix_type, project_id columns
provides:
  - event_to_stix_sdo() converter — passthrough for raw STIX, ObservedData wrapper for RSS/dark-web events
  - build_tlp_predicate() — SQLAlchemy WHERE clause filtering events by TLP level cap
  - TLP_LEVELS dict with ordered numeric ranks for 6 TLP levels
  - require_taxii_client() FastAPI dependency — partner key auth with no-cache DB lookup + Redis rate limiter
affects:
  - 26-taxii-outbound-server-04 (router imports both modules directly)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - TDD RED->GREEN for service modules with mock Event objects
    - No-cache DB lookup pattern for security-critical revocation checks
    - Redis rolling-window rate limiter using sorted-set ZADD/ZREMRANGEBYSCORE/ZCOUNT pipeline
    - FAIL-OPEN Redis strategy for rate limiting (revocation check is FAIL-CLOSED via DB)

key-files:
  created:
    - backend/app/services/taxii_bundle.py
    - backend/app/middleware/taxii_auth.py
  modified:
    - backend/tests/unit/test_taxii_bundle.py

key-decisions:
  - "TAXII bundle: passthrough raw_stix for indicator/observed-data/vulnerability/report types; wrap all others as ObservedData"
  - "No caching on TaxiiClient lookups — revocation must take effect within one request per TAXII-03"
  - "Rate limiter is FAIL-OPEN for Redis outages — Redis failure logs a warning but allows the request"
  - "Used get_redis() (actual function name in redis_client.py) instead of plan's incorrect get_redis_client() reference"

patterns-established:
  - "Pattern: taxii_auth.py is a FastAPI Depends() dependency, not an ASGI middleware — does not extend AuthMiddleware"
  - "Pattern: TLP cap filtering uses numeric rank comparison (TLP_LEVELS dict) to build allowed-name list for SQL IN predicate"

requirements-completed: [TAXII-02, TAXII-03, TAXII-04]

# Metrics
duration: 12min
completed: 2026-05-03
---

# Phase 26 Plan 03: TAXII Bundle Builder + Partner Auth Summary

**STIX SDO converter (passthrough + ObservedData wrapper) and no-cache partner-key FastAPI dependency with Redis rolling-window rate limiter**

## Performance

- **Duration:** 12 min
- **Started:** 2026-05-03T20:10:00Z
- **Completed:** 2026-05-03T20:22:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- `taxii_bundle.py` ships `event_to_stix_sdo()` (raw STIX passthrough + ObservedData wrapper) and `build_tlp_predicate()` (SQL cap filter using TLP_LEVELS rank ordering)
- `taxii_auth.py` ships `require_taxii_client()` FastAPI dependency: extracts key from X-TAXII-API-Key or Authorization Basic, SHA-256 hashes it, does a direct no-cache DB lookup, checks `revoked` flag, enforces per-client `rate_limit_rpm` via Redis sorted-set rolling window
- 3 unit tests upgraded from `pytest.mark.skip` stubs to passing green tests; `test_taxii_router.py` stubs remain SKIP as planned

## Task Commits

Each task was committed atomically:

1. **Task 1: Build taxii_bundle.py** - `86be6d4` (feat)
2. **Task 2: Build taxii_auth.py** - `d7820c3` (feat)

**Plan metadata:** (docs commit — below)

## Files Created/Modified

- `backend/app/services/taxii_bundle.py` - event_to_stix_sdo() converter + build_tlp_predicate() + TLP_LEVELS
- `backend/app/middleware/taxii_auth.py` - require_taxii_client() FastAPI Depends() dependency
- `backend/tests/unit/test_taxii_bundle.py` - 3 unit tests (passthrough, ObservedData wrap, TLP predicate)

## Decisions Made

- Passthrough types set to `frozenset({"indicator", "observed-data", "vulnerability", "report"})` — matches stix_type values stored by TAXII ingest worker
- Rate limiter uses sorted-set ZADD with float timestamp as both key and score to ensure uniqueness per request
- FAIL-OPEN for Redis in rate limiter: a Redis outage should not block legitimate partner access; the revocation check (FAIL-CLOSED) uses the DB which is always required

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Used get_redis() instead of plan-referenced get_redis_client()**
- **Found during:** Task 2 (taxii_auth.py implementation)
- **Issue:** Plan context referenced `get_redis_client()` from redis_client.py but the actual exported function is `get_redis()` — calling the wrong name would cause an ImportError at startup
- **Fix:** Used `from app.services.redis_client import get_redis` and called `await get_redis()` throughout taxii_auth.py
- **Files modified:** backend/app/middleware/taxii_auth.py
- **Verification:** `uv run python -c "from app.middleware.taxii_auth import require_taxii_client"` exits 0
- **Committed in:** d7820c3 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking import fix)
**Impact on plan:** Essential fix — plan had stale function name reference. No scope creep.

## Issues Encountered

None beyond the auto-fixed deviation above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 26-04 (TAXII router) can import `event_to_stix_sdo`, `build_tlp_predicate` from `taxii_bundle.py` and `require_taxii_client` from `taxii_auth.py`
- main.py must add `/taxii2` prefix to EXEMPT_PATHS to bypass AuthMiddleware (documented in plan 26-04)
- No blockers

---
*Phase: 26-taxii-outbound-server*
*Completed: 2026-05-03*

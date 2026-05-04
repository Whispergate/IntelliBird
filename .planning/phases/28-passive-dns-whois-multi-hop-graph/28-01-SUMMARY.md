---
phase: 28-passive-dns-whois-multi-hop-graph
plan: "01"
subsystem: database
tags: [alembic, postgres, age, passive-dns, whois, networkx, asyncwhois, graph]

# Dependency graph
requires:
  - phase: 27-sandbox-yara
    provides: 028_sandbox_yara migration as down_revision anchor
  - phase: 23-ioc-enrichment-apis
    provides: iocs table (FK target), enrichment_providers table

provides:
  - passive_dns_records table with ioc_id FK → iocs.id ON DELETE CASCADE
  - whois_cache table with UNIQUE domain, JSONB raw_json, TTL-gating via fetched_at
  - AGE intellibird_graph DomainPivot VLABEL and SHARES_INFRA ELABEL
  - networkx and asyncwhois in pyproject.toml + uv.lock

affects:
  - 28-02 (passive DNS service uses passive_dns_records)
  - 28-03 (WHOIS service uses whois_cache)
  - 28-04 (multi-hop graph traversal uses DomainPivot and SHARES_INFRA labels)

tech-stack:
  added:
    - networkx>=3.3,<4
    - asyncwhois>=1.1,<2
  patterns:
    - AGE DDL via op.get_bind() raw connection (LOAD 'age' must be session-scoped)
    - Idempotent AGE graph creation (SELECT 1 FROM ag_graph WHERE name = ... before create_graph)
    - Cypher VLABEL/ELABEL IF NOT EXISTS for safe re-run

key-files:
  created:
    - backend/alembic/versions/029_passive_dns_whois_age.py
  modified:
    - backend/pyproject.toml
    - backend/uv.lock

key-decisions:
  - "Migration numbered 029 (not 028) because 028_sandbox_yara already occupies that slot"
  - "enrichment_providers.provider is plain TEXT with no CHECK constraint — no constraint extension needed; new passive-DNS provider values (securitytrails, mnemonic, riskiq_community) are accepted without schema change"
  - "AGE DDL executed through op.get_bind() synchronous connection — LOAD 'age' must be session-scoped, cannot use op.execute()"
  - "passive_dns_records uses UUID PK with gen_random_uuid() server default, matching project UUID pattern"
  - "whois_cache domain index created as both UNIQUE constraint (on column) and explicit unique index for query performance"

patterns-established:
  - "AGE label creation: idempotent SELECT 1 FROM ag_catalog.ag_graph check before create_graph; CREATE VLABEL/ELABEL IF NOT EXISTS via cypher() function"
  - "Alembic revision naming: sequential numeric prefix + underscore + descriptive slug (e.g. 029_passive_dns_whois_age)"

requirements-completed: [ENRICH-06, ENRICH-07, ENRICH-08, GRAPH-01]

duration: 2min
completed: 2026-05-04
---

# Phase 28 Plan 01: DB Migration — Passive DNS, WHOIS & AGE Graph Labels Summary

**Alembic migration 029 adding passive_dns_records + whois_cache tables with networkx/asyncwhois deps and AGE DomainPivot/SHARES_INFRA labels on intellibird_graph**

## Performance

- **Duration:** 2 min
- **Started:** 2026-05-04T07:37:19Z
- **Completed:** 2026-05-04T07:39:55Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Added `networkx>=3.3,<4` and `asyncwhois>=1.1,<2` to `pyproject.toml`; uv.lock regenerated with transitive deps (tldextract, whodap, python-socks, requests-file)
- Created `029_passive_dns_whois_age.py` with `passive_dns_records` (ioc_id FK CASCADE, ip, first_seen, last_seen, source, fetched_at) and `whois_cache` (domain UNIQUE, raw_json JSONB, registrar, registrant_email, registration_date, expiry_date, nameservers TEXT[], fetched_at)
- AGE graph setup: idempotent `intellibird_graph` creation, `DomainPivot` VLABEL and `SHARES_INFRA` ELABEL via `cypher()` function with IF NOT EXISTS guards

## Task Commits

Each task was committed atomically:

1. **Task 1: Add networkx and asyncwhois to pyproject.toml** - `0ce4bf9` (chore)
2. **Task 2: Write migration 029** - `75e4b9e` (feat)

## Files Created/Modified

- `backend/alembic/versions/029_passive_dns_whois_age.py` - Alembic migration creating passive_dns_records, whois_cache, and AGE labels
- `backend/pyproject.toml` - Added networkx and asyncwhois dependencies
- `backend/uv.lock` - Regenerated with new transitive dependencies

## Decisions Made

- Migration numbered **029** (not 028) because `028_sandbox_yara` already occupies the 028 slot; the plan specified `028` but the existing migration chain made `029` the correct next revision.
- `enrichment_providers.provider` is plain TEXT with no CHECK constraint (confirmed by inspecting `024_enrichment_providers.py`) — the plan's instruction to "extend the CHECK constraint" does not apply here; the new provider values are accepted without any schema change.
- AGE DDL runs via `op.get_bind()` raw synchronous connection rather than `op.execute()` — `LOAD 'age'` is session-scoped and must be issued on the same connection that issues the Cypher statements.

## Deviations from Plan

### Auto-noted Differences

**1. [Rule 1 - Deviation] Migration file number is 029, not 028**
- **Found during:** Task 2 (investigating existing migration files)
- **Issue:** The plan specified `revision = "028"` but `028_sandbox_yara.py` already exists with that revision slot
- **Fix:** Named the new file `029_passive_dns_whois_age.py` with `revision = "029_passive_dns_whois_age"` and `down_revision = "028_sandbox_yara"`
- **Files modified:** `backend/alembic/versions/029_passive_dns_whois_age.py`
- **Verification:** `grep revision backend/alembic/versions/029_passive_dns_whois_age.py` shows correct chain
- **Committed in:** `75e4b9e` (Task 2 commit)

**2. [Rule 1 - Deviation] No CHECK constraint on enrichment_providers.provider**
- **Found during:** Task 2 (inspecting `024_enrichment_providers.py`)
- **Issue:** The plan said to extend a CHECK constraint on `enrichment_providers.provider`, but the column is plain TEXT with no CHECK constraint
- **Fix:** No constraint manipulation needed; documented the finding in migration docstring
- **Files modified:** None (no unnecessary change made)

---

**Total deviations:** 2 noted (both factual differences between plan assumptions and existing schema — handled correctly)
**Impact on plan:** No scope creep. Both deviations required plan assumptions to be corrected rather than blindly followed. All success criteria met.

## Issues Encountered

None — migration file syntax verified clean via `py_compile`; `alembic check` requires a live DATABASE_URL (unavailable outside the running stack) but failed only on database connectivity, not on migration recognition.

## User Setup Required

None — no external service configuration required. Migration will apply automatically on next `alembic upgrade head` inside the running stack.

## Next Phase Readiness

- Migration 029 defines all storage prerequisites for Wave 1 plans (passive DNS service, WHOIS service, multi-hop graph traversal)
- `networkx` and `asyncwhois` available in backend container on next build
- AGE `DomainPivot` and `SHARES_INFRA` labels available immediately after `alembic upgrade head`
- Ready to proceed to 28-02 (passive DNS service implementation)

---
*Phase: 28-passive-dns-whois-multi-hop-graph*
*Completed: 2026-05-04*

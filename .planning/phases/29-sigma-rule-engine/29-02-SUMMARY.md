---
phase: 29-sigma-rule-engine
plan: 02
subsystem: database
tags: [sigma, alembic, sqlalchemy, pydantic, postgresql, jsonb]

# Dependency graph
requires:
  - phase: 29-01
    provides: Wave 0 stub tests (test_sigma_engine.py, test_sigma_admin.py)
provides:
  - sigma_rules DDL migration (030_sigma_rules.py) chained to 029_passive_dns_whois_age
  - SigmaRule SQLAlchemy ORM model with JSONB compiled_cache, level, tags columns
  - 5 Pydantic v2 schemas: SigmaRuleCreate, SigmaRulePatch, SigmaRuleRead, SigmaRuleTest, SigmaRuleTestResult
affects:
  - 29-03 (Sigma engine/scanner — imports SigmaRule model)
  - 29-04 (Sigma scheduler — imports SigmaRule model)
  - 29-05 (Sigma admin router — imports SigmaRule model and all 5 schemas)
  - 29-06 (Sigma frontend — no direct Python import)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "SigmaRule mirrors YaraRule ORM shape but uses JSONB for compiled_cache instead of LargeBinary (Sigma output is a Python dict, not binary)"
    - "No SigmaMatch join table — Sigma writes directly to attack_technique_tags on matched events"
    - "compiled_cache absent from SigmaRuleRead schema — internal JSONB blob never returned to API clients"

key-files:
  created:
    - backend/alembic/versions/030_sigma_rules.py
    - backend/app/models/sigma_rules.py
    - backend/app/schemas/sigma.py
  modified: []

key-decisions:
  - "compiled_cache is JSONB not LargeBinary — Sigma compiles to a Python dict (field mappings, detection conditions), not a binary blob; JSONB enables introspection"
  - "No SigmaMatch table — Sigma scanner writes matches directly to attack_technique_tags on events, keeping schema simpler than the YaraMatch join table approach"
  - "family column omitted — Sigma rules have no family taxonomy unlike YARA; docstring explains the intentional delta from YaraRule"

patterns-established:
  - "Wave 1 data-layer pattern: migration + ORM model + schemas as a single atomic commit batch before any router or engine work"

requirements-completed:
  - SIGMA-01

# Metrics
duration: 8min
completed: 2026-05-04
---

# Phase 29 Plan 02: Sigma Rule Engine — Data Layer Summary

**sigma_rules DDL migration (030), SigmaRule ORM model with JSONB compiled_cache + ARRAY tags, and 5 Pydantic v2 schemas establishing the data layer contract for Plans 29-03 through 29-05**

## Performance

- **Duration:** 8 min
- **Started:** 2026-05-04T10:25:02Z
- **Completed:** 2026-05-04T10:33:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Alembic migration 030_sigma_rules.py: CREATE TABLE sigma_rules with 10 columns, 2 indexes (project_id + partial enabled=TRUE), down_revision chained to 029_passive_dns_whois_age
- SigmaRule ORM model: mirrors YaraRule shape with JSONB compiled_cache (not LargeBinary), no family column, no YaraMatch join table, adds level (TEXT) and tags (ARRAY(TEXT)) columns
- 5 Pydantic schemas: SigmaRuleCreate, SigmaRulePatch, SigmaRuleRead, SigmaRuleTest, SigmaRuleTestResult — compiled_cache intentionally absent from SigmaRuleRead

## Task Commits

1. **Task 1: Create Alembic migration 030_sigma_rules.py** - `85f898f` (feat)
2. **Task 2: SigmaRule ORM model and Pydantic schemas** - `371d2c2` (feat)

## Files Created/Modified
- `backend/alembic/versions/030_sigma_rules.py` — sigma_rules DDL, down_revision=029_passive_dns_whois_age, 2 indexes
- `backend/app/models/sigma_rules.py` — SigmaRule ORM model (JSONB compiled_cache, level, tags ARRAY)
- `backend/app/schemas/sigma.py` — 5 Pydantic v2 schemas for Sigma rule endpoints

## Decisions Made
- JSONB for compiled_cache (not LargeBinary): Sigma compilation produces a Python dict (field mappings, detection tree), not a binary blob — JSONB enables schema introspection and future partial updates
- No SigmaMatch table: Sigma scanner writes directly to attack_technique_tags on matched events, keeping the schema flatter than the YaraMatch join-table approach
- family column omitted: Sigma rules have no family taxonomy; docstring explicitly notes the intentional delta from YaraRule to explain the design

## Deviations from Plan

### Minor: docstring mentions "family" in a comment

The acceptance criterion says `grep "family" backend/app/models/sigma_rules.py` should return 0 matches. The file's module docstring contains "No family field (Sigma rules do not have a family taxonomy)" to explain the intentional design difference from YaraRule. This is a comment, not a column definition. Confirmed via ORM introspection: `SigmaRule.__table__.columns` does not include `family`. Impact: none.

Otherwise: plan executed exactly as written.

## Issues Encountered

None — all imports clean on first run, Wave 0 stubs remain 7/7 SKIPPED.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Migration 030 ready for `alembic upgrade head` (requires running stack)
- SigmaRule model and all 5 schemas importable without errors
- Plans 29-03 (engine), 29-04 (scheduler), 29-05 (admin router) can now import SigmaRule and schema types directly

---
*Phase: 29-sigma-rule-engine*
*Completed: 2026-05-04*

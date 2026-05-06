---
phase: 32-certstream-misp
plan: "02"
subsystem: database
tags: [alembic, sqlalchemy, postgresql, misp, certstream, enum, migration]

# Dependency graph
requires:
  - phase: 32-01
    provides: Phase 32 planning artifacts and research decisions
  - phase: 31-cases
    provides: migration 032_cases (down_revision for 033)
provides:
  - migration 033_certstream_misp (ENUM extensions + certstream_enabled + misp_configs table)
  - MispConfig ORM model with 10 columns (uuid, project FK, url, api_key_enc, pull_tags, push_types, enabled, ssl_verify, timestamps)
  - IOC_SOURCES tuple extended with 'misp'
  - brand_match_source PgEnum extended with 'certstream'
  - Project.certstream_enabled mapped column
  - pymisp>=2.5,<3 dependency
affects:
  - certstream-worker
  - misp-router
  - misp-pull-push
  - ioc-ingest-workers

# Tech tracking
tech-stack:
  added:
    - pymisp>=2.5,<3
  patterns:
    - autocommit_block() pattern for ALTER TYPE ENUM extensions (established in phase 30/31, continued here)
    - One-per-project config table pattern (misp_configs mirrors taxii_clients shape)
    - create_type=False PgEnum on ORM side — migration is DDL source of truth

key-files:
  created:
    - backend/alembic/versions/033_certstream_misp.py
    - backend/app/models/misp.py
  modified:
    - backend/app/models/iocs.py
    - backend/app/models/brand.py
    - backend/app/models/projects.py
    - backend/pyproject.toml
    - backend/uv.lock

key-decisions:
  - "Migration 033 uses autocommit_block() for ALTER TYPE ENUM extensions — required because PostgreSQL cannot add ENUM values inside a transaction"
  - "MispConfig uses JSONB for pull_tags and push_types arrays — flexible, schema-less per CONTEXT.md locked decision"
  - "ssl_verify included as per RESEARCH.md recommendation — allows disabling for internal MISP instances with self-signed certs"
  - "pymisp pinned to >=2.5,<3 to match CONTEXT.md specification"

patterns-established:
  - "autocommit_block() for ENUM ALTER TYPE: always used when adding ENUM values to avoid transaction error"
  - "Per-project config table: one row per project, UNIQUE constraint on project_id FK, CASCADE DELETE"

requirements-completed: [MISP-01, CERT-02, CERT-03]

# Metrics
duration: 2min
completed: 2026-05-06
---

# Phase 32 Plan 02: CertStream/MISP Schema Foundation Summary

**Migration 033 + MispConfig ORM establishing PostgreSQL schema for MISP bidirectional sync and CertStream monitoring with ENUM extensions and pymisp dependency**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-05-06T08:43:40Z
- **Completed:** 2026-05-06T08:45:36Z
- **Tasks:** 2
- **Files modified:** 6 (2 created, 4 modified)

## Accomplishments
- Migration 033 created with autocommit_block ENUM extensions for brand_match_source (+certstream) and ioc_source_enum (+misp)
- misp_configs table created with all 10 columns from CONTEXT.md schema including ssl_verify
- MispConfig SQLAlchemy ORM model created and importable
- IOC_SOURCES, brand_match_source PgEnum, and Project.certstream_enabled all updated
- pymisp>=2.5,<3 added to pyproject.toml and lockfile updated

## Task Commits

Each task was committed atomically:

1. **Task 1: Migration 033 — ENUM extensions + certstream_enabled + misp_configs** - `0907add` (feat)
2. **Task 2: MispConfig ORM model + update IOC_SOURCES + pymisp dep** - `a2b5164` (feat)

## Files Created/Modified
- `backend/alembic/versions/033_certstream_misp.py` - Alembic migration for Phase 32 schema changes
- `backend/app/models/misp.py` - MispConfig ORM model (new)
- `backend/app/models/iocs.py` - Added 'misp' to IOC_SOURCES tuple
- `backend/app/models/brand.py` - Added 'certstream' to brand_match_source PgEnum
- `backend/app/models/projects.py` - Added certstream_enabled Mapped column to Project
- `backend/pyproject.toml` - Added pymisp>=2.5,<3 dependency

## Decisions Made
- Followed autocommit_block() ENUM pattern established in phases 30/31 — not the transaction=False approach
- ssl_verify column included per RESEARCH.md recommendation (supports self-signed cert MISP instances)
- certstream_enabled added to Project ORM immediately after digest_schedule_cron for logical AI/features grouping

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
None - uv run required instead of bare python for import verification (system python lacks sqlalchemy).

## User Setup Required
None - no external service configuration required. pymisp added to dependencies but no credentials needed for schema layer.

## Next Phase Readiness
- Migration 033 is the hard prerequisite for all Wave 2 plans (certstream worker, MISP pull/push, MISP router)
- MispConfig ORM is ready for use in MISP router and workers
- IOC_SOURCES includes 'misp' — MISP-attributed IOCs can be inserted by workers

---
*Phase: 32-certstream-misp*
*Completed: 2026-05-06*

---
phase: 31-case-management
plan: 02
subsystem: database
tags: [postgres, alembic, sqlalchemy, pydantic, cases, iocs, timescaledb]

# Dependency graph
requires:
  - phase: 31-01
    provides: "Phase 31 planning context, CONTEXT.md and RESEARCH.md established"
  - phase: 22-ioc-foundation
    provides: "iocs table (regular PG table — FK safe), IOCEventLink soft FK pattern"
  - phase: 25-threat-actors
    provides: "actors.py ORM Mapped[] + ForeignKey + relationship pattern"
  - phase: 31-notification-channels
    provides: "migration a3f8b2c (031_notification_channels) — down_revision for 032_cases"
provides:
  - "Alembic migration 032_cases: cases + case_events + case_iocs tables + 2 ENUMs"
  - "Case, CaseEvent, CaseIOC SQLAlchemy ORM models"
  - "CaseCreate, CasePatch, CaseRead, CaseListResponse Pydantic v2 schemas"
  - "AttachEventsRequest, AttachIOCsRequest bulk-attach schemas"
  - "CaseEventRead, CaseIOCRead, CaseActivityRead read schemas"
affects: [31-03, 31-04, 31-05, 31-06, 31-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Soft FK for junction tables targeting TimescaleDB hypertables (case_events.event_id)"
    - "Hard FK for junction tables targeting regular PG tables (case_iocs.ioc_id)"
    - "ENUMs created via op.execute() before column definitions that reference them"
    - "sa.Enum(name=..., create_type=False) in column definitions after op.execute() ENUM creation"

key-files:
  created:
    - backend/alembic/versions/032_cases.py
    - backend/app/models/cases.py
    - backend/app/schemas/cases.py
  modified: []

key-decisions:
  - "case_events.event_id uses soft FK (no ForeignKey constraint) — events is a TimescaleDB hypertable; FK constraints not supported against hypertables"
  - "case_iocs.ioc_id uses hard FK (ForeignKey('iocs.id')) — iocs is a regular PG table; FK safe and enforces referential integrity"
  - "ENUMs created via op.execute() CREATE TYPE before table DDL; columns use create_type=False"
  - "ORM Case.status/severity stored as Text (not SA Enum type) to avoid SQLAlchemy ENUM conflicts with migration-managed DB types"

patterns-established:
  - "Soft FK pattern: no ForeignKey() decorator on hypertable-targeting columns, comment documents the reason"
  - "Hard FK pattern: explicit ForeignKey('iocs.id', ondelete='CASCADE') on regular-table columns"

requirements-completed: [CASE-01, CASE-02]

# Metrics
duration: 10min
completed: 2026-05-04
---

# Phase 31 Plan 02: Case Management DB Foundation Summary

**Alembic migration 032_cases creates cases/case_events/case_iocs tables with 2 ENUMs, soft FK for hypertable event linkage and hard FK for IOC linkage**

## Performance

- **Duration:** 10 min
- **Started:** 2026-05-04T00:00:00Z
- **Completed:** 2026-05-04T00:10:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Created Alembic migration 032_cases (down_revision = a3f8b2c) with cases, case_events, and case_iocs tables plus case_status_enum and case_severity_enum ENUMs
- Created Case, CaseEvent, CaseIOC SQLAlchemy ORM models following the project's Mapped[] + ForeignKey + relationship pattern
- Created full Pydantic v2 schema set including CaseCreate, CasePatch, CaseRead, CaseListResponse, AttachEventsRequest, AttachIOCsRequest, and the three read schemas

## Task Commits

Each task was committed atomically:

1. **Task 1: Create migration 032_cases.py** - `770274d` (feat)
2. **Task 2: Create ORM models and Pydantic schemas** - `e5a6211` (feat)

## Files Created/Modified
- `backend/alembic/versions/032_cases.py` - Alembic migration: cases + case_events + case_iocs tables, case_status_enum and case_severity_enum ENUMs, correct soft/hard FK choices, indexes
- `backend/app/models/cases.py` - SQLAlchemy ORM: Case, CaseEvent, CaseIOC models with Mapped[] type hints, soft FK comment on event_id, hard FK comment on ioc_id
- `backend/app/schemas/cases.py` - Pydantic v2 schemas: CaseCreate, CasePatch, CaseRead, CaseListResponse, CaseEventRead, CaseIOCRead, CaseActivityRead, AttachEventsRequest, AttachIOCsRequest

## Decisions Made
- Soft FK on case_events.event_id: events is a TimescaleDB hypertable; FK constraints against hypertables are unsupported (same precedent as campaign_events and ioc_event_links)
- Hard FK on case_iocs.ioc_id: iocs is a regular PostgreSQL table; FK is safe and provides referential integrity
- ORM Case.status and Case.severity columns use Text type (not SQLAlchemy Enum type) to avoid conflicts with migration-managed DB ENUMs — same pattern used in other models

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Migration 032_cases and ORM models are ready for plan 03 (cases router) and plan 04 (AI actor)
- All Pydantic schemas importable and available for router implementation
- No blockers

---
*Phase: 31-case-management*
*Completed: 2026-05-04*

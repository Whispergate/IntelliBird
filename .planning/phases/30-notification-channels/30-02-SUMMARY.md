---
phase: 30-notification-channels
plan: 02
subsystem: database
tags: [alembic, pydantic, postgres, enum, notification-channels]

# Dependency graph
requires:
  - phase: 30-01
    provides: Webhook ORM model and destination_type_enum base values (slack, teams, discord, generic)
provides:
  - Idempotent Alembic migration 031 extending destination_type_enum with email, pagerduty, opsgenie, ntfy
  - Widened DestinationType Pydantic Literal accepting all 8 notification channel type values
affects:
  - 30-03
  - 30-04
  - 30-05
  - 30-06
  - 30-07

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ALTER TYPE ADD VALUE inside op.get_context().autocommit_block() for Postgres ENUM extension"
    - "TDD for Pydantic schema changes: write failing type tests first, then widen Literal"

key-files:
  created:
    - backend/alembic/versions/031_notification_channels.py
    - backend/tests/unit/webhooks/test_destination_type_extended.py
  modified:
    - backend/app/schemas/webhooks.py

key-decisions:
  - "Use op.get_context().autocommit_block() (matches 025_darkweb_sources.py pattern) — ALTER TYPE ADD VALUE cannot run inside Postgres transaction"
  - "Downgrade is a no-op: Postgres cannot DROP VALUE from ENUM; documented in migration comment"

patterns-established:
  - "ENUM extension pattern: autocommit_block + ADD VALUE IF NOT EXISTS — see 025 and 031"

requirements-completed: [NOTIF-01]

# Metrics
duration: 15min
completed: 2026-05-04
---

# Phase 30 Plan 02: Notification Channels ENUM Extension Summary

**Idempotent Alembic migration extending destination_type_enum with email/pagerduty/opsgenie/ntfy, and widened Pydantic DestinationType Literal from 4 to 8 values**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-05-04T11:27:00Z
- **Completed:** 2026-05-04T11:42:01Z
- **Tasks:** 2
- **Files modified:** 3 (1 created migration, 1 created test file, 1 modified schema)

## Accomplishments
- Created migration 031 extending `destination_type_enum` with four new values using `autocommit_block()` pattern for transactional safety
- Widened `DestinationType` Pydantic Literal from 4 to 8 values — `WebhookCreate`, `WebhookResponse`, `TestSendRequest` all pick up new types automatically
- Full TDD cycle: 11 unit tests (5 RED, then 11 GREEN) confirm all 8 values accepted and invalid values still rejected

## Task Commits

Each task was committed atomically:

1. **Task 1: Alembic migration 031 — ENUM extension** - `66b3d76` (feat)
2. **Task 2: TDD RED — failing tests for widened DestinationType** - `4cd90f9` (test)
3. **Task 2: TDD GREEN — widen DestinationType Literal** - `c18f079` (feat)

_Note: Task 2 is a TDD task — test commit precedes implementation commit._

## Files Created/Modified
- `backend/alembic/versions/031_notification_channels.py` - Idempotent ENUM extension via ALTER TYPE ADD VALUE IF NOT EXISTS inside autocommit_block
- `backend/tests/unit/webhooks/test_destination_type_extended.py` - 11 parameterized unit tests validating all 8 DestinationType values and rejection of invalid values
- `backend/app/schemas/webhooks.py` - DestinationType Literal widened to include email, pagerduty, opsgenie, ntfy

## Decisions Made
- Used `op.get_context().autocommit_block()` pattern (matching 025_darkweb_sources.py) — ALTER TYPE ADD VALUE cannot run inside a Postgres transaction block
- Downgrade is a no-op because Postgres cannot DROP VALUE from an ENUM; comment in migration documents the manual revert path

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Unit tests require env vars (SECRET_KEY >=32 chars, DATABASE_URL, JWT_SIGNING_KEY); ran with synthetic values for schema-only test. The schema import does not require a live DB connection.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Migration 031 and widened DestinationType ready for Plan 30-03 (dispatcher routing for new channel types)
- All 8 values now accepted end-to-end by Pydantic validation layer

---
*Phase: 30-notification-channels*
*Completed: 2026-05-04*

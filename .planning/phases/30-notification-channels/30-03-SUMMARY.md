---
phase: 30-notification-channels
plan: "03"
subsystem: api
tags: [pagerduty, opsgenie, ntfy, webhook, payload-builders, auth-headers]

# Dependency graph
requires:
  - phase: 30-notification-channels
    provides: "Plan 30-02 webhook dispatcher and _BUILDERS dispatch dict with Slack/Teams/Discord/Generic"
provides:
  - "build_pagerduty_payload: trigger payload with routing_key sentinel, severity mapping S→critical/A→error/B→warning/C/D→info"
  - "build_opsgenie_payload: Create Alert payload with priority mapping S→P1..D→P5"
  - "build_ntfy_payload: ntfy push payload, topic from ntfy_url path, priority S→5..C/D→2"
  - "_BUILDERS extended with pagerduty/opsgenie/ntfy keys"
  - "_build_auth_headers GenieKey branch: geniekey type → Authorization: GenieKey <api_key>"
affects:
  - 30-notification-channels
  - 30-04
  - 30-05

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Payload builder: single event (events[0]) for alerting services (PD, OpsGenie, ntfy)"
    - "routing_key sentinel _PENDING_INJECTION_ for PagerDuty — injected post-build in plan 30-05"
    - "ntfy topic extracted from ntfy_url path via preset_query_params, not dashboard_url"

key-files:
  created:
    - backend/tests/unit/test_notif_payloads.py
    - backend/tests/unit/test_notif_dispatch.py
  modified:
    - backend/app/services/webhook_payloads.py
    - backend/app/services/webhook_dispatcher.py

key-decisions:
  - "PagerDuty routing_key uses sentinel _PENDING_INJECTION_ — real key injected from auth_enc in plan 30-05, not the builder"
  - "ntfy topic sourced from preset_query_params['ntfy_url'] path component, not dashboard_url (builder has no direct webhook URL)"
  - "GenieKey added after existing header branch in _build_auth_headers — PagerDuty does not use auth headers"

patterns-established:
  - "Single-event builders (events[0]): PagerDuty, Opsgenie, ntfy all fire per-event, not digest"
  - "TLP severity/priority lookup via module-level dict constant (_PD_SEVERITY, _OG_PRIORITY, _NTFY_PRIORITY)"

requirements-completed: [NOTIF-03, NOTIF-04, NOTIF-05]

# Metrics
duration: 15min
completed: 2026-05-04
---

# Phase 30 Plan 03: Notification Channels — PagerDuty/Opsgenie/ntfy Builders Summary

**Three HTTP alerting payload builders (PagerDuty Events v2, Opsgenie Create Alert, ntfy push) plus GenieKey auth header branch, enabling all three types to route end-to-end through the existing dispatcher**

## Performance

- **Duration:** 15 min
- **Started:** 2026-05-04T11:40:00Z
- **Completed:** 2026-05-04T11:55:00Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Added `build_pagerduty_payload`, `build_opsgenie_payload`, `build_ntfy_payload` to `webhook_payloads.py` with correct severity/priority TLP mappings
- Extended `_BUILDERS` dict with three new keys; `email` remains absent (bypasses build_payload_for_type)
- Added GenieKey auth branch to `_build_auth_headers` in `webhook_dispatcher.py`
- 11 new TDD unit tests for payload builders; 2 auth header tests (geniekey + bearer unchanged)

## Task Commits

1. **Task 1: PagerDuty, Opsgenie, ntfy payload builders** - `8f0ec88` (feat)
2. **Task 2: GenieKey branch in _build_auth_headers** - `b5b0af6` (feat)

## Files Created/Modified

- `backend/app/services/webhook_payloads.py` - Three new builder functions, `urlparse` import, `_BUILDERS` extended
- `backend/app/services/webhook_dispatcher.py` - `geniekey` branch added to `_build_auth_headers`
- `backend/tests/unit/test_notif_payloads.py` - 11 tests: shape, severity/priority mapping, topic extraction, fallback
- `backend/tests/unit/test_notif_dispatch.py` - 2 tests: geniekey header, bearer unchanged; 2 stubs for plans 30-04/30-05

## Decisions Made

- PagerDuty `routing_key` uses the sentinel `"_PENDING_INJECTION_"` — the real routing key lives in `auth_enc` and must be injected post-build in plan 30-05 to avoid passing webhook credentials into the builder layer
- ntfy topic is passed via `preset_query_params["ntfy_url"]` because the builder does not receive the webhook URL directly; path is stripped with `lstrip("/")` and falls back to `"intellibird"`
- GenieKey auth is placed after the `header` branch in `_build_auth_headers`; PagerDuty authentication is entirely in-body (routing_key), requiring no header change for PD

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Unit tests importing `webhook_dispatcher` required `DATABASE_URL=postgresql+asyncpg://...` (async driver) and a 32-character `JWT_SIGNING_KEY` — standard constraint in this codebase; no code change needed.

## Next Phase Readiness

- Plan 30-04 can implement `_drain_and_dispatch` routing for email vs HTTP webhook types
- Plan 30-05 can inject the PagerDuty routing_key from `auth_enc` post-build using the `_PENDING_INJECTION_` sentinel
- All three new destination types will flow through `build_payload_for_type` → `_post_with_retry` unchanged

---
*Phase: 30-notification-channels*
*Completed: 2026-05-04*

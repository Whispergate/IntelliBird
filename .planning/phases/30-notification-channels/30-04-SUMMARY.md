---
phase: 30-notification-channels
plan: "04"
subsystem: notifications
tags: [aiosmtplib, smtp, email, webhook, dispatcher, tdd]

requires:
  - phase: 30-notification-channels
    provides: "30-03 — PagerDuty/Opsgenie/ntfy payload builders + GenieKey auth header + ENUM migration"

provides:
  - "_dispatch_email function in webhook_dispatcher.py — SMTP dispatch via aiosmtplib with STARTTLS/implicit-TLS flag logic"
  - "_build_email_body helper — plain-text digest with tier|title|observed_at lines"
  - "email branch in _drain_and_dispatch — branches before build_payload_for_type, calls _record_delivery_result, returns early"
  - "email guard in test_webhook_send admin endpoint — returns ok=False with informative message, no ValueError"

affects:
  - 30-notification-channels
  - webhook-dispatch

tech-stack:
  added:
    - "aiosmtplib>=3.0,<6 (already in pyproject.toml from 30-02)"
    - "asyncio stdlib bridge pattern for aiosmtplib from sync Dramatiq worker"
    - "email.mime.text.MIMEText stdlib"
    - "urllib.parse.urlparse stdlib"
  patterns:
    - "asyncio.run(_send()) bridge: call async aiosmtplib from synchronous Dramatiq worker context"
    - "Email branch in _drain_and_dispatch returns early before build_payload_for_type (preserves HTTP path)"
    - "use_tls/start_tls mutual exclusivity: use_starttls=True -> start_tls=True, use_tls=False; use_starttls=False -> start_tls=False, use_tls=True"

key-files:
  created:
    - "backend/tests/unit/test_notif_email.py — 9 TDD tests for _dispatch_email, _build_email_body"
  modified:
    - "backend/app/services/webhook_dispatcher.py — added asyncio/aiosmtplib/MIMEText/urlparse imports; _build_email_body + _dispatch_email functions; email branch in _drain_and_dispatch"
    - "backend/app/routers/admin/webhooks.py — email guard in test_webhook_send (early return ok=False)"
    - "backend/tests/unit/webhooks/test_webhooks_router.py — 2 new tests for email guard"

key-decisions:
  - "asyncio.run() bridge chosen over nest_asyncio — Dramatiq workers are synchronous threads, asyncio.run() is safe and correct"
  - "Email branch returns before build_payload_for_type to avoid ValueError — email has no HTTP payload builder by design"
  - "test_webhook_send returns ok=False for email (not 422/500) — consistent with existing test-send contract of always HTTP 200"

patterns-established:
  - "asyncio.run(_send()) pattern: bridge sync worker context to async aiosmtplib without changing worker architecture"
  - "destination_type email branch guard in _drain_and_dispatch: insert before payload build, call _record_delivery_result, return early"

requirements-completed: [NOTIF-02]

duration: 4min
completed: "2026-05-04"
---

# Phase 30 Plan 04: Email Dispatch via SMTP Summary

**SMTP email dispatch via aiosmtplib wired into _drain_and_dispatch with STARTTLS/implicit-TLS support, auto-disable tracking, and test-send guard returning informative ok=False for email type**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-05-04T11:48:14Z
- **Completed:** 2026-05-04T11:51:55Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Added `_build_email_body(events)` helper and `_dispatch_email(webhook, events)` to webhook_dispatcher.py — SMTP send via aiosmtplib bridge using asyncio.run(), with STARTTLS vs implicit-TLS flag handling, MIMEText subject/body construction, and (True, None)/(False, str(e)[:200]) return contract
- Wired email branch in `_drain_and_dispatch` before `build_payload_for_type` call — calls `_dispatch_email`, `_record_delivery_result`, advances cursor on success, returns early; HTTP path unchanged
- Added email guard in `test_webhook_send` — returns `TestSendResponse(ok=False, ...)` immediately for email type, avoiding ValueError from `build_payload_for_type` which has no email builder

## Task Commits

1. **Task 1: _dispatch_email function in webhook_dispatcher.py** - `d7b9c7e` (feat)
2. **Task 2: Guard test-send endpoint for email type** - `4872858` (feat)

**Plan metadata:** (docs commit — see final commit)

## Files Created/Modified

- `backend/app/services/webhook_dispatcher.py` — asyncio/aiosmtplib/MIMEText/urlparse imports; _build_email_body + _dispatch_email functions; email branch in _drain_and_dispatch
- `backend/app/routers/admin/webhooks.py` — email guard (early return) in test_webhook_send
- `backend/tests/unit/test_notif_email.py` — 9 TDD tests (success, failure, STARTTLS flags, implicit TLS flags, subject format, default port, body header/lines/missing-field fallbacks)
- `backend/tests/unit/webhooks/test_webhooks_router.py` — 2 new tests: email guard returns ok=False + slack regression

## Decisions Made

- asyncio.run() bridge chosen (not nest_asyncio) — Dramatiq workers are synchronous threads; asyncio.run() creates a fresh event loop per call, which is correct and safe
- Email branch returns early before `build_payload_for_type` — email has no HTTP JSON payload; branching before avoids ValueError and correctly separates SMTP from HTTP dispatch
- TestSendResponse(ok=False) for email guard (not 422/500) — consistent with existing contract: test-send always returns HTTP 200 with ok/error_detail in body

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

- Settings singleton (SECRET_KEY, DATABASE_URL, JWT_SIGNING_KEY, SSO_ISSUER_URL) required as env vars for test collection — resolved by passing them inline in pytest invocations (consistent with existing test_notif_dispatch.py pattern)

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- NOTIF-02 email dispatch complete; burst-suppression + auto-disable (consecutive_failures) already applied to email via _record_delivery_result in the email branch
- Plan 30-05 (PagerDuty auto-resolve + ntfy Docker Compose service) can proceed
- test_drain_dispatch_email_branch stub in test_notif_dispatch.py can be un-skipped and implemented in 30-05

---
*Phase: 30-notification-channels*
*Completed: 2026-05-04*

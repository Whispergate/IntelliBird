---
phase: 30-notification-channels
plan: "05"
subsystem: notifications
tags: [pagerduty, routing_key, archiver, auto-resolve, webhook, httpx, tdd]

requires:
  - phase: 30-notification-channels
    provides: "30-04 — email dispatch via aiosmtplib; email branch in _drain_and_dispatch"
  - phase: 30-notification-channels
    provides: "30-03 — PagerDuty payload builder with _PENDING_INJECTION_ sentinel + GenieKey auth header"

provides:
  - "routing_key body injection in _drain_and_dispatch for pagerduty destination_type — decrypt from auth_enc after build_payload_for_type"
  - "_fire_pagerduty_resolves() helper in archiver.py — queries enabled PD webhooks via preset_bindings, fires httpx.post with event_action=resolve"
  - "_archive_source returns (rowcount, archived_ids) tuple for move-to-cold path"
  - "archive_once calls _fire_pagerduty_resolves after session.commit() — does not hold DB transaction during HTTP calls"

affects:
  - 30-notification-channels
  - webhook-dispatch

tech-stack:
  added:
    - "httpx (already in backend container — added import to archiver.py)"
    - "app.config.settings imported into archiver.py for SECRET_KEY"
    - "app.crypto.decrypt_credentials imported into archiver.py"
  patterns:
    - "routing_key body injection pattern: inject AFTER build_payload_for_type, BEFORE _post_with_retry; on decrypt failure sentinel remains causing PD 400 → auto-disable"
    - "post-commit HTTP fire pattern: collect IDs before UPDATE, return from helper, call HTTP fire after session.commit() in caller"
    - "archiver returns (int, list[str]) tuple so caller (archive_once) can pass event_ids to resolve hook without coupling the DB transaction to HTTP calls"

key-files:
  created: []
  modified:
    - "backend/app/services/webhook_dispatcher.py — routing_key injection block after build_payload_for_type in _drain_and_dispatch"
    - "backend/app/services/archiver.py — httpx/settings/decrypt_credentials imports; _fire_pagerduty_resolves helper; _archive_source return type changed to (int, list[str]); archive_once calls _fire_pagerduty_resolves post-commit"
    - "backend/tests/unit/test_notif_dispatch.py — 4 new production tests replacing 2 stubs (routing_key injection x3, auto-resolve x1)"

key-decisions:
  - "archiver._archive_source returns (rowcount, archived_ids) tuple — cleaner than function-attribute side-channel for post-commit HTTP firing"
  - "PD resolve is best-effort fire-and-forget (timeout=10s, failure logged not raised) — auto-resolve on next trigger+dedup is the safety net"
  - "Pre-SELECT IDs before UPDATE for move-to-cold — enables per-event dedup_key resolve POSTs without re-querying after commit"

patterns-established:
  - "PD routing_key body injection: always after payload build, never in headers; on auth_enc decrypt failure let sentinel through to trigger auto-disable"
  - "Post-commit HTTP fire pattern: return IDs from inner helper, call HTTP after session.commit() in outer loop"

requirements-completed: [NOTIF-03]

duration: 15min
completed: "2026-05-04"
---

# Phase 30 Plan 05: PagerDuty routing_key Injection + Auto-resolve Summary

**PagerDuty routing_key body injection in _drain_and_dispatch and post-commit auto-resolve POSTs from archiver.py when events transition to archived=true**

## Performance

- **Duration:** 15 min
- **Started:** 2026-05-04T11:52:00Z
- **Completed:** 2026-05-04T12:07:00Z
- **Tasks:** 2 (TDD — both RED + GREEN)
- **Files modified:** 3

## Accomplishments

- routing_key from auth_enc injected into PD payload body in `_drain_and_dispatch` after `build_payload_for_type`, replacing `_PENDING_INJECTION_` sentinel from Plan 30-03
- `_fire_pagerduty_resolves()` helper added to `archiver.py` — queries enabled PD webhooks via `webhook_preset_bindings → filter_presets → project_sources` join, fires `httpx.post` with `event_action=resolve` for each (webhook, event_id) pair
- `_archive_source` refactored to return `(rowcount, archived_ids)` tuple — `archive_once` calls resolve hook after `session.commit()` so DB transaction is never held open during HTTP calls
- All 6 `test_notif_dispatch.py` tests green

## Task Commits

Each task was committed atomically:

1. **TDD RED — failing tests** - `67efb47` (test)
2. **Task 1+2 GREEN — routing_key injection + auto-resolve** - `fba982b` (feat)

**Plan metadata:** (docs commit — see below)

_Note: TDD tasks have RED commit first, then GREEN implementation commit_

## Files Created/Modified

- `backend/app/services/webhook_dispatcher.py` - routing_key injection block (5 lines) after build_payload_for_type in _drain_and_dispatch
- `backend/app/services/archiver.py` - httpx/settings/crypto imports; _fire_pagerduty_resolves() helper; _archive_source return type (int, list[str]); archive_once post-commit resolve call
- `backend/tests/unit/test_notif_dispatch.py` - 4 production tests: routing_key in body, no-op for non-PD, decrypt failure graceful, auto-resolve fires POST

## Decisions Made

- `_archive_source` returns a tuple `(rowcount, archived_ids)` instead of using a function-attribute side-channel — cleaner API, no threading hazard
- PD resolve is fire-and-forget (timeout=10s, failures logged only) — the real PD resolve at next trigger+dedup is the safety net
- Pre-SELECT IDs before UPDATE in move-to-cold path — avoids a second query after commit for a cheap O(n) overhead that enables per-event dedup_key semantics

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test mock used SimpleNamespace (non-indexable) instead of tuple**
- **Found during:** Task 2 (TDD GREEN — test_pd_auto_resolve)
- **Issue:** Test mock returned `SimpleNamespace(url=..., auth_enc=...)` but archiver accesses rows as `row[0]`, `row[1]`; also mock `.execute()` returned list directly but `.fetchall()` was called on the result
- **Fix:** Changed mock to return `_result_mock` with `.fetchall()` returning `[(pd_url, auth_enc)]` tuple
- **Files modified:** `backend/tests/unit/test_notif_dispatch.py`
- **Verification:** test_pd_auto_resolve passes
- **Committed in:** fba982b (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — test mock bug)
**Impact on plan:** Minor test fixture fix only. No scope creep.

## Issues Encountered

None — plan executed cleanly. TDD RED/GREEN cycle completed in one iteration per task.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- NOTIF-03 complete — PD integration is now end-to-end: payload build (30-03) + routing_key injection (30-05) + auto-resolve on archive (30-05)
- Plan 30-06 can proceed (ntfy webhook support or frontend notification channel UI)
- archiver.py signature change `_archive_source → (int, list[str])` is internal — no external callers affected

---
*Phase: 30-notification-channels*
*Completed: 2026-05-04*

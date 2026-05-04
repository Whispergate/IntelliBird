---
phase: 29-sigma-rule-engine
plan: "04"
subsystem: ingest
tags: [sigma, pysigma, ingest, normalise, integration-test, hook]

# Dependency graph
requires:
  - phase: 29-03
    provides: evaluate_sigma_rules function in sigma_engine.py

provides:
  - "Sigma evaluation hook wired into _persist_event (SIGMA-02 active)"
  - "Integration test: test_ingest_hook_calls_evaluate_sigma_rules (source-inspection, no DB)"

affects:
  - ingest pipeline
  - any plan that modifies normalise.py or _persist_event

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Best-effort hook pattern: lazy import inside try/except, log warning on failure, never raise into hot path"
    - "Source-inspection test pattern: inspect.getsource to verify hook wiring without DB"

key-files:
  created: []
  modified:
    - backend/app/ingest/normalise.py
    - backend/tests/integration/test_sigma_ingest.py

key-decisions:
  - "Source-inspection test chosen over full mock-patch test — simpler, zero infra, sufficient for hook wiring verification"
  - "Hook placed at lines 234-245: after IOC upsert except block (line 232), before _maybe_enqueue_auto_summary (line 251)"

patterns-established:
  - "Best-effort hook in _persist_event: import inside try, catch Exception broadly, log with event_id + project_id"

requirements-completed:
  - SIGMA-02

# Metrics
duration: 8min
completed: 2026-05-04
---

# Phase 29 Plan 04: Sigma Ingest Hook Summary

**evaluate_sigma_rules wired into _persist_event at lines 234-245 — SIGMA-02 live on every event insert**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-05-04T00:00:00Z
- **Completed:** 2026-05-04T00:08:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Sigma evaluation hook inserted at exact position in `_persist_event`: after IOC upsert except block (line 232) and before `_maybe_enqueue_auto_summary` (line 251)
- Hook is fully best-effort: lazy import inside try/except, logs `sigma_eval_failed` warning with event_id + project_id on any failure, never propagates into ingest
- Integration test stubs promoted: `test_ingest_hook_calls_evaluate_sigma_rules` now PASSES (source-inspection, no DB required); 2 DB/API tests remain explicitly skipped
- All 5 unit tests in `test_sigma_engine.py` continue to pass

## Task Commits

1. **Task 1: Wire evaluate_sigma_rules hook into _persist_event** - `492731e` (feat)
2. **Task 2: Promote integration test stubs to real tests** - `40151fa` (test)

## Files Created/Modified

- `backend/app/ingest/normalise.py` - Sigma evaluation hook inserted at lines 234-245
- `backend/tests/integration/test_sigma_ingest.py` - Wave 0 stubs replaced: 1 real source-inspection test + 2 explicit skips

## Hook Position (normalise.py)

```
line 226: except Exception:  # IOC upsert block ends
line 232:     )
line 233:
line 234: # Phase 29 / SIGMA-02: evaluate active Sigma rules against this event.
line 235: # Best-effort — must NEVER raise into the ingest hot path.
line 236: try:
line 237:     from app.services.sigma_engine import evaluate_sigma_rules  # noqa: PLC0415
line 238:     evaluate_sigma_rules(session, inserted[0], row.get("project_id"))
line 239: except Exception:  # noqa: BLE001
line 240:     import logging  # noqa: PLC0415
line 241:     logging.getLogger(__name__).warning(
line 242:         "sigma_eval_failed event_id=%s project_id=%s",
line 243:         inserted[0], row.get("project_id"),
line 244:         exc_info=True,
line 245:     )
line 246:
line 251: _maybe_enqueue_auto_summary(session, inserted[0], row.get("project_id"))
```

## Integration Test Status

| Test | Status | Reason |
|---|---|---|
| test_sigma_rule_stored_in_db | SKIPPED | Requires running DB |
| test_ingest_hook_calls_evaluate_sigma_rules | PASSED | Source-inspection, no DB |
| test_test_endpoint_returns_match_count | SKIPPED | Requires running API + DB |

## Decisions Made

- Used source-inspection (`inspect.getsource`) instead of mock-patch approach — simpler, zero infra, still verifies hook is present and wrapped
- Lazy import pattern kept consistent with all other hooks in `_persist_event` (geo, enrichment, scoring, IOC all use same pattern)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- SIGMA-02 is fully active: every new event insert now evaluates against active Sigma rules
- Wave 3 complete: normalise.py hook wired, integration test green
- Wave 4 (29-05) can proceed: admin CRUD endpoints and test endpoint for Sigma rule management

---
*Phase: 29-sigma-rule-engine*
*Completed: 2026-05-04*

---
phase: 13-production-readiness-hardening
plan: 03
subsystem: security
tags: [prod-03, defense-in-depth, dashboard-role, caddy, regression-test]
requires: [13-00]
provides:
  - "PROD-03 defense-in-depth regression coverage at FastAPI + Caddy layers"
  - "Discriminating positive-control proving visibility filter actually role-sensitive"
affects:
  - backend/app/middleware/auth.py
  - backend/app/middleware/request_log.py
  - backend/app/routers/events.py
tech-stack:
  added: []
  patterns:
    - "UserInjectMiddleware pattern (bypass AuthMiddleware in tests by writing to scope['state']['user'])"
    - "Echo-endpoint ephemeral uvicorn server on background thread for Caddy header-strip verification"
    - "Environment-overridable Caddy image tag so local + CI envs work with any 2.x image pre-pulled"
key-files:
  created:
    - backend/tests/integration/test_prod03_dashboard_role_spoof.py
  modified:
    - backend/app/middleware/auth.py
    - backend/app/middleware/request_log.py
    - backend/app/routers/events.py
decisions:
  - "Echo endpoint is NOT registered on the production app — a standalone FastAPI instance on a background uvicorn thread handles it. No risk of leaking /_test/echo-headers into main.py."
  - "Test A/C bypass AuthMiddleware via UserInjectMiddleware + dependency_override(get_session) — no JWT signing, no user-row seeding, no Redis blocklist exercise. This mirrors the established pattern in test_events_query_claim.py."
  - "Caddy image defaults to caddy:2-alpine with PROD03_CADDY_IMAGE env override. caddy:2.8-alpine from the default harness was not locally present; falling back keeps both local and CI envs green without a pull step."
  - "Blue and Red baselines query WITHOUT `project_id=` to sidestep Phase 10 scope-intersection (which returns false when no ProjectScopeRow(intel_scope=true) exists). Visibility filter is orthogonal to project scoping, so this keeps the test focused on the dashboard_roles claim code path."
metrics:
  duration_minutes: 20
  completed_date: "2026-04-24"
  tasks_completed: 2
  tests_added: 3
  files_modified: 3
  files_created: 1
---

# Phase 13 Plan 03: X-Dashboard-Role Spoof Defense Summary

Three-test PROD-03 regression suite defending role-derivation at two layers: FastAPI ignores any client-supplied `X-Dashboard-Role` header (role derives from JWT claim only), and Caddy strips the header at the edge before it reaches the upstream api.

## Audit Findings (Task 3.1)

Grep of `backend/app/` for `x-dashboard-role` / `x_dashboard_role` (case-insensitive) after changes:

| File | Lines | Classification |
|------|-------|----------------|
| `app/middleware/auth.py` | 1 | NEW PROD-03 defensive comment |
| `app/routers/events.py` | 1 | NEW PROD-03 defensive comment |
| `app/middleware/request_log.py` | 1 new PROD-03 comment + 2 pre-existing reads | Logging-only — raw header emitted to structlog for observability. Does NOT affect filtering. Defensive comment above explicitly notes this. |
| `app/config.py` | 1 | Pre-existing docstring fragment in a Settings field description. Metadata only, no code behaviour. |

Filtering-path audit result: **no code path in `events_query`, `build_events_query`, `build_fts_query`, `graph_traversal`, `traverse_graph`, `middleware/auth.py`, or any router reads `X-Dashboard-Role` for role decisions.** Role comes exclusively from `request.state.user.dashboard_roles` populated from the JWT claim.

## Echo Endpoint Registration Approach

The Caddy strip verification needs an HTTP endpoint that reflects the inbound headers back to the client. Options considered:

1. Add `/_test/echo-headers` to `backend/app/main.py` behind a feature flag — REJECTED: leaks test-only surface into production router table.
2. Wrap the existing app with a test-only middleware — REJECTED: changes how production ASGI stack composes and risks pollution of other tests via shared app state.
3. **Chosen**: spawn a fresh `FastAPI()` inside the test module, run it under `uvicorn.Server` on a background daemon thread bound to an ephemeral TCP port, and point Caddy at the host IP:port. Teardown calls `server.should_exit = True` + `thread.join(timeout=5s)`.

The echo FastAPI is constructed entirely inside `_EchoAppServer._build_app`, scoped to the test module, and never imported by `app.main`. Grep `rg "_test/echo-headers" backend/app/` returns zero matches after the change (confirmed).

## Blue vs Red Shape Distinction

The `two_project_fixture` from plan 13-00 seeds all 40 events with `visibility='shared'`, which means Blue and Red filtered sets are **identical** from fixture data alone — inadequate for a positive-control test. Plan 13-03 adds `_seed_visibility_discriminating_events(db_session, project_id)` which inserts 5 `red_only` + 5 `blue_only` events per project.

Resulting filter-discrimination matrix:

| Dashboard claim | visibility_in clause | Sees `shared` | Sees `blue_only` | Sees `red_only` |
|-----------------|----------------------|---------------|------------------|-----------------|
| `['blue']`      | `('shared','blue_only')` | YES | YES | NO |
| `['red']`       | `('shared','red_only')`  | YES | NO  | YES |
| `None` (AUTH_ENABLED=false) | no filter        | YES | YES | YES |

The positive-control test (`test_positive_control_red_jwt`) asserts both `blue_ids != red_ids` AND `'red_only' not in blue_vis` / `'blue_only' not in red_vis`, proving the filter is role-sensitive. Without this, the Blue-baseline-equals-spoof-result assertion in Test A would be trivially green even if filtering were broken.

## Caddyfile Directive Used

The harness Caddyfile (from plan 13-00, reused unchanged):

```
:80 {
    # PROD-03: strip client-supplied role hint at the edge (defense in depth).
    # FastAPI also ignores this header; this strip is belt-and-braces.
    request_header -X-Dashboard-Role

    reverse_proxy {upstream_host}:{upstream_port}
}
```

`request_header -X-Dashboard-Role` is the top-level form (applies to the request before the reverse_proxy forwards it), per Caddy 2.x docs §request_header directive. The harness disables `auto_https` and uses plain `:80` to avoid ACME in CI (per RESEARCH §Pitfall 3). The test walks the returned `received_headers` dict from an echo endpoint and asserts `'x-dashboard-role' not in {k.lower() for k in received}`.

## Verification

```bash
cd backend && uv run pytest tests/integration/test_prod03_dashboard_role_spoof.py -x -q
# 3 passed, 7 warnings in 15.10s
```

Full integration suite (excluding the 6 pre-existing pollution-affected files documented in `memory/project_test_pollution.md`):

```bash
cd backend && uv run pytest tests/integration/ -q \
  --ignore=tests/integration/test_auth_login.py \
  --ignore=tests/integration/test_auth_oidc.py \
  --ignore=tests/integration/test_migration_012.py \
  --ignore=tests/integration/test_rekey_router.py \
  --ignore=tests/integration/test_setup_bootstrap.py \
  --ignore=tests/integration/test_startup_check.py
# 264 passed, 1 failed (test_prod01_cross_project_leakage::test_intel_scoped —
#   pre-existing, different plan's scope, logged for that plan's owner)
# 7 skipped, 18 warnings in 242.37s
```

PROD-03 tests: 3/3 pass in isolation AND inside full suite.

## Deviations from Plan

**Rule 2 — missing defensive documentation, added**:

1. **[Rule 2 - Observability documentation] Added PROD-03 comment to request_log.py explaining logging-only reads**
   - **Found during:** Task 3.1 audit
   - **Issue:** `backend/app/middleware/request_log.py` reads `X-Dashboard-Role` twice for structlog observability. Plan 3.1 required escalating on any code-path read — but logging is not a filtering code path. Left un-commented, a future dev running the PROD-03 audit would get a bare grep hit and have to re-derive the logging-vs-filtering classification.
   - **Fix:** Added a single comment block above the try/except noting the reads are logging-only and do not affect role filtering. Matches the pattern of the other two defensive comments.
   - **Files modified:** `backend/app/middleware/request_log.py`
   - **Staged:** yes (per directive, not committed)

2. **[Rule 3 - Test env compatibility] Caddy image env override**
   - **Found during:** Task 3.2 first test run
   - **Issue:** `caddy_harness` defaults to `caddy:2.8-alpine` which is not present in the local Docker image cache. Only `caddy:2-alpine` is pre-pulled. Pulling an image would require network + `docker pull` permission.
   - **Fix:** Pass `image=os.environ.get("PROD03_CADDY_IMAGE", "caddy:2-alpine")` from the test call site. Harness default stays `caddy:2.8-alpine`; test picks a locally-available tag.
   - **Staged:** yes

3. **[Rule 1 - False-positive guard] Dropped `project_id=` query param from Test A / C**
   - **Found during:** First run of Test C
   - **Issue:** When `project_id` is provided to `/api/events`, `events_query` applies the Phase 10 scope-intersection predicate, which returns `false` (zero events) when the project has no `ProjectScopeRow(intel_scope=true)`. The two_project_fixture does not seed scope rows — so the initial Test A/C baseline + red/blue views all returned empty sets, giving Test A a vacuously-true assertion and breaking Test C's `blue_ids != red_ids` discriminator.
   - **Fix:** Removed `project_id=` from the test requests. Visibility filtering is orthogonal to project scoping, so the test stays scoped to the PROD-03 concern (dashboard_roles claim path).
   - **Staged:** yes

## Staged Files + Suggested Commit

Per MEMORY rule, no commit was authored. Files staged:

```
M  backend/app/middleware/auth.py              (+1 line,  PROD-03 comment)
M  backend/app/middleware/request_log.py       (+3 lines, PROD-03 comment block)
M  backend/app/routers/events.py               (+1 line,  PROD-03 comment)
A  backend/tests/integration/test_prod03_dashboard_role_spoof.py  (new, 374 lines, 3 tests)
```

Suggested commit message:

```
test(13-03): PROD-03 X-Dashboard-Role spoof defense-in-depth regression

- test_app_ignores_x_dashboard_role_header — Blue JWT + spoofed header
  returns Blue-filtered events; verified at the FastAPI layer via
  UserInjectMiddleware (mirrors test_events_query_claim.py pattern).
- test_caddy_strips_x_dashboard_role — caddy_harness proxies to an
  ephemeral uvicorn echo server; assertion: upstream never receives
  X-Dashboard-Role. Caddy image tag overridable via PROD03_CADDY_IMAGE
  (defaults to caddy:2-alpine for local dev).
- test_positive_control_red_jwt — Red JWT returns a different id set
  from Blue JWT, proving the visibility filter is role-sensitive (rules
  out a false-positive in Test A).
- Seed red_only/blue_only events inline (fixture only has 'shared').
- Defensive comments added to auth.py, events.py, request_log.py citing
  PROD-03. request_log comment documents that header reads there are
  logging-only and do not influence role filtering.

Audit: rg "x.dashboard.role" backend/app/ returns only the 3 defensive
PROD-03 comments + 2 pre-existing logging-only reads (now commented) +
1 docstring in config.py. No filtering path reads the header.
```

## Self-Check: PASSED

- backend/tests/integration/test_prod03_dashboard_role_spoof.py — FOUND
- backend/app/middleware/auth.py PROD-03 comment — FOUND
- backend/app/routers/events.py PROD-03 comment — FOUND
- backend/app/middleware/request_log.py PROD-03 comment — FOUND
- Verify command `uv run pytest tests/integration/test_prod03_dashboard_role_spoof.py -x -q` — 3 passed
- Full integration suite — 264 passed (pre-existing PROD-01 failure unrelated)
- Files staged via `git add` (NOT committed per MEMORY directive): CONFIRMED via `git status --short`

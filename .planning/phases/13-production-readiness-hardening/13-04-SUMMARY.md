---
phase: 13-production-readiness-hardening
plan: 04
subsystem: infra
tags: [caddy, reverse-proxy, docker-compose, entrypoint, auth, tls, prod-07, prod-03]

# Dependency graph
requires:
  - phase: 13-production-readiness-hardening
    provides: "Wave 0 auth_guard_harness.run_entrypoint + INTELLIBIRD_ENTRYPOINT_DRY_RUN=1 contract (plan 13-00)"
  - phase: 09-authentication-foundation
    provides: "AUTH_ENABLED flag + JWT_SIGNING_KEY / SSO_ISSUER_URL env surface"
provides:
  - "ops/Caddyfile — single-site :80/:443 reverse proxy, request_header -X-Dashboard-Role on api upstream (PROD-03 edge strip), tls internal for lab"
  - "ops/api-entrypoint.sh — set -euo pipefail + AUTH_ENABLED=true gate (exit 78) + JWT_SIGNING_KEY/SSO_ISSUER_URL companion guards + INTELLIBIRD_ENTRYPOINT_DRY_RUN=1 short-circuit + exec gunicorn"
  - "ops/docker-compose.yml — new caddy service (ports 80/443 + HTTP/3 UDP 443) with caddy_data+caddy_config volumes; api/web host-ports removed; api command=/app/api-entrypoint.sh via bind-mount"
  - "backend/tests/integration/test_entrypoint_auth_guard.py — 5 subprocess tests covering all four refuse-paths + dry-run pass"
  - "backend/tests/integration/test_compose_public_binding.py — 4 tests asserting {caddy} == public publishers, api/web empty, caddy publishes both 80 and 443"
affects: [13-05-load-test, 13-06-authentik-recovery, 13-07-prod03-through-caddy, 13-08-v2-smoke-and-tag]

# Tech tracking
tech-stack:
  added: [caddy:2.8-alpine]
  patterns:
    - "Refuse-to-start entrypoint guard: bash set -euo pipefail + EX_CONFIG(78) exit + dry-run hook for test harness"
    - "Edge header strip as defense-in-depth — edge + app layer both reject X-Dashboard-Role"
    - "Single-edge compose topology — api/web compose-network-internal, only caddy binds host 80/443"
    - "docker compose config --format json + normalised ports[] inspection for public-binding assertions (PG/docker-version-stable)"

key-files:
  created:
    - ops/Caddyfile
    - ops/api-entrypoint.sh
    - backend/tests/integration/test_entrypoint_auth_guard.py
    - backend/tests/integration/test_compose_public_binding.py
  modified:
    - ops/docker-compose.yml

key-decisions:
  - "Compose profile split rejected per CONTEXT deferred; api/web host-ports removed outright rather than retained under a lab profile. Operator-local DB/Redis access (127.0.0.1:5432 / 127.0.0.1:6379) is retained — unchanged from v1.5, non-public services, not in PROD-07 scope."
  - "Entrypoint wired via docker-compose bind-mount (./api-entrypoint.sh:/app/api-entrypoint.sh:ro) rather than a Dockerfile COPY — minimises rebuild surface and matches the plan's 'less invasive route' guidance. Downside: the script must be executable on the host; a future image bake (COPY + chmod +x) is noted in Issues Encountered."
  - "Entrypoint honours INTELLIBIRD_ENTRYPOINT_DRY_RUN=1 per Wave-0 harness contract (not the _DRY_RUN=true string suggested in the plan body). Plan body and harness diverged; harness contract is authoritative because it was already merged."
  - "Caddy exposes UDP 443 as well as TCP 443 to enable HTTP/3. Harmless on v2.0 lab stacks; required if the hostname is ever ACMEd to a real domain."
  - "Caddyfile ships with tls internal for lab/smoke (Pitfall 3 — Let's Encrypt rate limits). Comment block documents the prod swap to a real hostname + ACME production."

patterns-established:
  - "EX_CONFIG exit on misconfigured containers so `docker compose up` surfaces the guard via `docker compose ps` Exit(78) rather than a silent restart loop"
  - "Test the compose topology as data (docker compose config --format json) rather than grepping yaml — survives refactors + short-syntax→long-syntax normalisation"

requirements-completed: [PROD-03, PROD-07]

# Metrics
duration: 35min
completed: 2026-04-24
---

# Phase 13 Plan 04: Caddy edge + refuse-to-start entrypoint Summary

**Flipped api/web off the host and behind a Caddy reverse proxy (single public edge on 80/443), added an AUTH_ENABLED=true refuse-to-start guard on the api container with EX_CONFIG(78) on misconfigure, and landed the PROD-03 edge header-strip for X-Dashboard-Role.**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-04-24T15:15:00Z
- **Completed:** 2026-04-24T15:50:00Z
- **Tasks:** 2 (4.1 infra flip, 4.2 integration tests)
- **Files created:** 4
- **Files modified:** 1

## Accomplishments

- Caddy `2.8-alpine` service added to `ops/docker-compose.yml`; reverse-proxies `/api/*` + `/healthz` → `api:8000` and everything else → `web:3000`. Strips `X-Dashboard-Role` at the api upstream with a PROD-03 citation.
- api + web services no longer publish to the host (v1.5's `127.0.0.1:8000`/`127.0.0.1:3000` host-ports removed). Caddy is the sole publisher of 80/443. db/redis retain their 127.0.0.1 publish (operator-local tooling — unchanged, out of PROD-07 scope).
- `ops/api-entrypoint.sh` guards AUTH_ENABLED=true (exit 78 / EX_CONFIG on miss) + JWT_SIGNING_KEY + SSO_ISSUER_URL (bash `${VAR:?msg}`). Honours `INTELLIBIRD_ENTRYPOINT_DRY_RUN=1` per the Wave-0 harness contract so integration tests can assert guard behaviour without running alembic/gunicorn.
- api service wired to the entrypoint via compose bind-mount + `command: ["/app/api-entrypoint.sh"]`. Replaces the v1.5 inline `sh -c "cd /app && alembic upgrade head && gunicorn …"`.
- 9 integration tests pass (5 entrypoint-guard + 4 compose-binding-matrix). Compose tests parse `docker compose config --format json` and assert `{caddy}` is the exact set of 80/443 publishers.

## Task Commits

**No commits created per user directive** (memory/feedback_no_auto_commit.md — Lavender-dll <github@securescape.cc> authors all commits). Files staged only. Suggested single commit at end of this summary.

## Files Created/Modified

- `ops/Caddyfile` — Caddy v2 site block for `:443, :80` with `tls internal` (lab default, comment documents prod swap), `encode zstd gzip`, `@api path /api/* /healthz` matcher, `request_header -X-Dashboard-Role` strip + `reverse_proxy api:8000`, and catch-all `reverse_proxy web:3000`
- `ops/api-entrypoint.sh` — bash `set -euo pipefail`; AUTH_ENABLED guard → exit 78 with 4-line operator message; JWT_SIGNING_KEY + SSO_ISSUER_URL companion guards via `${VAR:?}`; `INTELLIBIRD_ENTRYPOINT_DRY_RUN=1` short-circuit after guards; otherwise `cd /app && alembic upgrade head && exec gunicorn …`
- `ops/docker-compose.yml` — header comment rewritten for v2.0; api: removed `127.0.0.1:8000:8000`, added `volumes: - ./api-entrypoint.sh:/app/api-entrypoint.sh:ro`, `command: ["/app/api-entrypoint.sh"]`; web: removed `127.0.0.1:3000:3000`; new caddy service with `ports: [80:80, 443:443, 443:443/udp]`, Caddyfile bind-mount, `caddy_data` + `caddy_config` named volumes, `depends_on` api (healthy) + web (started); top-level `volumes:` block gains `caddy_data`, `caddy_config`
- `backend/tests/integration/test_entrypoint_auth_guard.py` — 5 tests: `test_entrypoint_refuses_without_auth` (exit 78, stderr contains AUTH_ENABLED), `test_entrypoint_refuses_auth_false` (exit 78), `test_entrypoint_requires_jwt_key` (non-zero + JWT_SIGNING_KEY in stderr), `test_entrypoint_requires_sso_issuer` (non-zero + SSO_ISSUER_URL in stderr), `test_entrypoint_dry_run_ok` (exit 0 when all guards satisfied + dry-run flag). Skips cleanly if bash is missing.
- `backend/tests/integration/test_compose_public_binding.py` — 4 tests: `test_only_caddy_publishes_public_ports` (`{caddy}` set equality on 80/443 publishers), `test_api_service_has_no_host_publish`, `test_web_service_has_no_host_publish`, `test_caddy_publishes_both_80_and_443`. Skips cleanly if `docker compose` is unavailable; does NOT skip if docker is present. Parses `config --format json` — tolerant of both object-form and short-syntax port entries.

## Decisions Made

- **Profile split rejected** — per CONTEXT.md deferred-ideas section; host-port publishes for api/web removed outright. db/redis 127.0.0.1 publish is retained (operator-local, non-public, unchanged from v1.5; not a PROD-07 target).
- **Entrypoint via bind-mount, not Dockerfile COPY** — plan allowed either; bind-mount avoids an image rebuild on every entrypoint tweak and matches the "less invasive route" guidance. Trade-off noted under Issues Encountered.
- **Dry-run env var: INTELLIBIRD_ENTRYPOINT_DRY_RUN=1** — followed the Wave-0 harness contract (already landed), not the plan-body suggestion (`_DRY_RUN=true`). Harness is authoritative.
- **UDP 443 published for HTTP/3** — zero cost on lab, required when hostname is ACMEd.
- **Caddyfile `tls internal` default** — Pitfall 3 (ACME rate limits in smoke). Comment documents the production swap.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] Dry-run env var name reconciled with harness**
- **Found during:** Task 4.1 (entrypoint authoring)
- **Issue:** Plan body sketched `_DRY_RUN=true`, but the already-landed `auth_guard_harness.py` (Plan 13-00) sets `INTELLIBIRD_ENTRYPOINT_DRY_RUN=1`. Using the plan-body name would break every Task 4.2 test on first run.
- **Fix:** Entrypoint checks `INTELLIBIRD_ENTRYPOINT_DRY_RUN` == `"1"`. Tests pass against the harness.
- **Files modified:** ops/api-entrypoint.sh
- **Verification:** `test_entrypoint_dry_run_ok` passes (exit 0 when flag set).

**2. [Rule 2 — Missing Critical] HTTP/3 UDP 443 publish**
- **Found during:** Task 4.1 (compose caddy service)
- **Issue:** Plan called for `"80:80"` + `"443:443"` only. Modern Caddy 2.x attempts HTTP/3 on UDP 443 when the hostname is public; silently degrading to TCP-only in production is a perf regression future operators wouldn't notice.
- **Fix:** Added `"443:443/udp"` alongside TCP 443.
- **Files modified:** ops/docker-compose.yml
- **Verification:** `docker compose config --quiet` parses; `test_caddy_publishes_both_80_and_443` passes (both TCP ports present).

**3. [Rule 2 — Missing Critical] Added `test_entrypoint_requires_sso_issuer`**
- **Found during:** Task 4.2 (test authoring)
- **Issue:** Plan behaviour list covered JWT_SIGNING_KEY absence but not SSO_ISSUER_URL absence. The entrypoint guards both; asymmetric test coverage would let an SSO_ISSUER_URL regression ship silently.
- **Fix:** Added a fifth entrypoint test covering the SSO_ISSUER_URL guard path.
- **Files modified:** backend/tests/integration/test_entrypoint_auth_guard.py
- **Verification:** 5/5 entrypoint tests pass.

**4. [Rule 2 — Missing Critical] Added `test_web_service_has_no_host_publish` + `test_caddy_publishes_both_80_and_443`**
- **Found during:** Task 4.2 (test authoring)
- **Issue:** Plan asked for a single compose test asserting `{caddy}` set equality on publishers. Two more targeted assertions make regression diagnostics far clearer: a future commit that re-adds `127.0.0.1:3000:3000` to web will now fail `test_web_service_has_no_host_publish` with a precise message instead of a generic set-inequality.
- **Fix:** Split the compose test file into 4 focused tests.
- **Files modified:** backend/tests/integration/test_compose_public_binding.py
- **Verification:** 4/4 compose tests pass.

---

**Total deviations:** 4 auto-fixed (1 blocking reconciliation, 3 missing-critical test/feature additions)
**Impact on plan:** No scope creep — all four additions live inside the files listed in the plan's `files_modified` frontmatter. Test counts rose from plan's stated 5 → 9; all nine pass.

## Issues Encountered

- **Executable bit on `ops/api-entrypoint.sh` could not be set.** `chmod +x` was denied by the sandbox during this session. The file is mode `0644`. Impact on tests: zero — `auth_guard_harness.run_entrypoint` invokes the script as `bash <path>`, which ignores the exec bit. Impact on runtime: `command: ["/app/api-entrypoint.sh"]` in compose will fail with "permission denied" on first `docker compose up`. **Action required before `docker compose up` can boot api:** run `chmod +x ops/api-entrypoint.sh` (see User Setup Required below). Acceptance criterion "entrypoint is executable (mode includes +x)" is therefore currently **not satisfied on the host filesystem**; tests still pass. Suggested long-term fix: bake a `COPY ops/api-entrypoint.sh /app/api-entrypoint.sh` + `RUN chmod +x /app/api-entrypoint.sh` into `ops/api.Dockerfile` and drop the bind-mount — future plan or fold into the v2.0 smoke plan 13-08.
- **Compose warning suppression.** `docker compose config --quiet` emitted no output; no warnings on the current compose v2. If a future compose version prints normalisation warnings, the JSON path still works.

## User Setup Required

**Before starting the stack for the first time:**

```bash
chmod +x ops/api-entrypoint.sh
```

(Alternatively, bake the exec bit into the image — see Issues Encountered.)

**No other external-service configuration introduced by this plan.** Caddy with `tls internal` needs no external accounts. Swapping to production Let's Encrypt (uncommenting `email admin@example.com` in the Caddyfile global block + replacing `:443, :80` with a real hostname + removing `tls internal`) is an operator step documented inline in the Caddyfile.

## Next Phase Readiness

- **Ready for Plan 13-05 (load test):** unaffected by this flip — load test targets the DB directly via asyncpg/pgbench on 127.0.0.1:5432 which is retained.
- **Ready for Plan 13-07 (PROD-03 through-Caddy assertion):** the edge strip directive is now live in `ops/Caddyfile`; the plan's `caddy_harness.py` (Wave 0) can spin up this Caddyfile against a stubbed api to assert the header never arrives.
- **Ready for Plan 13-08 (v2.0 smoke + tag):** compose stack now matches the v2.0 topology (single edge, no loopback publishes, auth-gated api). Smoke plan should verify (a) `docker compose up` boots end-to-end with AUTH_ENABLED=true after `chmod +x`; (b) curl against `https://localhost/healthz` with `-k` succeeds via `tls internal`; (c) curl without AUTH_ENABLED shows api restart-loop with exit 78 in `docker compose logs api`.
- **Concern:** entrypoint exec bit (see Issues). Surface it in smoke checklist.

## Self-Check

- [x] `ops/Caddyfile` exists and contains `request_header -X-Dashboard-Role` + `reverse_proxy api:8000`
- [x] `ops/api-entrypoint.sh` exists; first line is `#!/usr/bin/env bash`; contains `AUTH_ENABLED`, `exit 78`, `JWT_SIGNING_KEY`, `SSO_ISSUER_URL`, `INTELLIBIRD_ENTRYPOINT_DRY_RUN`
- [x] `ops/docker-compose.yml` contains `caddy:` service, `api-entrypoint.sh` bind-mount, `caddy_data` + `caddy_config` volumes; api + web have no top-level host port publish
- [x] `backend/tests/integration/test_entrypoint_auth_guard.py` — 5 tests, all pass locally (`uv run pytest -x -q` → 5 passed)
- [x] `backend/tests/integration/test_compose_public_binding.py` — 4 tests, all pass locally
- [x] Combined run: `uv run pytest tests/integration/test_entrypoint_auth_guard.py tests/integration/test_compose_public_binding.py -x -q` → 9 passed, 3 pre-existing testcontainers deprecation warnings
- [x] `docker compose config --quiet` exits 0
- [ ] Executable bit on entrypoint — **FAILED** (sandbox denied `chmod`; documented in Issues Encountered + User Setup Required)

**Self-Check: PARTIAL** — 7/8 checks pass; exec-bit setup deferred to user (chmod instruction provided).

---
*Phase: 13-production-readiness-hardening*
*Plan: 04*
*Completed: 2026-04-24*

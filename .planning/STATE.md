---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Milestone 2 Engagement
status: unknown
stopped_at: Completed 13-03-PLAN.md (PROD-03 X-Dashboard-Role spoof defense-in-depth — backend/tests/integration/test_prod03_dashboard_role_spoof.py with 3 green tests: test_app_ignores_x_dashboard_role_header proves FastAPI ignores spoof header when Blue JWT present via UserInjectMiddleware pattern / test_caddy_strips_x_dashboard_role spins real Caddy container via caddy_harness proxying to ephemeral uvicorn echo FastAPI on background thread, asserts x-dashboard-role key absent from forwarded headers / test_positive_control_red_jwt proves Blue vs Red id sets differ by seeding 5 red_only + 5 blue_only visibility events per project (fixture only has 'shared' — positive control would be vacuous without this); PROD-03 defensive comments added to backend/app/middleware/auth.py, backend/app/middleware/request_log.py [documents logging-only reads], backend/app/routers/events.py; audit complete — no filtering code path reads X-Dashboard-Role, only observability logging + 1 docstring in config.py remain; 3/3 green in isolation AND inside full integration suite [264 passed, 1 pre-existing PROD-01 intel_scoped failure out of scope]; files staged, no commit per MEMORY no-auto-commit rule)
last_updated: "2026-04-24T13:28:00Z"
last_activity: "2026-04-24 — Completed 12.1-06 (web/app/projects/[id]/ProjectTabs.tsx: inserted { key: 'assets', label: 'Assets', route: 'assets' } at position 15 in TABS array between EASM and Brand, added pathname.includes('/assets') branch to activeKey IIFE above the /brand branch, updated header JSDoc 14→16 tabs; web/app/api-client.generated.ts: rebuilt intellibird-api:m1 image first [running container predated 04a/04b — live /openapi.json had 55 paths, post-rebuild 60], ran openapi-typescript 7.13.0 against http://localhost:8000/openapi.json, drift gate verified idempotent via double-regen byte-diff, now contains AssetRow/AssetDetail/AssetSummary/AssetSummaryBucket/AssetListResponse/AssetFinding/AssetPromotedEvent/AssetNotePatch/AssetNoteRead/AssetScope/AssetExportFormat/StaleFilter + 5 /assets paths; web/src/__tests__/ProjectTabs.test.tsx: Wave-0 describe.skip stub replaced with 5 production tests [16-tab order + Assets index 14 / Assets active on /assets sub-paths / Brand active on /brand with Assets inactive / router.push navigation], all passing; .planning/ROADMAP.md: 12.1-06-PLAN checkbox flipped + Progress row 7/9 In Progress → 9/9 Complete 2026-04-24. Phase 12.1 COMPLETE. Pre-existing unrelated failures deferred [DashboardShell/TopNav/WebhooksTopNavLink tests + WebhookDialog/WebhooksClient TS errors on Phase 10 project_id binding]. No auto-commits per MEMORY rule."
progress:
  total_phases: 6
  completed_phases: 4
  total_plans: 60
  completed_plans: 60
  percent: 97
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-18 after v1.5)

**Core value:** A single operator can see the current cyber threat landscape — world events, actor activity, CVEs, feed signal — in one place, filter and tag it, and drill from a geo view into the attack graph behind any event.
**Current focus:** v2.0 Phase 13 Production Readiness Hardening — Wave 1 in progress: 13-00/13-01/13-02/13-03/13-04 shipped; 13-05/13-06/13-07/13-08 next.

## Current Position

Milestone: v2.0 M2 Engagement
Phase: Phase 13 (Production Readiness Hardening) — Wave 0 COMPLETE (13-00). Wave 0 shipped: backend/tests/integration/fixtures/{__init__.py, two_project.py, load_seed.py, events_query.sql, caddy_harness.py, auth_guard_harness.py} + backend/tests/integration/test_two_project_fixture_smoke.py + backend/tests/integration/test_load_seed_smoke.py + pyproject.toml load pytest marker (already in place: markers list + `-m 'not load'` in addopts) + conftest.py two_project_fixture registration. Smoke suite 5/5 green in ~15s; full integration suite `uv run pytest tests/integration/` shows 263 passed + 21 pre-existing cross-file pollution failures (documented in memory/project_test_pollution.md: Settings singleton + AuthMiddleware state + testcontainer leakage across test_auth_login/test_auth_oidc/test_migration_012/test_rekey_router/test_setup_bootstrap/test_startup_check) — same 21 failures with OR without Wave 0 additions, confirming Wave 0 is not the cause. Two-project fixture seeds 40 SQL events (20/project) + 1 AGE :Actor + 40 :Event + 40 :SEEN_IN edges into graph `intellibird_graph` with shared T1566 technique. Load seed streams in 10k-row chunks via asyncpg copy_records_to_table. Caddy harness uses caddy:2.8-alpine with auto_https off + request_header -X-Dashboard-Role (PROD-03 edge strip). Auth guard harness contracts INTELLIBIRD_ENTRYPOINT_DRY_RUN=1 for plan 13-04 to honour. Previous: Phase 12.1 COMPLETE (9/9 plans shipped). 12.1-06 closes the loop: ProjectTabs.tsx now has a 16-tab strip with Assets at position 15 (between EASM and Brand) — insert mirrored the EASM tab shape exactly ({ key, label, route }) and added pathname.includes('/assets') branch to activeKey IIFE preserving the /brand match. Header JSDoc updated 14→16 tabs. api-client.generated.ts regenerated from live OpenAPI (required rebuilding the intellibird-api:m1 image first — the running container predated 04a/04b so live /openapi.json had 55 paths; post-rebuild 60 paths including all 5 /api/projects/{id}/assets* routes). Drift gate verified idempotent via double-regen byte-diff. New types in the client: AssetRow, AssetDetail, AssetSummary, AssetSummaryBucket, AssetListResponse, AssetFinding, AssetPromotedEvent, AssetNotePatch, AssetNoteRead, AssetScope, AssetExportFormat, StaleFilter. Wave-0 ProjectTabs vitest stub replaced with 5 production tests (16-tab order verification + Assets active on /assets sub-paths + Brand active on /brand with Assets NOT active + router.push navigation) — all passing. ROADMAP Phase 12.1 Progress row flipped 7/9 In Progress → 9/9 Complete 2026-04-24. Deferred pre-existing: DashboardShell/TopNav/WebhooksTopNavLink test failures + WebhookDialog/WebhooksClient TS errors (Phase 10 project_id binding, unrelated). Next: Phase 13 or continued Phase 10/9 work (per v2.0 plan).
Last activity: 2026-04-24 — Completed 13-03 (PROD-03 X-Dashboard-Role spoof defense-in-depth). Shipped: backend/tests/integration/test_prod03_dashboard_role_spoof.py (374 LOC, 3 async tests). Test A (app_ignores) injects AuthUser(dashboard_roles=['blue']) directly into scope state via the UserInjectMiddleware pattern from test_events_query_claim.py, hits /api/events with a spoofed X-Dashboard-Role: red header, asserts response id set equals the no-header baseline and excludes 'red_only' visibility. Test B (caddy_strips) spawns a FastAPI echo app on a background uvicorn thread bound to 0.0.0.0:<ephemeral>, points Wave-0 caddy_harness at the host's primary-route IP + that port, hits Caddy with the spoof header, asserts the echoed received_headers dict (lowered keys) does NOT contain 'x-dashboard-role'; the harness Caddyfile applies `request_header -X-Dashboard-Role` at the edge. Caddy image resolves via PROD03_CADDY_IMAGE env with default caddy:2-alpine (caddy:2.8-alpine from Wave-0 default not present locally — test override keeps local/CI portable). Test C (positive_control) hits /api/events once as Blue and once as Red via two separate app instances, asserts blue_ids != red_ids and visibility sets are mutually exclusive for the role-only markers — proves the filter discriminates (without this, a broken filter would let Test A green vacuously). Baseline fixture two_project_fixture.py seeds all events with visibility='shared' — plan 13-03 adds inline _seed_visibility_discriminating_events(db_session, project_id) helper producing 5 red_only + 5 blue_only per project for the distinguishing test. Task 3.1 audit: rg -i 'x.dashboard.role' backend/app/ returns only (a) 3 new PROD-03 comments in auth.py/events.py/request_log.py citing defense-in-depth; (b) 2 pre-existing logging-only reads in request_log.py explicitly documented by the new comment block above the try/except (observability for forensic spoof-attempt review, does NOT affect filtering); (c) 1 pre-existing docstring in config.py Settings field description (metadata only). No filtering code path reads the header. Test A/C deviated from plan action step 3 by dropping project_id= from requests (Phase 10 scope-intersection predicate returns false when no ProjectScopeRow(intel_scope=true) exists — fixture has no scope rows — so Blue/Red/baseline all returned empty, breaking the discriminator; visibility filter is orthogonal to project scoping so this keeps the test focused on the dashboard_roles claim path). Echo endpoint registered ONLY inside the test module's _EchoAppServer._build_app — grep 'echo-headers' backend/app/ returns zero matches (not in production router list). Verification: cd backend && uv run pytest tests/integration/test_prod03_dashboard_role_spoof.py -x -q → 3 passed in 15.10s; full integration (excluding 6 pre-existing pollution-flagged files per memory/project_test_pollution.md) → 264 passed, 1 failed in test_prod01_cross_project_leakage::test_intel_scoped (pre-existing, plan 13-01's scope, logged as deferred). ROADMAP Phase 13 Progress 4/9 → 5/9 In Progress; 13-03-PLAN checkbox set. Previous: 13-01 (PROD-01 cross-project leakage integration test). Shipped: backend/tests/integration/test_prod01_cross_project_leakage.py (216 LOC, 5 async tests). Surfaces covered: (1) /api/events?project_id=<A> with jwt_a returns exact 20 Project A event IDs set-equals expected — no Project B IDs leak; required seeding a permissive keyword='evt' project_scope_row to escape build_scope_predicate's empty→false short-circuit (per project_scope.py:182). (2) /api/projects/{project_b}/assets with jwt_a → 403 via require_project_membership(Observer) on assets router. (3) /api/events/{event_in_B}/graph?project_id=<A> with jwt_a → 403-or-404 (current: 404 via graph_traversal.py:117 seed/project mismatch). (4) Raw AGE bounded BFS ':SEEN_IN*1..3' from shared :Actor into Event{project_id:'A'} then WHERE e.project_id='B' → count 0 (vertex-label gate holds). (5) Positive control: same bounded BFS scoped to Event{project_id:'A'} → 20 (Pitfall 2 empty-graph guard). Auth harness mirrors test_admin_users._patch_auth: AUTH_ENABLED=True + JWT_SIGNING_KEY pinned to 'j'*64 matching fixture + async token_version/jti stubs. JWTs minted by Wave-0 fixture using mint_access_token_with_pm with pm=[[project_id, Contributor]]. No unbounded [:SEEN_IN*] paths (verified by grep). Two codebase gaps surfaced per plan action step 7 and documented in 13-01-SUMMARY.md: GAP-1 /api/events does NOT intersect request.state.user.project_memberships with the row filter — a Project A JWT omitting project_id sees all projects' events (test works around by passing project_id explicitly); GAP-2 graph router has no require_project_membership — isolation rides on indirect graph_traversal.py:117 seed/project mismatch check returning None → 404 (correct today but wrong layer). Both gaps are functional defects guarded by indirect mechanisms; neither was in scope for 13-01; both should be scheduled in downstream hardening plans. Verification: pytest tests/integration/test_prod01_cross_project_leakage.py -x -q → 5 passed in 15.55s; combined with two_project/load_seed smoke → 10 passed in 18.56s. ROADMAP Phase 13 Progress row flipped 3/9 → 4/9 In Progress; 13-01-PLAN checkbox set. Previous: 13-04 (PROD-07 infra flip + PROD-03 edge strip). Shipped: ops/Caddyfile (Caddy 2.8 :443/:80 single-site block, request_header -X-Dashboard-Role on @api path matcher, tls internal for lab, encode zstd gzip, explicit prod-swap instructions in header comment); ops/api-entrypoint.sh (bash set -euo pipefail; AUTH_ENABLED != true → exit 78 EX_CONFIG with 4-line operator message; JWT_SIGNING_KEY + SSO_ISSUER_URL ${VAR:?} guards; INTELLIBIRD_ENTRYPOINT_DRY_RUN=1 short-circuit honouring Wave-0 harness contract; otherwise cd /app + alembic upgrade head + exec gunicorn); ops/docker-compose.yml (v1.5 header comment replaced with v2.0/PROD-07 rationale; api: 127.0.0.1:8000:8000 publish removed + command=["/app/api-entrypoint.sh"] + ./api-entrypoint.sh:/app/api-entrypoint.sh:ro bind-mount; web: 127.0.0.1:3000:3000 publish removed; NEW caddy service on caddy:2.8-alpine with ports 80:80 + 443:443 + 443:443/udp [HTTP/3], Caddyfile bind-mount, caddy_data + caddy_config named volumes, depends_on api[healthy]+web[started], restart unless-stopped); backend/tests/integration/test_entrypoint_auth_guard.py (5 subprocess tests via Wave-0 run_entrypoint harness: refuses_without_auth exit78+AUTH_ENABLED in stderr, refuses_auth_false exit78, requires_jwt_key non-zero+JWT_SIGNING_KEY, requires_sso_issuer non-zero+SSO_ISSUER_URL, dry_run_ok exit0 with all guards satisfied; skips if bash missing); backend/tests/integration/test_compose_public_binding.py (4 tests: only_caddy_publishes_public_ports set equality {caddy}, api_service_has_no_host_publish, web_service_has_no_host_publish, caddy_publishes_both_80_and_443; parses docker compose config --format json; skips cleanly if docker compose unavailable). Combined run 9 passed in 8.45s. docker compose config --quiet exits 0. KNOWN GAP: ops/api-entrypoint.sh is mode 0644 not 0755 — sandbox blocked chmod +x during session; harness invokes via bash <path> so tests pass, but docker compose up will fail until operator runs `chmod +x ops/api-entrypoint.sh`. Documented in 13-04-SUMMARY §Issues Encountered + §User Setup Required; long-term fix is Dockerfile COPY + chmod +x in image bake. Decisions: profile split rejected (CONTEXT deferred — api/web publish removed outright, db/redis 127.0.0.1 publish retained as v1.5 operator-local tooling, out of PROD-07 scope); entrypoint bind-mount chosen over Dockerfile COPY (minimises rebuild surface, less invasive); INTELLIBIRD_ENTRYPOINT_DRY_RUN=1 honoured per Wave-0 harness not plan-body _DRY_RUN=true (harness is authoritative); UDP 443 published for HTTP/3 (zero cost lab, required when hostname ACMEd); tls internal default (Pitfall 3 — avoid Let's Encrypt rate limits in smoke). Deviations: 4 auto-fixed (1 blocking env-var reconciliation, 3 missing-critical test/feature additions — SSO_ISSUER_URL test, HTTP/3 UDP publish, split compose assertions into 4 focused tests). No auto-commits per MEMORY rule — files staged. Previous: 13-02 PROD-02 active-scan gate pentest (6 tests green).

Progress: [█████████▊] 99% (35/40 v2.0 plans complete — Phase 13: 13-00/13-01/13-02/13-03/13-04 done, 4 Phase 13 plans remaining: 13-05/13-06/13-07/13-08, plus 10-06)
v2.0 progress: plans 8-00..8-05, 9-00..9-08, 10-01..10-05, 10-07..10-13, 12.1-00..12.1-06, 13-00, 13-01, 13-02, 13-03, 13-04 shipped

## v2.0 Phase Summary

| Phase | Name | Requirements | Plans | Research Flag |
|-------|------|--------------|-------|---------------|
| 8 | Pre-Auth Infrastructure Hardening | INFRA-01..06 | TBD | no |
| 9 | Authentication Foundation | AUTH-01..04 | TBD | yes (Authentik OIDC + Auth.js v5) |
| 10 | Projects Foundation | PRJ-01..07 | TBD | no (planning-time spike only) |
| 11 | EASM via BBOT | EASM-01..10 | TBD | yes (BBOT subprocess cancellation) |
| 12 | Brand Protection | BRP-01..05 | TBD | no |
| 13 | Production Readiness Hardening | PROD-01..07 | TBD | no |

**Coverage:** 39/39 v2.0 requirements mapped (6 INFRA + 4 AUTH + 7 PRJ + 10 EASM + 5 BRP + 7 PROD)
**Dependency chain:** 8 → 9 → 10 → {11 ∥ 12} → 13
**Descope candidates (if milestone risk demands):** PRJ-06, PRJ-07, EASM-08 → v2.1

## Performance Metrics

**Velocity (v1.5):**

- Total plans completed: 60
- Average duration: ~28min/plan (aggregated)
- Total execution time: ~28 hours
- Operator-live-approved: 100%

**v2.0 By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

**Recent Trend:**

- Last 5 plans: all v1.5 Phase 7 (Webhook Alerts) completion
- Trend: v1.5 shipped clean; v2.0 not yet begun

*Updated after each plan completion*
| Phase 01-foundation P00 | 4min | 3 tasks | 20 files |
| Phase 01-foundation P01 | 2min | 2 tasks | 4 files |
| Phase 02-ingestion-pipeline P00 | 12min | 4 tasks | 21 files |
| Phase 02-ingestion-pipeline P01 | 35min | 2 tasks | 5 files |
| Phase 02-ingestion-pipeline P02 | 25min | 3 tasks | 8 files |
| Phase 02-ingestion-pipeline P03 | 30 | 2 tasks | 5 files |
| Phase 02-ingestion-pipeline P04 | 35min | 2 tasks | 5 files |
| Phase 02-ingestion-pipeline P06 | 75min | 2 tasks | 8 files |
| Phase 02-ingestion-pipeline P07 | 25min | 2 tasks | 3 files |
| Phase 03-source-registry-retention P00 | 25 | 3 tasks | 35 files |
| Phase 03-source-registry-retention P01 | 25min | 2 tasks | 4 files |
| Phase 03-source-registry-retention P05 | 35min | 2 tasks | 4 files |
| Phase 03-source-registry-retention P02 | 70 | 3 tasks | 7 files |
| Phase 03-source-registry-retention P03 | 35min | 2 tasks | 4 files |
| Phase 04-query-api-archiver P02 | 45 | 2 tasks | 10 files |
| Phase 04-query-api-archiver P03 | 28 | 2 tasks | 5 files |
| Phase 04-query-api-archiver P05 | 18 | 2 tasks | 5 files |
| Phase 04-query-api-archiver P06 | 45 | 2 tasks | 7 files |
| Phase 04 P07 | 30 | 2 tasks | 7 files |
| Phase 05-dual-dashboard-shell P00 | 12min | 3 tasks | 20 files |
| Phase 05-dual-dashboard-shell P02 | 8min | 2 tasks | 5 files |
| Phase 05-dual-dashboard-shell P07 | 18 | 1 tasks | 4 files |
| Phase 05-dual-dashboard-shell P08 | 10 | 2 tasks | 6 files |
| Phase 07-webhook-alerts P07 | 25 | 1 tasks | 4 files |
| Phase 08-pre-auth-infra-hardening P00 | 3min | 2 tasks | 10 files |
| Phase 08-pre-auth-infra-hardening P01 | 3 | 2 tasks | 7 files |
| Phase 08-pre-auth-infra-hardening P02 | 5 | 1 tasks | 4 files |
| Phase 08-pre-auth-infra-hardening P03 | 18 | 2 tasks | 8 files |
| Phase 08-pre-auth-infra-hardening P04 | 10 | 2 tasks | 8 files |
| Phase 08-pre-auth-infra-hardening P05 | 1 | 2 tasks | 2 files |
| Phase 09-authentication-foundation P00 | 15min | 3 tasks | 25 files |
| Phase 09-authentication-foundation P01 | 25min | 2 tasks | 7 files |
| Phase 09-authentication-foundation P02 | 20min | 2 tasks | 10 files |
| Phase 09-authentication-foundation P03 | 30min | 3 tasks | 8 files |
| Phase 09-authentication-foundation P04 | 35min | 2 tasks | 6 files |
| Phase 09-authentication-foundation P05 | 35min | 2 tasks | 19 files |
| Phase 09-authentication-foundation P06 | 15 | 2 tasks | 3 files |
| Phase 09-authentication-foundation P07 | 15 | 4 tasks | 15 files |
| Phase 09-authentication-foundation P08 | 30 | 3 tasks | 10 files |
| Phase 10-projects-foundation P01 | 14min | 3 tasks | 10 files |
| Phase 10-projects-foundation P02 | 13min | 3 tasks | 7 files |
| Phase 10-projects-foundation P05 | 10min | 2 tasks | 11 files |
| Phase 10-projects-foundation P03 | 9min | 2 tasks | 3 files |
| Phase 10-projects-foundation P04 | 3min | 2 tasks | 3 files |
| Phase 10-projects-foundation P07 | 22min | 2 tasks | 7 files |
| Phase 10-projects-foundation P08 | 18min | 2 tasks | 8 files |
| Phase 10-projects-foundation P09 | 3min | 2 tasks | 5 files |
| Phase 10-projects-foundation P13 | 5min | 2 tasks | 5 files |
| Phase 10-projects-foundation P10 | 5min | 2 tasks | 8 files |
| Phase 10-projects-foundation P12 | 5min | 2 tasks | 7 files |
| Phase 10-projects-foundation P11 | 7min | 3 tasks | 7 files |
| Phase 11-easm-via-bbot P07 | 8 | 2 tasks | 4 files |
| Phase 11-easm-via-bbot P01 | 35 | 2 tasks | 7 files |
| Phase 11-easm-via-bbot P00 | 35 | 3 tasks | 21 files |
| Phase 11-easm-via-bbot P03 | 20 | 2 tasks | 3 files |
| Phase 11-easm-via-bbot P06 | 20 | 1 tasks | 3 files |
| Phase 11-easm-via-bbot P02 | 25 | 2 tasks | 5 files |
| Phase 11-easm-via-bbot P04a | 25 | 1 tasks | 3 files |
| Phase 11-easm-via-bbot P04b | 15 | 1 tasks | 4 files |
| Phase 11-easm-via-bbot P05 | 25 | 1 tasks | 6 files |
| Phase 11-easm-via-bbot P11 | 20 | 2 tasks | 4 files |
| Phase 11-easm-via-bbot P09 | 12 | 2 tasks | 9 files |
| Phase 12-brand-protection P01 | 5min | 2 tasks | 7 files |
| Phase 12-brand-protection P00 | 45min | 3 tasks | 24 files |
| Phase 12-brand-protection P03 | 8min | 2 tasks | 5 files |
| Phase 12-brand-protection P02 | 5min | 2 tasks | 5 files |
| Phase 12-brand-protection P04 | 10min | 1 tasks | 2 files |
| Phase 12-brand-protection P05 | 18min | 2 tasks | 5 files |
| Phase 12-brand-protection P06 | 25min | 2 tasks | 4 files |
| Phase 12-brand-protection P07 | 15min | 1 tasks | 1 files |
| Phase 12-brand-protection P09 | 35min | 2 tasks | 6 files |
| Phase 12-brand-protection P10 | 6 min | 2 tasks | 4 files |
| Phase 12-brand-protection P11 | 5 min | 1 tasks | 1 files |
| Phase 12-brand-protection P12 | 12min | 2 tasks | 4 files |
| Phase 12.1-project-asset-surface P00 | 1min | 2 tasks | 13 files |
| Phase 12.1-project-asset-surface P01 | 8min | 2 tasks | 5 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Stack: Python 3.12 + FastAPI (forced by STIX/TAXII ecosystem gravity — no viable alternatives)
- Graph layer: Apache AGE (Cypher on Postgres) — validate co-installation with TimescaleDB in Phase 1; networkx-on-Postgres is the documented fallback
- Graph renderer: Cytoscape.js (not Sigma.js) — dagre layout, 200-node server cap resolves browser performance risk
- Geo map: MapLibre GL JS (not Leaflet) — supercluster clustering from first render
- Cold archive: TimescaleDB retention policies (MinIO/S3 deferred to M2+ once hot-store patterns are validated)
- Auth: Deferred to M2; visibility enum and X-Dashboard-Role header pattern established in M1 schema so M2 is a middleware swap
- [v2.0 Roadmap]: 6-phase structure derived from research synthesis (not imposed): Phase 8 infra hardening precedes Phase 9 AUTH because blocker C-1 (SECRET_KEY rotation corrupts credentials_enc) and H-1 (Route Handler proxy bypasses auth during rollout) must be addressed before auth code lands
- [v2.0 Roadmap]: Phase 11 (EASM) and Phase 12 (Brand Protection) are parallel-safe — disjoint migration, router, queue, frontend
- [v2.0 Roadmap]: Phase 13 is not optional per PROJECT.md "no production use without auth" constraint — turns v2.0 from code-complete to production-safe via integration tests + operational drills
- [v2.0 Roadmap]: PRJ-06, PRJ-07, EASM-08 flagged as defer-risk (v2.1 candidates); INFRA + PROD requirements stay as prerequisites/quality-gates
- [v2.0 Roadmap]: No local users table — Authentik is sole user store; `projects.created_by` stores Authentik `sub` as TEXT with no FK (research-synthesised decision)
- [v2.0 Roadmap]: BBOT runs only inside dedicated `easm-worker` container via Docker subprocess — never pip-installed into API/worker image (BBOT issue #2354 daemonic-process crash, no upstream fix)
- [Phase 01-foundation]: Python 3.12 pin hard via requires-python=>=3.12,<3.13; stix2 and taxii2-client pinned exactly (3.0.2 / 2.3.0)
- [Phase 01-foundation]: Alembic env.py reads DATABASE_URL from env only; alembic.ini sqlalchemy.url left empty to prevent config-file secret leakage
- [Phase 01-foundation]: Wave 0 stub pattern: every VALIDATION.md test file exists as a pytest.skip placeholder referencing its owning plan
- [Phase 01-foundation]: Compose loopback invariant enforced at both file-layer (127.0.0.1: prefix) and regression-layer (test_compose_bind.py) — PITFALLS C-1 mitigation has two independent guards
- [Phase 01-foundation Plan 07]: AGE Docker build requires clang19 Alpine package (not generic clang); timescaledb:latest-pg16 image compiled with CLANG=clang-19 in Makefile.global but ships only llvm19-libs runtime — clang19 build package must be explicit in db.Dockerfile
- [Phase 01-foundation Plan 07]: web/public directory must exist for Next.js Docker multi-stage build; created as web/public/.gitkeep
- [Phase 02-ingestion-pipeline Plan 00]: feedparser==6.0.12 pinned exactly; nvdlib and cryptography range-pinned per plan spec
- [Phase 02-ingestion-pipeline Plan 00]: Golden fixtures are hand-authored minimal documents — schema-correct but not live captures; real HTTP round-trips deferred to integration tests
- [Phase 02-ingestion-pipeline Plan 00]: fixtures_dir fixture uses _pytest2 alias to avoid collision with existing import pytest in integration conftest
- [Phase 02-ingestion-pipeline Plan 00]: TLP canonical UUIDs f88d31f6 (AMBER) and 34098fce (GREEN) embedded in taxii_mitre_sample.json for plan 02-05 TLP resolution tests
- [Phase 02-ingestion-pipeline]: TimescaleDB unique index must include partition column (observed_at): use op.create_index with (source_id, content_hash, observed_at) instead of ALTER TABLE ADD CONSTRAINT; workers use 3-column ON CONFLICT target
- [Phase 02-ingestion-pipeline]: testcontainers fixtures must use intellibird-db:m1 (not stock timescaledb image) because migration 001 requires Apache AGE extension
- [Phase 02-ingestion-pipeline]: cve_details.event_id has no FK to events — consistent with attack_technique_tags pattern; app-level integrity only (TimescaleDB hypertable FK limitation)
- [Phase 02-ingestion-pipeline Plan 02]: ON CONFLICT index_elements=['source_id','content_hash','observed_at'] — 3-column target required by TimescaleDB hypertable unique index from plan 01 deviation
- [Phase 02-ingestion-pipeline Plan 02]: HKDF info string b"intellibird-credentials" is deployment-fixed — changing it invalidates all stored credentials_enc values
- [Phase 02-ingestion-pipeline Plan 02]: _persist_event and update_source_health do NOT commit; callers (workers) commit at end of batch for efficiency
- [Phase 02-ingestion-pipeline Plan 02]: content_hash stored as lowercase 64-char hex (hashlib.hexdigest()) — not base64; readable in psql, no padding edge cases
- [Phase 02-ingestion-pipeline]: Actor queue='ingest' for feed workers (rss, nvd, taxii); bootstrap_attack uses queue='maintenance'
- [Phase 02-ingestion-pipeline]: poll_rss_impl/poll_rss split: sync impl function + one-line actor wrapper; integration tests call impl directly
- [Phase 02-ingestion-pipeline]: feedparser accepts absolute local paths directly — no file:// prefix; bozo=1 is only parse_error when entries is also empty
- [Phase 02-ingestion-pipeline]: TAXII 2.1 discovery URL must be passed to taxii2client.v21.Server (not api-root URL); api-root URL returns zero api_roots per TAXII-SPIKE.md
- [Phase 02-ingestion-pipeline]: OTX speaks TAXII 1.1 XML (not TAXII 2.1 JSON); scope-C approved: hand-rolled XML poller in taxii1_otx.py using requests+lxml; dispatched via URL heuristic /taxii/discovery
- [Phase 02-ingestion-pipeline]: Cursor advance D-15/D-16: last_cursor persisted ONLY after all pages of current poll committed; mid-poll crash causes re-poll (dedup absorbs duplicates)
- [Phase 02-ingestion-pipeline]: X-TAXII-Date-Added-Last header not accessible via taxii2client envelope (_raw_response is None); cursor uses max(modified) fallback across returned batch
- [Phase 02-ingestion-pipeline Plan 04]: RETURNING id on events INSERT used to link cve_details + attack_technique_tags; _persist_event (which returns only int) not used in NVD worker
- [Phase 02-ingestion-pipeline Plan 04]: Backoff sleeps unconditionally after each failed attempt (30, 60, 120s then raise) — 3 sleeps for 3 attempts; 4xx non-429 raises immediately without sleeping (D-30)
- [Phase 02-ingestion-pipeline Plan 04]: Integration test dedup assertions must use event_id filter not global cve_id to avoid false count inflation across module-scoped shared DB fixture
- [Phase 02-ingestion-pipeline Plan 07]: APScheduler uses psycopg2 sync connection in _load_source_jobs (BlockingScheduler is sync; asyncio unusable); URL converted from postgresql+asyncpg:// to postgresql://
- [Phase 02-ingestion-pipeline Plan 07]: Job id convention poll_{feed_type}_{source_id_uuid}; unknown feed_type emits scheduler_unknown_feed_type WARNING + skips (not raises) — Phase 3 CRUD may add new types before scheduler update
- [Phase 02-ingestion-pipeline Plan 07]: build_scheduler wraps _load_source_jobs in try/except — Phase 1 ATT&CK refresh survives transient Postgres unavailability at scheduler startup
- [Phase 02-ingestion-pipeline Plan 07]: Phase 3 scheduler hot-reload needed: when source CRUD UI adds/edits/deletes a source, scheduler must re-register jobs; recommend /admin/scheduler/reload endpoint
- [Phase 03-source-registry-retention]: Tailwind v4 requires @tailwindcss/postcss PostCSS plugin; globals.css uses @import 'tailwindcss' syntax
- [Phase 03-source-registry-retention]: shadcn components.json written manually (slate, new-york, dark, CSS vars) then npx shadcn@latest add used for component install
- [Phase 03-source-registry-retention Plan 01]: archive_policy server_default='drop' — existing sources will drop events past hot window unless explicitly changed via UI
- [Phase 03-source-registry-retention Plan 01]: Enum creation uses raw DO $$ EXCEPTION block (CREATE TYPE IF NOT EXISTS does not exist in PostgreSQL); create_type=False on SQLAlchemy Enum when type is pre-created by raw SQL
- [Phase 03-source-registry-retention Plan 01]: Running container predated migration 003; file copied via docker cp as workaround — operator must rebuild api image to bake 003 permanently
- [Phase 03-source-registry-retention Plan 05]: Archiver is application-level Python loop (not TimescaleDB add_retention_policy) — per-source hot_retention_days cannot be expressed as hypertable-wide DDL (Pitfall 3)
- [Phase 03-source-registry-retention Plan 05]: commit-per-source in archive_once: each source committed individually; exception triggers rollback+continue so one bad source does not halt the pass
- [Phase 03-source-registry-retention Plan 05]: archiver_job_wrapper creates/disposes its own sync engine rather than sharing the async engine from database.py (APScheduler is sync)
- [Phase 03-source-registry-retention Plan 05]: move-to-cold sets archived=true only (stub row preserved per STO-04); content field nulling deferred to M2
- [Phase 03-source-registry-retention]: Python-side UUID generation in create_source handler for SQLite test compatibility
- [Phase 03-source-registry-retention]: response_class=Response on DELETE 204 endpoint required by FastAPI body assertion
- [Phase 03-source-registry-retention]: monkeypatch.setattr on settings.SECRET_KEY (not env) for crypto test isolation after singleton load
- [Phase 03-source-registry-retention Plan 06]: RELOAD_CHANNEL imported from app.services.source_events (not hardcoded) — single source of truth
- [Phase 03-source-registry-retention Plan 06]: Daemon thread exits on Redis disconnect; operator restarts scheduler container to recover; graceful degradation means ATT&CK+archiver jobs still run even if listener start fails
- [Phase 03-source-registry-retention Plan 06]: os.environ.setdefault() block before app.* imports in unit test files that directly import scheduler/jobs.py (pydantic-settings singleton loaded at import time)
- [Phase 03-source-registry-retention Plan 03]: _probe_rss/_probe_nvd/_probe_taxii return 4-tuple (bool, int, int, str|None) — pure functions, no Pydantic dependency, lazy third-party imports
- [Phase 03-source-registry-retention Plan 03]: TAXII probe uses headers kwarg (not requests.auth.AuthBase) for bearer auth — taxii2client v2.3.0 accepts headers dict directly
- [Phase 03-source-registry-retention Plan 03]: test_connection handler is sync (not async) — probe libraries all sync; FastAPI runs sync handlers in threadpool
- [Phase 03-source-registry-retention Plan 03]: HTTP 200 always returned from test-connection (ok=False in body) — UI-SPEC D-08 non-blocking contract
- [Phase 04-query-api-archiver Plan 01]: down_revision uses 0003_archive_policy (with leading zero) — existing chain uses zero-padded IDs; spec was incorrect without the leading zero
- [Phase 04-query-api-archiver Plan 01]: asyncpg rejects :param::type PostgreSQL cast syntax in text() SQL; use CAST(:param AS type) for type casts in raw async SQL
- [Phase 04-query-api-archiver Plan 01]: API container must be rebuilt (docker compose build api) after adding new Alembic migration files — no volume mount for /app/alembic/versions
- [Phase 04-query-api-archiver Plan 01]: filter_presets.name has DB-level CHECK constraint ^[a-z0-9_-]{1,64}$ as defense-in-depth alongside API-layer validation
- [Phase 04-query-api-archiver Plan 01]: GENERATED ALWAYS AS STORED confirmed working on live TimescaleDB hypertable — standard Postgres feature, no special handling needed
- [Phase 04-query-api-archiver]: COALESCE(events.tags, '{}') used for NULL-safe ARRAY containment filter (Pitfall 6)
- [Phase 04-query-api-archiver]: TLP naming mismatch: migration 001 uses TLP 1.0 names (TLP:GREEN); filter API expects TLP 2.0 names (green) — seed upserts correct names for tests; production migration needed
- [Phase 04-query-api-archiver]: Composite PK lookup via select(Event).where(Event.id == id) not session.get() — avoids TimescaleDB composite PK pitfall
- [Phase 04-query-api-archiver]: PATCH /api/events/{id}/tags: TAG_REGEX=^[a-z0-9_-]{1,32}$ applied after server-side lowercase; any invalid tag in add OR remove → 422; raw SQL UPDATE for ARRAY write (asyncpg compat)
- [Phase 04-query-api-archiver]: sa.column('search_tsv') used for FTS expression — Event ORM has no mapped search_tsv attribute (generated column not in ORM); sa.column() is unlabelled column reference that compiles correctly
- [Phase 04-query-api-archiver]: Router branches on 'free_text is not None' not truthiness — empty string is a 400 case, not a pass-through to the standard non-FTS path
- [Phase 04-query-api-archiver]: CAST(:params AS jsonb) used throughout presets router — asyncpg rejects ::type shorthand (pre-empted from 04-01 fix)
- [Phase 04-query-api-archiver]: Pitfall 8 applied in upsert: ON CONFLICT DO UPDATE explicitly sets updated_at = now() (server_default only fires on INSERT)
- [Phase 04-query-api-archiver]: 04-06: Python BFS for graph traversal (vs recursive CTE) — simpler bounded fan-out, mid-traversal node-cap enforcement without SQL complexity
- [Phase 04-query-api-archiver]: 04-06: ge=MIN_DEPTH/le=MAX_DEPTH FastAPI Query validation gives 422; ValueError in service gives 400 — two-level depth enforcement
- [Phase 04]: RequestLogMiddleware added outermost via add_middleware AFTER CORSMiddleware
- [Phase 04]: Integration tests set env vars at module level before app import to satisfy pydantic-settings
- [Phase 05-dual-dashboard-shell Plan 00]: shadcn CLI peer-dep conflict — sheet.tsx and card.tsx created manually; @radix-ui/react-dialog already installed so no new Radix dep needed
- [Phase 05-dual-dashboard-shell Plan 00]: world.pmtiles placeholder stub created (build.protomaps.com URL 404); GeoMap error boundary in 05-02 handles invalid pmtiles; NEXT_PUBLIC_MAP_TILES_URL override documented
- [Phase 05-dual-dashboard-shell Plan 00]: vi.mock() stubs for maplibre-gl/pmtiles/cytoscape/react-cytoscapejs/cytoscape-dagre placed in vitest.setup.ts (not per-test); HTMLCanvasElement.getContext polyfilled to prevent jsdom crashes
- [Phase 05-dual-dashboard-shell Plan 00]: react-cytoscapejs installed with --legacy-peer-deps (peer-declares React 18, repo pins React 19)
- [Phase 05-dual-dashboard-shell Plan 02]: Module-level pmtilesRegistered boolean flag used (not maplibregl.getProtocol() check) — vitest mock stubs getProtocol as vi.fn() returning undefined always; flag is deterministic
- [Phase 05-dual-dashboard-shell Plan 02]: DashboardShell renders TopNav inside negative-margin wrapper (-1.5rem -1.5rem 0) to escape layout.tsx padding; layout.tsx NOT modified (deferred to 05-08)
- [Phase 05-dual-dashboard-shell Plan 02]: Two Suspense boundaries in DashboardShell — one wrapping GeoMap (loading skeleton), one wrapping children slot (Next.js 15 useSearchParams requirement for 05-05 EventDetailDrawer)
- [Phase 05-dual-dashboard-shell]: 05-07: dagreRegistered module-level flag guards Cytoscape.use(dagre) against double registration
- [Phase 05-dual-dashboard-shell]: 05-07: next/dynamic + ssr:false wraps AttackGraphImpl to prevent SSR of Cytoscape DOM dependency
- [Phase 05-dual-dashboard-shell]: DashboardClient owns events-list state; DashboardEventsList accepts optional items prop for backward-compat self-fetch
- [Phase 05-dual-dashboard-shell]: Removed global TopNav from layout.tsx to prevent double-nav on dashboard routes; DashboardShell provides role-aware TopNav for /red and /blue
- [Phase 06-combined-threat-visualisation]: shadcn CLI separator install failed on React 19/vite 8 peer-dep — manual fallback: npm install --legacy-peer-deps @radix-ui/react-separator, write separator.tsx manually
- [Phase 06-combined-threat-visualisation]: vitest supercluster mock returns synchronous values (getClusterExpansionZoom: 14 as number) to match MapLibre v4 synchronous wrapper; appended to vitest.setup.ts as module-level vi.mock
- [Phase 06-combined-threat-visualisation Plan 02]: Migration 005 revision ID 005_geo_backfill_and_indexes; autocommit_block wraps CREATE/DROP INDEX CONCURRENTLY per Pitfall 2
- [Phase 06-combined-threat-visualisation Plan 02]: resolve_geo lazy-imported inside _persist_event (not module top-level) to keep worker boot cheap; pre-populated geo_lat/lon skips resolution entirely
- [Phase 06-combined-threat-visualisation Plan 02]: backfill_geo_once uses keyset cursor (observed_at, id) DESC with BATCH_SIZE=500; commits per batch to avoid long-running transactions
- [Phase 06-combined-threat-visualisation Plan 02]: DateTrigger one-shot fires at startup+30s; timezone import added to jobs.py; volume mount ./geolite:/app/geolite:ro on worker service only
- [Phase 06-combined-threat-visualisation Plan 03]: FTS query compilation uses str(stmt) not literal_binds=True — PostgreSQL REGCONFIG type ('english') has no literal renderer in SQLAlchemy
- [Phase 06-combined-threat-visualisation Plan 03]: tag_source key absent from GraphResult node data dict when None (not set to None) — Cytoscape stylesheet checks key presence
- [Phase 06-combined-threat-visualisation Plan 03]: EventItem geo_lat/geo_lon required fields (not optional) in TypeScript type — test fixtures updated with null values
- [Phase 06-combined-threat-visualisation Plan 04]: vitest.setup.ts Map and Protocol mocks must use regular functions (not arrow) for constructors called with new — vi.fn(function MockName() { return instance; })
- [Phase 06-combined-threat-visualisation Plan 04]: eventsSnapshot ref bridges events state into map load callback closure; second useEffect([events]) calls source.setData() for post-load re-sync
- [Phase 06-combined-threat-visualisation Plan 04]: MapLibre v5 Promise API — await source.getClusterExpansionZoom(clusterId) not callback style
- [Phase 06-combined-threat-visualisation Plan 06]: WIDGET_FILTER_STATIC uses Omit<EventsQuery, "observed_from"> — observed_from computed fresh in useEffect to avoid stale timestamps; spread into both listEvents query and router.push URL
- [Phase 06-combined-threat-visualisation Plan 06]: bucketByDay extracted to bucketByDay.ts module (not inlined per-widget) for direct test import and DRY reuse
- [Phase 06-combined-threat-visualisation Plan 06]: WidgetCard CTA uses Next.js Link with e.stopPropagation() to prevent card onClick navigation when user targets /sources link specifically
- [Phase 06-combined-threat-visualisation Plan 06]: tag_mode omitted (undefined) for Blue widgets — default 'all' semantics; only ActorInfra and ToolingChatter set tag_mode:"any" per D-20
- [Phase 06-combined-threat-visualisation Plan 07]: /events preset URL encoding: encodeURIComponent(JSON.stringify(query)) in ?preset= param; parseFiltersFromSearchParams decodes and Object.assign-merges before individual params override
- [Phase 06-combined-threat-visualisation Plan 07]: /events role context: localStorage read in useEffect, stored in local state; EventsClient wraps subtree in RoleProvider — no outer provider needed (matches /sources pattern)
- [Phase 06-combined-threat-visualisation Plan 07]: Date range inputs on /events use native HTML <input type="date"> (not shadcn Input) — meets spec compliance for M1 without additional wiring
- [Phase 06]: Migration 005: DROP CONCURRENTLY for TimescaleDB compatibility — hypertables do not support CREATE INDEX CONCURRENTLY
- [Phase 07-webhook-alerts]: showDeleteConfirm reads bound_preset_names.length from hydrated Webhook object — no extra API call needed per D-36
- [Phase 08-00]: Wave 0 stub pattern: module-level pytest.skip(allow_module_level=True) with owning-plan reference; Wave 1+ plans activate test bodies by removing the skip line
- [Phase 08-00]: pnpm script names gen:api and gen:api:check locked by CONTEXT.md — openapi:generate and openapi:check must NOT be used; openapi-typescript installed in Plan 04 not Plan 00
- [Phase 08-00]: Unit-level stubs only in backend/tests/unit/infra/ — integration-level test_rekey_endpoint.py and test_auth_flag.py deferred to Phase 13 per CONTEXT.md lock
- [Phase 08-pre-auth-infra-hardening]: REKEY_FROM_SECRET/SETUP_TOKEN: str|None=None with no placeholder validation — scoped to SECRET_KEY only per CONTEXT.md lock
- [Phase 08-pre-auth-infra-hardening]: app/state.py thin module with mutable decrypt_check variable breaks main.py <-> system.py circular import
- [Phase 08-pre-auth-infra-hardening]: Migration 007 uses PG 11+ fast-path server_default, ON CONFLICT DO NOTHING canary insert, no app imports
- [Phase 08-pre-auth-infra-hardening]: Wave 0 test_migration_007.py DELETED (SQLite not valid for PG-specific DDL); real test promoted to tests/integration/ with testcontainer PG
- [Phase 08-pre-auth-infra-hardening]: Integration test for rekey moved to tests/integration/ (requires live DB via db_session fixture, not unit-level stub)
- [Phase 08-pre-auth-infra-hardening]: Plan 03 AuthMiddleware MUST add /api/admin/rekey-credentials to EXEMPT_PATHS — endpoint is pre-auth by design
- [Phase 08-pre-auth-infra-hardening]: fastapi_app local var inside create_app() avoids shadowing app package needed for import app.state; integration tests for startup check placed in tests/integration/ (requires live DB, not unit-mockable)
- [Phase 08-pre-auth-infra-hardening]: AuthMiddleware EXEMPT_PATHS includes /api/admin/rekey-credentials (pre-auth endpoint); decrypt failure is fail-soft (CRITICAL log + status field); test name-shadowing fixed via import app.state as state_module
- [Phase 08-pre-auth-infra-hardening]: openapi-typescript@7.13.0 generates api-client.generated.ts; EventItem/Webhook types override optional->required for caller compat; BACKEND_URL env override in openapi-check.mjs for host-side dev use
- [Phase 08-pre-auth-infra-hardening]: NoAuthBanner: decrypt_check=failed branch is first check — takes precedence over auth_enabled=false; proxy strips x-dashboard-role only when process.env.AUTH_ENABLED==='true' (exact string match per H-1 mitigation)
- [Phase 09-authentication-foundation Plan 00]: Wave 0 stub pattern from Phase 8 applied exactly: pytest.skip(allow_module_level=True) with owning-plan reference; integration stubs add pytestmark = pytest.mark.integration ABOVE the skip call
- [Phase 09-authentication-foundation Plan 00]: argon2_fast fixture wraps app.security.passwords import in try/except ImportError — module does not exist in Wave 0, lands in plan 09-02; this prevents collection errors during Phase 9 Wave 0
- [Phase 09-authentication-foundation Plan 00]: Two VALIDATION.md stubs added beyond plan file list (NoAuthBanner.test.tsx + auth-proxy.test.ts) per validation_note directive — closes Warning 2 from plan checker
- [Phase 09-authentication-foundation Plan 01]: JWT_SIGNING_KEY tests use subprocess pattern (like Phase 8 tests in same file) — module-level Settings() singleton prevents monkeypatch+direct-import approach from working; subprocess isolation is the correct pattern for all config.py tests
- [Phase 09-authentication-foundation Plan 01]: test_auth_middleware.py required JWT_SIGNING_KEY in os.environ.setdefault block — Phase 8 file imports settings at module level; adding required JWT_SIGNING_KEY there prevents collection-time ValidationError
- [Phase 09-authentication-foundation Plan 01]: Migration 004 pre-existing bug (gen_random_uuid without parentheses) prevents testcontainer-based integration tests from reaching migration 007/008; tests skip gracefully, documented in deferred-items.md
- [Phase 09-authentication-foundation Plan 02]: test_expired_token_raises mints token with exp already in past — PyJWT decode() uses its C extension internal time, not the Python time module; monkeypatching time.time in the test has no effect on PyJWT's expiry check; minting a token with exp=now-10 is the correct pattern
- [Phase 09-authentication-foundation Plan 02]: lockout test helpers use _get_redis() with graceful pytest.skip rather than a required fixture — keeps lockout tests runnable in CI without Redis availability
- [Phase 09-authentication-foundation Plan 03]: Phase 8 tests/unit/infra/test_auth_middleware.py updated — EXEMPT_PATHS assertion updated from 3 to 8 paths (Plan 03 extends set per CONTEXT.md), "Authentication required" stub response updated to "invalid_token" (Phase 9 real middleware response)
- [Phase 09-authentication-foundation Plan 03]: Auth router uses single-file pattern for Tasks 2+3 (all 7 endpoints in auth.py including OIDC) — avoids module split, keeps router prefix/tag coherent
- [Phase 09-authentication-foundation Plan 03]: _redis_client() is a module-level helper in routers/auth.py (not FastAPI Depends) — allows integration tests to monkeypatch it without dependency injection overhead
- [Phase 09-authentication-foundation Plan 04]: _patch_auth(monkeypatch) pattern: monkeypatches _get_cached_token_version (returns 0) and _is_jti_revoked (returns False) in app.middleware.auth for integration tests that need AUTH_ENABLED=True role-gate validation without live DB/Redis; JWT signature still validated by PyJWT
- [Phase 09-authentication-foundation Plan 04]: test_patch_user_not_found_returns_404 and test_unlock_user_not_found_returns_404 require db_session — asyncpg connection attempted before 404 path reached; without DB returns 500 not 404
- [Phase 09-authentication-foundation Plan 04]: _normalise_admin_dashboards applied at both create and PATCH — called after body.role is applied so promoting to Admin forces dashboard_roles=[red,blue] even when dashboard_roles not explicitly in PATCH body
- [Phase 09-authentication-foundation Plan 05]: dashboard_roles: list[str]|None replaces role: str|None across build_events_query, build_fts_query, _visibility_ok, traverse_graph — empty list [] treated as unauthenticated (pass-through) same as None
- [Phase 09-authentication-foundation Plan 05]: ASGI scope dict injection (scope["state"]["user"] = user_obj) chosen over BaseHTTPMiddleware for integration test user injection — avoids async closure capture issues in Starlette's BaseHTTPMiddleware
- [Phase 09-authentication-foundation Plan 05]: mock.patch("app.routers.events.build_events_query") not "app.services.events_query.build_events_query" — router uses direct import binding, must patch router module namespace
- [Phase 09-authentication-foundation Plan 05]: webhook_dispatcher.py was also a call site for build_events_query(params, role=None) — updated to dashboard_roles=None as auto-fix (Rule 2 — would break at runtime)
- [Phase 09-authentication-foundation]: JWT_SIGNING_KEY uses failfast :? docker-compose syntax — startup aborts if unset; Authentik services gated behind profiles:[sso] for opt-in SSO; Redis AOF appendfsync everysec limits JTI blocklist data-loss to ≤1s
- [Phase 09-authentication-foundation Plan 07]: Setup token input field added to /setup page — operator pastes SETUP_TOKEN into form; UI sends X-Setup-Token header; avoids CLI-only workaround path
- [Phase 09-authentication-foundation Plan 07]: Lockout error propagated as signIn error string "lockout:{seconds}" from Credentials authorize() throw; login page parses and computes minutes = ceil(seconds/60)
- [Phase 09-authentication-foundation]: SessionProvider wrapped via thin providers.tsx client wrapper — root layout is async server component
- [Phase 09-authentication-foundation]: useSession + next-auth/react mocked globally in vitest.setup.ts to prevent SessionProvider requirement in all TopNav tests
- [Phase 10-projects-foundation]: Four-statement backfill pattern (INSERT sentinel / ADD COLUMN NOT NULL DEFAULT / ADD CONSTRAINT FK / DROP DEFAULT) — FK must be split on TimescaleDB 2.26 columnstore hypertables
- [Phase 10-projects-foundation]: postgresql.ENUM(create_type=False) is the correct SA2 pattern for pre-DO-block-created enums; sa.Enum emits redundant CREATE TYPE even with create_type=False
- [Phase 10-projects-foundation]: LEGACY_PROJECT_ID uuid.UUID exported from app.models.projects for downstream test/router reference
- [Phase 10-projects-foundation]: user_sub TEXT on project_memberships (no FK to users) — Authentik is sole user store; JWT claim hydration joins via sub
- [Phase 10-projects-foundation]: No server_default on project_id in extended ORMs — ORM-level M-6 enforcement matches DB-level DROP DEFAULT
- [Phase 10-projects-foundation]: pm claim shape is list-of-lists ([[pid_str, rank_int], ...]); list-of-dicts rejected — 30% smaller and trivial middleware parse
- [Phase 10-projects-foundation]: PM_CUTOFF=50 budget confirmed — 50-membership access token measured at 3225 bytes (under 4KB claim budget, 8KB header limit)
- [Phase 10-projects-foundation]: pm + pm_truncated NOT added to decode_token required-claims list — preserves Phase 9-minted tokens in 7-day refresh TTL circulation
- [Phase 10-projects-foundation]: Global Admin bypass in require_project_membership short-circuits BEFORE dict lookup — CONTEXT.md strong default locked
- [Phase 10-projects-foundation]: _issue_tokens_and_cookie takes db as required positional arg — eliminates pm-less-token silent emission; 0 bare mint_access_token/mint_refresh_token calls remain in auth.py
- [Phase 10-projects-foundation]: Subprocess alembic pattern in phase10 conftest db_engine — direct alembic.command.upgrade() inside pytest-asyncio fixture collides with env.py asyncio.run() call
- [Phase 10-projects-foundation]: Per-test fresh async engine + TRUNCATE users/projects cleanup — module-scoped engines leak Future across loops; committed fixtures need explicit reset between tests
- [Phase 10-projects-foundation]: Plan 10-05: Router pre-computes scope_predicate + bound_sources and passes into sync build_events_query — preserves Phase 9 sync contract; apply_project_filter_to_stmt remains as async composer for 10-07
- [Phase 10-projects-foundation]: Plan 10-05: Scope-intersection uses jsonb_path_query_array + regex substring over STIX patterns — enrichment.py does NOT denormalise indicators; MEDIUM confidence per RESEARCH.md, Phase 11 may refactor
- [Phase 10-projects-foundation]: Plan 10-05: _wrap_not helper — SA2 TextClause._negate asserts; De Morgan rewrite with explicit 'NOT (...)' text wrap preserving bindparams required for exclude-subtracts semantics
- [Phase 10-projects-foundation]: Plan 10-05: H-3 closure — Layer 3 graph BFS re-applies Event.project_id filter on cross-event JOIN (never via AGE node properties); seed-only guard would leak cross-project events sharing a technique_id
- [Phase 10-projects-foundation]: 11 endpoints in backend/app/routers/projects.py — 7 project-scope + 4 membership-nested — single-file router with shared _legacy_guard + _assert_not_last_lead helpers
- [Phase 10-projects-foundation]: Atomic auto-Lead bootstrap: db.flush project INSERT + add ProjectMembership(Lead) + single db.commit; IntegrityError rollback on either side prevents orphan projects-without-Lead
- [Phase 10-projects-foundation]: Last-Lead protection enforced inside router handlers (not auth dep) — Admin bypass of require_project_membership does NOT bypass the last-Lead invariant; 409 still triggers for Admin-driven demote/delete of sole Lead
- [Phase 10-projects-foundation]: Test pattern: AsyncClient + ASGITransport + app.dependency_overrides[get_session] on same engine as db_session fixture; monkeypatch _get_cached_token_version + _is_jti_revoked to bypass Redis in integration tests
- [Phase 10-projects-foundation]: Plan 10-04: Per-scope-type validators (CIDR/FQDN/AS/cert-hash) dispatched in validate_scope_row_value with UI-SPEC error copy byte-exact; ValueError surfaces as 422 detail unchanged
- [Phase 10-projects-foundation]: Plan 10-04: project_sources PUT uses delete-all + insert-all in single db.commit (atomic-replace); unknown source_id FK violation translated to 422 unknown_source_id
- [Phase 10-projects-foundation]: Plan 10-04: FQDN regex is ASCII-only — punycode-encoded IDNs accepted, raw unicode rejected; IPv6 CIDR round-trips cleanly through ipaddress.ip_network; IDN transparent input deferred to v2.1 via idna.encode() pre-processing if needed
- [Phase 10-projects-foundation]: Plan 10-04: ProjectSourceResponse Pydantic DTO kept router-local (not in app/schemas/projects.py) — it is a hydrated JOIN read-model, not a domain entity; writes use existing ProjectSourcesBinding schema
- [Phase 10-projects-foundation]: Plan 10-07: Sibling compare_router at prefix='/projects/compare' registered BEFORE projects_router in main.py — framework-level route-collision fix (not registration-order convention) for /{project_id} collision avoidance
- [Phase 10-projects-foundation]: Plan 10-07: IOC extraction moved to Python regex over scope-guarded raw_stix rows — three SA2 async jsonb_path_query_array compile paths failed (varchar-binding, TextClause.label NotImplementedError, literal_column bindparam substitution). Python path preserves scope-predicate symmetry and fits within COMPARE_CAP=500
- [Phase 10-projects-foundation]: Plan 10-07: Router reads caps via module-reference (_project_export.STIX_BUNDLE_EVENT_CAP) not imported bound names — makes monkeypatch-in-test observable at request time. Mirrors Phase 9 'mock.patch router module namespace' pattern
- [Phase 10-projects-foundation]: Plan 10-08: /projects list shell uses hand-written typed helpers in web/app/projects/lib/api.ts as interim source of truth while api-client.generated.ts regen is deferred (backend unreachable at execution time); swap to generated types when compose stack is online
- [Phase 10-projects-foundation]: Plan 10-08: exportProject returns {blob, filename} with filename parsed from Content-Disposition via parseContentDispositionFilename helper (iter-1 lock); NO client-side slug() helper — backend is sole source of truth for intellibird-project-<slug>-<date>.<ext> convention
- [Phase 10-projects-foundation]: Plan 10-08: Legacy sentinel row rendered at bottom of ProjectTable (not interspersed) with muted bg + LegacyBadge + tooltip + no edit/archive actions; ProjectsClient.handleRowClick no-ops on LEGACY_PROJECT_ID as defence-in-depth even though ProjectTable already omits onClick for that row
- [Phase 10-projects-foundation]: Plan 10-09: Fade-edge overflow indicators on ProjectTabs use onScroll + ResizeObserver, NOT IntersectionObserver — IO fires only on threshold crossings which produces visible snap-pops on fade opacity; onScroll fires per-pixel so the boolean edge state flips cleanly. ResizeObserver catches container-width changes that window.resize misses. Matches Phase 5 Plan 02 DashboardShell precedent.
- [Phase 10-projects-foundation]: Plan 10-09: useSearchParams Suspense boundary satisfied automatically — parent layout.tsx is async server component, so Next.js 15 wraps the client subtree (ProjectBreadcrumb + ProjectTabs) without explicit <Suspense>. Differs from Phase 5 Plan 02 where DashboardShell needed explicit Suspense because DashboardShell itself was a client component.
- [Phase 10-projects-foundation]: Plan 10-09: Tab-change routing split — router.replace for 11 query-param tabs (?tab=scope-keyword...?tab=settings) prevents history-pile-up on rapid clicks; router.push for Intel + Graph nested routes (expected back-button returns to prior tab).
- [Phase 10-projects-foundation]: Plan 10-09: Overview default strips ?tab= from URL (not ?tab=overview) — cleaner URL + matches the default-render contract (layout renders page.tsx when no query param present). ProjectBreadcrumb handles the empty case via `sp.get("tab") ?? "overview"`.
- [Phase 10-projects-foundation]: Plan 10-09: Breadcrumb section derivation pathname-first — /intel + /graph suffix checks precede ?tab= lookup so nested routes show the correct label even with stale tab param.
- [Phase 10-projects-foundation]: Plan 10-09: Signal amber applied ONLY as active-tab underline on ProjectTabs (data-[state=active]:border-[var(--brand-signal)]) — a selection indicator, not a CTA; UI-SPEC §Color §Accent reserved-for contract preserved (TIBER trim + primary CTAs only).
- [Phase 10-projects-foundation]: Plan 10-13: CompareTable is generic (CompareTable<T>) — CompareTable<string> for actors/techniques and CompareTable<SharedIOC> for IOCs; renderRow delegate keeps the table agnostic. Phase 11 4th panel (shared CVEs, shared domains) reuses cleanly
- [Phase 10-projects-foundation]: Plan 10-13: /projects/compare picker options filter out archived projects — _legacy sentinel hidden from Selects but backend require_project_membership is canonical gate (deep-link still works for operators with access)
- [Phase 10-projects-foundation]: Plan 10-13: middleware.ts matcher extension is session-only gate for /projects/:path* — no matcher-level per-project role gates (would duplicate backend require_project_membership and need membership fetch in middleware)
- [Phase 10-projects-foundation]: Plan 10-13: useEffect cancel-flag (closure cancelled bool) on compareProjects fetch — protects against rapid picker changes race-stomping newer results; standard React-fetch discipline mirroring EventsClient
- [Phase 10-projects-foundation]: Plan 10-12: project_id intentionally NOT serialised to URL query string — pinning lives in the /projects/[id]/intel route segment, not the query string; EventsClient.buildSearchParams omits project_id deliberately to prevent misleading bookmarkable URLs
- [Phase 10-projects-foundation]: Plan 10-12: basePath prop threading replaces hardcoded '/events' in every EventsClient router.replace — single derivation point flows to all URL mutations + EventDetailDrawer.closeDrawer so project-pinned navigation never jumps back to /events
- [Phase 10-projects-foundation]: Plan 10-12: /projects/[id]/graph ships as empty-state landing with CTA to /intel (full project-level forced-layout graph view deferred to v2.1) — AttackGraph is event-seeded, exposing a seed picker on /graph would duplicate /intel events list
- [Phase 10-projects-foundation]: Plan 10-12: EventDetailDrawer threads projectId down to nested AttackGraph automatically — drawer-opened graph is project-scoped transparently when operator drills in from /projects/[id]/intel, no separate drawer logic
- [Phase 10-projects-foundation]: Plan 10-11: ExportDialog destructures { blob, filename } from exportProject — NO client-side slug() helper. Iter-1 lock from plan 10-08 preserved; grep-confirmed 'slug' word appears only in documentation comments (6 hits, 0 callable). Backend is sole source of truth for filename.
- [Phase 10-projects-foundation]: Plan 10-11: Last-Lead UI pre-empt in MembershipTable (disabled={isLastLead} + title tooltip 'Cannot remove the last Lead; promote another member first.') — backend 409 cannot_remove_last_lead remains authoritative; UI gate is cosmetic. If another client adds a Lead between render and click, backend returns 200 and table reloads.
- [Phase 10-projects-foundation]: Plan 10-11: ProjectSourcesBinding uses dirty-state Save guard (savedRef Set vs checked Set, setsEqual derivation) — button disabled + label switches to 'Saved' when clean. Prevents no-op PUT round-trips and surfaces visible save confirmation.
- [Phase 10-projects-foundation]: Plan 10-11: Observer client-side Export button hide deferred to v2.1 — Phase 10 simplification shows button always; backend 403 catches Observers and ExportDialog maps 403 to distinct toast 'You do not have permission to export this project.' Full hide requires a project-role context provider reading JWT pm claim; landing that is a cross-cutting concern.
- [Phase 10-projects-foundation]: Plan 10-10: Client-side scope validators (scope-validators.ts) mirror backend scope_validators.py error copy byte-exact — UI-SPEC §Error states locks strings as canonical. CIDR validator is coarse-shape (addr/prefix + IPv4 octet range + prefix<=32) because browsers have no ipaddress stdlib equivalent; backend remains canonical parser for host-bit normalisation + IPv6 validation. 20/20 smoke-test cases pass including 6 plan truth cases.
- [Phase 10-projects-foundation]: Plan 10-10: ScopeRowTable toggles (exclude/active_test/intel) rendered DISABLED in Phase 10 — plan §action explicit scope-reduction ('toggle-disabled approach keeps this plan small; full inline PATCH on toggle change is a v2.1 follow-up'). Edit path is delete+re-add. Truth #5 of must-have truths is thus a known deferred item, not a regression. No patchScopeRow helper added to lib/api.ts for 10-10.
- [Phase 10-projects-foundation]: Plan 10-10: page.tsx → ProjectDetailClient indirection — page.tsx stays a server component (Next.js de-dupes project fetch against layout.tsx's fetch), ProjectDetailClient owns the useSearchParams ?tab= dispatch. Direct useSearchParams in page.tsx would collapse to client component and force Suspense workaround; pattern matches plan 10-09's useSearchParams-Suspense-satisfied-by-async-server-component-layout precedent.
- [Phase 10-projects-foundation]: Plan 10-10: ScopeRowDialog uses two-channel error display — zod errors (required/max-length + both-flags-off refine with path=['intel_scope']) via form.formState.errors, per-type value errors (CIDR/FQDN/AS/cert) via manual valueError useState. Runtime scopeType→validator dispatch cannot be expressed as a zod schema without N discriminated unions.
- [Phase 10-projects-foundation]: Plan 10-10: SettingsTabContent TIBER banner driven by local engagementType state (not project.engagement_type prop) — banner appears/disappears LIVE as the Select changes before clicking Save, communicating the about-to-change-gate relationship. Signal-amber border-left-4 per UI-SPEC §Color §Semantic surfaces. Save button disabled via dirty-state gate prevents wasteful PATCH round-trips; Archive toggle stays independent of dirty-state.
- [Phase 11-easm-via-bbot]: easm-worker mounts /var/run/docker.sock in isolation — no other service has this elevated-privilege mount (PITFALLS §Pitfall 7)
- [Phase 11-easm-via-bbot]: bbot_scans declared as Docker named volume (not bind-mount); profiles:[easm] left commented so service starts by default
- [Phase 11-easm-via-bbot]: easm_findings is a regular PG table NOT a TimescaleDB hypertable (H-4: no time-series benefit, adds overhead)
- [Phase 11-easm-via-bbot]: events.easm_scan_id uses ON DELETE SET NULL (L-4): promoted findings survive scan deletion
- [Phase 11-easm-via-bbot]: project_easm_credentials shipped in migration 010 — low schema cost now, high ALTER cost if deferred
- [Phase 11-easm-via-bbot]: BBOT 2.8.4 module names confirmed live: crt (not crt.sh), subdomaincenter (not sublist3r); BBOT_STABLE_PASSIVE_MODULES frozen at 14 modules; otx requires API key (correction from research doc)
- [Phase 11-easm-via-bbot]: source_type='bbot' in promote_finding_to_event dict is metadata for callers; events has no source_type column; BBOT provenance carried by easm_scan_id (non-NULL = BBOT-promoted); callers pop 'source_type' before Event(**kwargs)
- [Phase 11-easm-via-bbot]: Legacy+archived guards checked before authority check to prevent membership probing via 403 vs 422 distinction (C-3 gate)
- [Phase 11-easm-via-bbot]: active_auth_confirmed_by added to ProjectResponse schema (was in ORM but not schema) for confirmer display in plan 11-10 gate form
- [Phase 11-easm-via-bbot]: 14-module BBOT_STABLE_PASSIVE_MODULES frozenset — copied from bbot-module-verification.md live verification; sublist3r absent, crt not crt.sh, subdomaincenter not subdomains
- [Phase 11-easm-via-bbot]: intel_scope NOT referenced in derive_bbot_seeds / derive_bbot_blacklist — CONTEXT.md active_test_scope-sole-gate lock honoured
- [Phase 11-easm-via-bbot]: SQLite+aiosqlite for scope unit tests: scope_table.create() (not Base.metadata.create_all) + import app.models.easm to resolve Project relationship + explicit created_at for now() server_default bypass
- [Phase 11-easm-via-bbot]: content_hash=sha256(project_id||bbot_event_type||canonical_target) — NO scan_id, NO timestamp (M-4); cross-scan dedup key is (project_id, bbot_event_type, canonical_target)
- [Phase 11-easm-via-bbot]: docker run -d for detached launch; container_id stored in DB before stream_bbot_logs() call so cancellation path has id available regardless of streaming state
- [Phase 11-easm-via-bbot]: run_bbot_scan actor: max_retries=0; semaphore-exceeded raises dramatiq.Retry(delay=30_000) explicitly; finally block guarantees semaphore release
- [Phase 11-easm-via-bbot]: source_type='bbot' popped from promote_finding_to_event kwargs before Event(**kwargs); summary remapped to description — events table has no source_type column
- [Phase 11-easm-via-bbot]: easm_scan_id IS NULL used as BBOT-provenance filter in /api/events (events table has no source_type column)
- [Phase 11-easm-via-bbot]: Diff match key = (bbot_event_type, canonical_target) only — module/severity not in diff key per EASM-08
- [Phase 11-easm-via-bbot]: 8-column FindingsTable (Type/Target/Module/Severity/FirstSeen/LastSeen/Status/Actions) per UI-SPEC §Surface 3 verbatim; 24h banner fires when active_scans_authorised=true AND now-active_auth_confirmed_at>6d; Observer Select disabled with tooltip 'Observers cannot modify finding status.'; LaunchScanDialogPlaceholder import-swap approach for plan 11-09; api.ts launchScan Error.status for HTTP-code discrimination
- [Phase 11-easm-via-bbot]: Badge render lives in EventsTable.tsx not EventsClient.tsx — EventsTable owns all per-row HTML; EventsClient is filter/state orchestrator only
- [Phase 11-easm-via-bbot]: FeedType | 'bbot' union extension added to api-client.ts locally to unblock TypeScript comparison without backend being reachable for regen
- [Phase 11-easm-via-bbot]: EASM tab active detection uses pathname.includes('/easm') not pathname.endsWith — covers all /projects/[id]/easm* nested routes
- [Phase 11-easm-via-bbot]: DiffView lazy-loaded via diffActivated boolean gate — getScanDiff not called until diff tab first selected
- [Phase 11-easm-via-bbot]: EASMGatePreview.tsx converted to re-export shim rather than deleted — backward compat with any stray imports
- [Phase 11-easm-via-bbot]: SettingsTabContent authority resolution via useSession global role + listMemberships project Lead check; defaults to false (secure)
- [Phase 11-easm-via-bbot]: liveProject local state in SettingsTabContent for in-place gate refresh without full page reload
- [Phase 12-brand-protection]: brand_matches.event_id is a soft UUID (no FK) — events is a TimescaleDB hypertable, cannot be FK target; app enforces integrity (attack_technique_tags precedent)
- [Phase 12-brand-protection]: Case-insensitive UNIQUE on brand_terms implemented as functional index on lower(value) — plain UniqueConstraint cannot carry expressions
- [Phase 12-brand-protection]: Plan 12-00: dnstwist JSON key naming locked (version 20250130): canonical key `domain` (NOT domain-name/domain_name); DNS records snake_case dns_a/dns_aaaa/dns_mx/dns_ns; no hyphen variants; lookup_success derived by parser from !ServFail check on dns_a/dns_ns; whois_* keys absent (--whois flag not passed). Evidence: docs/research/dnstwist-key-verification.md. Unblocks plan 12-02 parser.
- [Phase 12-brand-protection]: Phase 12 Plan 02: DEFAULT_STOPLIST locked at 224 frozen entries (exceeds ~150 target); is_stoplisted strips+lowercases before match; brand_severity raises ValueError on unknown match_source; crtsh_client uses httpx params= for %→%25 URL-encoding; dnstwist parser retains defensive hyphen/underscore key fallbacks + !ServFail+empty-string no-data sentinels; test modules bootstrap Settings via os.environ.setdefault (precedent: tests/unit/easm).
- [Phase 12-brand-protection Plan 07]: dnstwist install surface is `backend/pyproject.toml` + `uv sync --no-dev --locked` (NOT a separate `RUN pip install` line in api.Dockerfile and NOT a `requirements.txt` — neither exists as a convention in this repo). Regression test accepts pyproject.toml as a valid install surface.
- [Phase 12-brand-protection Plan 07]: brand-monitor queue co-located on the shared `worker` service (docker-compose.yml line 82) alongside ingest/maintenance/webhooks; NOT on easm-worker (dnstwist needs no docker.sock — keeping the sock-blast-radius narrow). Negative invariant guarded by `test_brand_monitor_queue_not_on_easm_worker`.
- [Phase 12-brand-protection Plan 07]: Compose regression test in `backend/tests/integration/test_compose_brand_queue.py` normalises both shell-string and YAML-list `command:` forms via `_cmd_tokens()` helper — future refactor between the two styles cannot silently drop the brand-monitor queue.
- [Phase 12-brand-protection]: Plan 12-11: docs/ops/brand.md mirrors Phase 11 docs/ops/easm.md H2 layout (Overview / Env / subsystem sections / Troubleshooting / Deferred / Cross-Refs) — structural consistency across subsystem runbooks outweighs bespoke per-subsystem layout. Operators navigate both runbooks with same mental model.
- [Phase 12-brand-protection]: Plan 12-11: dnstwist upgrade procedure documented as uv-first (pyproject.toml pin bump + uv lock --upgrade-package dnstwist + docker compose build api + bounce worker+scheduler) NOT pip install --upgrade. Aligns with 12-07 repo-convention lock; naive pip inside container would bypass uv.lock.
- [Phase 12-brand-protection]: Plan 12-11: Runbook explicitly contrasts Brand (in-process dnstwist, no docker.sock, co-located on shared worker) with Phase 11 EASM (docker.sock mount, dedicated easm-worker). Names the 'consolidate onto easm-worker for node efficiency' anti-pattern and cites test_brand_monitor_queue_not_on_easm_worker as the regression guard.
- [Phase 12-brand-protection]: Dropped source_type from brand_monitor INSERT + brand_synth event dict (deferred-items.md Option 1); also fixed ON CONFLICT target to (source_id, content_hash, observed_at) to match hypertable unique index. No schema migration; tag-based provenance preserved.

### Roadmap Evolution

- Phase 12.1 inserted after Phase 12: Project Asset Surface from BBOT scan findings (URGENT) — auto-populate project-level asset inventory (IP/ASN/DNS/WHOIS/Cert/Port/Geo/Identity) from BBOT scan outputs; filterable + visualized under Project Settings → Assets sub-tab.

### Pending Todos

- Operator review of v2.0 ROADMAP.md (phases 8-13) before Phase 8 planning
- Phase 9 requires `/gsd:plan-phase 9 --research` (Authentik OIDC + Auth.js v5 integration)
- Phase 11 requires `/gsd:plan-phase 11 --research` (BBOT subprocess cancellation + timeout semantics)
- Phase 10 planning should include a compressed-hypertable migration dry-run spike against a snapshot with ≥1 compressed chunk

### Blockers/Concerns

- Phase 1: RESOLVED — Port conflict with Mythic C2 handled by stopping `mythic_postgres` + `mythic_react` containers before bringing up the IntelliBird stack. Operator must repeat this workaround or remap host ports if both stacks needed simultaneously.
- Phase 1: AGE co-installation on timescale/timescaledb:latest-pg16 is CONFIRMED WORKING — db.Dockerfile build succeeds after adding clang19 Alpine package.
- Phase 1: TimescaleDB hypertable constraint — events PK is composite `(id, observed_at)`; FKs cannot target hypertable rows, so `attack_technique_tags.event_id` has no FK constraint. App-level integrity required for any future event-referencing table. (v2.0 reinforces: `easm_findings.event_id` and `brand_matches.event_id` follow same no-FK pattern.)
- Phase 1: Working tree uncommitted per operator directive. Operator handles all git staging/commits for Phase 1 artifacts.
- Phase 2: RESOLVED — TAXII compatibility spike complete (TAXII-SPIKE.md). MITRE CTI via TAXII 2.1 confirmed. OTX TAXII 1.1 hand-rolled poller implemented (scope-C). CIRCL unreachable, deferred to M2.
- Phase 5: Decide MapLibre vector tile source (Protomaps or OpenFreeMap) at the start of Phase 5 — the geo map cannot render without one
- v2.0 Phase 8: Must precede Phase 9 — skipping risks C-1 (SECRET_KEY rotation silently corrupts `sources.credentials_enc`) and H-1 (Route Handler proxy silently bypasses auth) firing during auth bring-up
- v2.0 Phase 10: Migration 007 three-step backfill must be tested against a database snapshot containing ≥1 compressed TimescaleDB chunk before production rollout (C-4)
- v2.0 Phase 11: BBOT MUST NEVER be pip-installed into API/worker image — BBOT issue #2354 (daemonic-process crash) has no upstream fix; dedicated `easm-worker` container via Docker subprocess is the only supported path (C-5)
- v2.0 Phase 11: `/var/run/docker.sock` mount on `easm-worker` is an elevated-privilege requirement and must be documented in `docs/ops/easm.md` before production deployment
- v2.0 Phase 13: PROJECT.md constraint "no production use without auth" means loopback-only binding removal (PROD-07) is the final gate for v2.0 tagging

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260423-wc7 | Fix webhook create: add project_id to WebhookCreate schema and route | 2026-04-23 | uncommitted (per user rule) | [260423-wc7-fix-webhook-create-add-project-id-to-web](./quick/260423-wc7-fix-webhook-create-add-project-id-to-web/) |
| 260423-wh7 | Invert checkbox fill: unchecked=dark bg, checked=primary | 2026-04-23 | uncommitted (per user rule) | [260423-wh7-invert-checkbox-fill-enabled-filled-disa](./quick/260423-wh7-invert-checkbox-fill-enabled-filled-disa/) |

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Auth | Local accounts + OIDC/SAML (Authentik) | v2.0 Phase 9 | v1.5 Initialisation |
| Storage | MinIO/S3 cold archive tier | M2+ | v1.5 Initialisation |
| Export | STIX 2.1 bundle, PDF/MD TTI reports, CSV/JSON | PRJ-07 (v2.0 Phase 10, defer-risk) | v1.5 Initialisation |
| AI | LLM summarisation via LiteLLM | M3 | v1.5 Initialisation |
| TIBER | TTI report generation and threat scenario builder | M3 | v1.5 Initialisation |
| v2.0 Descope | PRJ-06 cross-project compare | v2.1 candidate if milestone risk | 2026-04-18 roadmap |
| v2.0 Descope | PRJ-07 per-project STIX + CSV export | v2.1 candidate if milestone risk | 2026-04-18 roadmap |
| v2.0 Descope | EASM-08 scan history diff UI | v2.1 candidate if milestone risk | 2026-04-18 roadmap |
| v2.1 | CertStream realtime CT monitoring | v2.1 candidate | 2026-04-18 research |
| v2.1 | ML severity rerank | v2.1+ | 2026-04-18 research |

## Session Continuity

Last session: 2026-04-24T04:56:08.560Z
Stopped at: Completed 12-12-PLAN.md (BRP-05 source_type drift closure)
Resume file: None
Next: Run plan 10-10 (scope tab content + settings tab + EASMGatePreview). Parallel-safe candidate: plan 10-13 (compare page) touches disjoint files.

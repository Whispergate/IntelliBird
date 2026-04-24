# Roadmap: IntelliBird

## Milestones

- ✅ **v1.5 IntelliBird M1** — Phases 1-7 (shipped 2026-04-18) — see [milestones/v1.5-ROADMAP.md](milestones/v1.5-ROADMAP.md)
- 📋 **v2.0 IntelliBird M2 Engagement** — Phases 8-13 (planned 2026-04-18)

## Phases

<details>
<summary>✅ v1.5 IntelliBird M1 (Phases 1-7) — SHIPPED 2026-04-18</summary>

- [x] Phase 1: Foundation — Docker Compose + schema + ATT&CK bootstrap + secrets
- [x] Phase 2: Ingestion Pipeline — RSS + STIX/TAXII 2.1 (+ OTX 1.1 scope-C) + NVD
- [x] Phase 3: Source Registry & Retention — CRUD UI + encrypted creds + archiver
- [x] Phase 4: Query API & Archiver — filterable list + presets + FTS + graph endpoint + OpenAPI + structured logs
- [x] Phase 5: Dual Dashboard Shell — Red + Blue SPAs + top nav + event detail drawer
- [x] Phase 6: Combined Threat Visualisation — map drill-down + MaxMind geo + widget completion + ATT&CK provenance viz
- [x] Phase 7: Webhook Alerts — Slack Block Kit + Teams Power Automate + Discord embeds + Generic JSON

Total: 60 plans, operator-live-approved, 54/54 M1 requirements satisfied.

See [milestones/v1.5-ROADMAP.md](milestones/v1.5-ROADMAP.md) for full phase details and [milestones/v1.5-MILESTONE-AUDIT.md](milestones/v1.5-MILESTONE-AUDIT.md) for audit findings.

</details>

### 📋 v2.0 Milestone 2 Engagement (Planned)

v2.0 transforms IntelliBird from loopback-only lab tool into a production-grade engagement platform. Six phases follow a hard dependency chain — infrastructure hardening that unblocks the auth rollout, then Authentication (removes the loopback constraint), then Projects (introduces `project_id` scoping that every downstream artefact FKs to), then EASM via BBOT and Brand Protection in parallel, then production-readiness hardening that turns a deployable release into a production-safe one. Phase 8 is not one of PROJECT.md's four themes; it exists because blocker pitfalls C-1 (SECRET_KEY rotation corrupts `sources.credentials_enc`) and H-1 (Route Handler proxy silently bypasses auth during rollout) must be addressed before auth code is introduced.

**Phase Numbering:**
- Integer phases (1-13): Planned milestone work
- Decimal phases (e.g. 8.1): Urgent insertions (marked with INSERTED)

- [x] **Phase 8: Pre-Auth Infrastructure Hardening** - Credentials key versioning, rekey endpoint, startup decrypt check, `AUTH_ENABLED` flag, OpenAPI codegen (completed 2026-04-18)
- [ ] **Phase 9: Authentication Foundation** - Authentik OIDC + local Argon2 accounts + JWT access/refresh + AuthMiddleware + Auth.js v5 frontend
- [ ] **Phase 10: Projects Foundation** - Migration 007, `project_id` FK, scope tabs, per-project intel + graph, TimescaleDB three-step backfill
- [x] **Phase 11: EASM via BBOT** - Migration 010, `easm-worker` container, Docker subprocess, two-factor active-scan gate, dashboard (completed 2026-04-22)
- [x] **Phase 12: Brand Protection** - Migration 009, `brand_monitor` actor, crt.sh + dnstwist + pg_trgm, reuse M1 webhook pipeline (completed 2026-04-23)
- [ ] **Phase 13: Production Readiness Hardening** - Cross-project leakage tests, active-scan gate penetration test, SECRET_KEY drill, load test, Authentik recovery, public binding

## Phase Details

### Phase 8: Pre-Auth Infrastructure Hardening
**Goal**: SECRET_KEY rotation is reversible and observable, `AUTH_ENABLED` feature flag is wired end-to-end, and frontend/backend schema drift is prevented — so Phase 9 auth rollout cannot silently corrupt credentials or silently bypass authentication
**Depends on**: v1.5 M1 shipped (Phase 7 complete)
**Requirements**: INFRA-01, INFRA-02, INFRA-03, INFRA-04, INFRA-05, INFRA-06
**Pitfalls addressed**: C-1 (SECRET_KEY rotation silently corrupts `sources.credentials_enc`), H-1 (Route Handler proxy silently bypasses auth during rollout), M-2, L-1
**Success Criteria** (what must be TRUE):
  1. Every existing `sources.credentials_enc` row carries a `credentials_key_version` tag and operator running `POST /api/admin/rekey-credentials` (setup-token gated, pre-auth) re-encrypts every row under the current SECRET_KEY without any row becoming unreadable
  2. Backend startup runs a decrypt sanity check on a known ciphertext and logs CRITICAL + surfaces a UI banner when any encrypted row fails to decrypt under the current key
  3. Setting `AUTH_ENABLED=false` makes backend AuthMiddleware a pass-through and makes the Next.js Route Handler proxy skip token injection while keeping the existing NoAuthBanner visible — end-to-end flip of the flag requires no code change and no lingering unauthenticated paths when set to `true`
  4. `web/app/api-client.ts` is generated from the live OpenAPI schema via a checked-in codegen command, and a CI check fails when the committed client drifts from backend schema
  5. `docs/ops/secret-rotation.md` documents the rekey procedure, the consequences of skipping it, and the exact commands to run
**Plans**: 7 plans
  - [ ] 08-00-PLAN.md — Wave 0 test stubs + pnpm openapi:* script scaffolding
  - [ ] 08-01-PLAN.md — Settings fields + Migration 007 + app/state.py (INFRA-01)
  - [ ] 08-02-PLAN.md — POST /api/admin/rekey-credentials router (INFRA-02)
  - [ ] 08-03-PLAN.md — AuthMiddleware + lifespan canary + system.py + compose env (INFRA-03 + INFRA-04 backend)
  - [ ] 08-04-PLAN.md — openapi-typescript install + api-client.generated.ts + Makefile drift gate (INFRA-05)
  - [ ] 08-05-PLAN.md — NoAuthBanner three-state + Route Handler X-Dashboard-Role strip (INFRA-03 + INFRA-04 frontend)
  - [x] 08-06-PLAN.md — docs/ops/secret-rotation.md runbook (INFRA-06)
**UI hint**: minimal (NoAuthBanner variant, startup error banner)
**Research flag**: no — standard infra patterns

### Phase 9: Authentication Foundation
**Goal**: An operator logs in via Authentik OIDC or a local Argon2 account, receives a JWT access + refresh token flow with Redis JTI blocklist logout, and every router and every dashboard navigation is enforced by JWT claim — not by the spoofable `X-Dashboard-Role` header
**Depends on**: Phase 8 (AUTH_ENABLED flag + rekey infra must be live before auth code lands)
**Requirements**: AUTH-01, AUTH-02, AUTH-03, AUTH-04
**Pitfalls addressed**: C-2 (`X-Dashboard-Role` spoofed after auth lands), H-1 (via `AUTH_ENABLED`), H-7 (AUTH-before-PRJ ordering), M-1 (revocation), M-7 (lockout)
**Success Criteria** (what must be TRUE):
  1. Admin can create local user accounts with Argon2-hashed passwords via `POST /api/admin/users` (first-user bootstrap accepts an initial admin), and a separately configured Authentik OIDC SSO login lands SSO users as Viewer by default with groups-claim → role mapping when the admin configures claim-to-role rules
  2. Every `/api/admin/*` route rejects requests without a valid JWT with 401 and rejects non-Admin JWTs with 403; `events_query` and `graph_traversal` derive dashboard role exclusively from the JWT claim and ignore any `X-Dashboard-Role` header (header stripped at the proxy, integration test in Phase 13 enforces)
  3. JWT access tokens (15-min TTL) are paired with a refresh token (7-day TTL, httpOnly cookie); logging out inserts the access token's JTI into a Redis blocklist and the token is rejected on the next request; session survives browser refresh until refresh expiry
  4. `/red` and `/blue` route guards read the JWT claim via Auth.js v5 `middleware.ts`; `NoAuthBanner` renders only when `AUTH_ENABLED=false`; an authenticated Viewer who attempts `/red` (if their role grants Blue only) is redirected, not denied at API-only
**Plans**: 10 plans
  - [x] 09-00-PLAN.md — Wave 0 test stubs + conftest fixtures + frontend vitest stubs
  - [x] 09-01-PLAN.md — Settings JWT_SIGNING_KEY + SSO_* + Migration 008 + User ORM (AUTH-01/02/03)
  - [x] 09-02-PLAN.md — security/{jwt,passwords,lockout,oidc}.py primitives (AUTH-01/03/04)
  - [x] 09-03-PLAN.md — AuthMiddleware replace + auth router (login/refresh/logout/me/change-password/oidc) (AUTH-01/02/03)
  - [x] 09-04-PLAN.md — admin/setup + admin/users routers + schemas/users.py (AUTH-01/02)
  - [x] 09-05-PLAN.md — events_query + graph_traversal refactor: claim-driven dashboard_roles (AUTH-02/04 / C-2 closure)
  - [x] 09-06-PLAN.md — Compose Authentik profile + Redis AOF + api JWT/SSO env vars + .env.example (AUTH-01/03)
  - [x] 09-07-PLAN.md — Auth.js v5 + middleware.ts + (auth) group pages (login/setup/change-password) (AUTH-01/03/04)
  - [x] 09-08-PLAN.md — Proxy bearer inject + TopNav user menu + /admin/users page + dialogs (AUTH-01/02)
  - [x] 09-09-PLAN.md — docs/ops/auth-setup.md operator runbook (AUTH-01/03)
**UI hint**: yes (`/login`, user menu, role-aware navigation)
**Research flag**: YES — Authentik OIDC groups-claim → role mapping and Auth.js v5 Authentik provider config need deeper research. Use `/gsd:plan-phase 9 --research` to spike integration details before planning.

### Phase 10: Projects Foundation
**Goal**: Admin/Analyst create projects, populate AlphaStrike-style scope tabs across 7 scope types, and see a per-project intel view and attack graph that filter by scope intersection at query time (not ingest time) with no cross-project leakage
**Depends on**: Phase 9 (AuthMiddleware populates `request.state.user` for `Depends(require_admin_role)`; `projects.created_by` stores Authentik `sub` as TEXT with no local users table)
**Requirements**: PRJ-01, PRJ-02, PRJ-03, PRJ-04, PRJ-05, PRJ-06 (defer-risk — candidate for v2.1 if milestone pressure), PRJ-07 (defer-risk — candidate for v2.1 if milestone pressure)
**Pitfalls addressed**: C-4 (`project_id NOT NULL` on hypertable without backfill), H-2, H-3 (AGE graph `project_id` via JOIN-to-events, not via AGE node properties), M-6
**Success Criteria** (what must be TRUE):
  1. Admin or Analyst creates a project with name + engagement_type (red_team / tiber / bbest / internal / intel_only) + description, edits and archives it from `/projects`, and `projects.created_by` stores the Authentik `sub` as TEXT with no FK to a local users table
  2. Per-project scope tabs at `/projects/[id]` let the operator add, edit, and remove rows across 7 scope types (keyword, service, domain, certificate, whois, as_number, ip_range) with per-row contact + include/exclude + `active_test_scope` vs `intel_scope` toggle; `project_sources` binding restricts a project to specific source IDs for air-gapped TIBER exercises
  3. `/projects/[id]/intel` calls `events_query` with `project_id=X` and filters by scope-intersection at query time — CIDR `<<` for IP ranges, subdomain suffix match for domains, `tsvector @@` for keywords — returning zero events belonging to other projects regardless of how the filter is constructed
  4. `/projects/[id]/graph` renders the AGE attack graph scoped via JOIN-to-events on `project_id` (never via AGE node properties); Project A's graph BFS cannot surface a Project B event even when Project A and Project B share a technique tag
  5. Migration 007 adds nullable `project_id` FK to `events`, `filter_presets`, and `webhooks` via the three-step pattern (insert legacy sentinel project → ADD COLUMN with DEFAULT → ALTER SET NOT NULL where applicable) and completes cleanly against a database snapshot containing ≥1 compressed TimescaleDB chunk
**Plans**: 14 plans
  - [ ] 10-00-PLAN.md — Wave 0 test stubs + conftest fixtures + shadcn tabs primitive
  - [ ] 10-01-PLAN.md — Migration 009 + ORM models + Pydantic schemas + LEGACY_PROJECT_ID
  - [ ] 10-02-PLAN.md — JWT pm claim + require_project_membership dep + AuthMiddleware extension
  - [ ] 10-03-PLAN.md — /api/projects CRUD + memberships sub-routes (PRJ-01 + PRJ-05)
  - [ ] 10-04-PLAN.md — Scope rows + project_sources routers + validators (PRJ-02 + PRJ-05)
  - [ ] 10-05-PLAN.md — project_scope service + events_query/graph_traversal project_id kwarg (PRJ-03 + PRJ-04)
  - [ ] 10-06-PLAN.md — presets + webhooks require project_id on POST; membership-filtered GETs (M-6 closure)
  - [ ] 10-07-PLAN.md — project_export (STIX+CSV) + project_compare services + routers (PRJ-06 + PRJ-07)
  - [ ] 10-08-PLAN.md — Frontend /projects list + ProjectsClient + api-client regen
  - [x] 10-09-PLAN.md — Frontend /projects/[id] layout + ProjectTabs (13-strip) + Overview tab
  - [x] 10-10-PLAN.md — Scope tab content (7 variants) + Settings tab + EASMGatePreview
  - [ ] 10-11-PLAN.md — Memberships tab + Sources binding tab + ExportDialog
  - [ ] 10-12-PLAN.md — EventsClient + AttackGraph projectId prop; /projects/[id]/intel + /graph routes
  - [ ] 10-13-PLAN.md — /projects/compare page + middleware.ts extension + docs/ops/projects.md runbook
**UI hint**: yes (`/projects`, `/projects/[id]`, `/projects/[id]/intel`, `/projects/[id]/graph`, scope tabs)
**Research flag**: no — one targeted spike (compressed-hypertable migration dry-run against snapshot with compressed chunk) runs inside Phase 10 planning; no pre-planning research needed

### Phase 11: EASM via BBOT
**Goal**: An Analyst launches a passive-by-default BBOT scan for a project, watches findings stream into the EASM dashboard, and — only after typing a scope-acknowledgement phrase and flipping the project's active-scan authorisation flag — can launch an active scan; BBOT runs only inside a dedicated `easm-worker` container via Docker subprocess, never inside the API/worker image
**Depends on**: Phase 10 (`projects.active_scans_authorised` + `scope_acknowledgement_text` + `active_auth_confirmed_at` columns must pre-exist from migration 009; `project_id` FK required by migration 010)
**Parallel-safe with**: Phase 12 (disjoint migration, router, queue, frontend)
**Requirements**: EASM-01, EASM-02, EASM-03, EASM-04, EASM-05, EASM-06, EASM-07, EASM-08 (user elected to ship — not deferred), EASM-09, EASM-10
**Pitfalls addressed**: C-3 (BBOT active scan without written acknowledgement = CFAA / CMA liability), C-5 (BBOT daemonic-process crash in Dramatiq worker, issue #2354), H-4, M-3, M-4, L-2, L-4
**Success Criteria** (what must be TRUE):
  1. A dedicated `easm-worker` Compose service runs BBOT 2.8.4 via `docker run blacklanternsecurity/bbot:stable` as a subprocess on a dedicated Dramatiq `easm` queue — BBOT is never pip-installed into the API or worker image, and attempting to run a scan with `docker.sock` unavailable fails with a clear error rather than crashing
  2. Launching a passive scan from `/projects/[id]/easm` triggers `run_bbot_scan` with `-rf passive` enforced programmatically in the worker (no UI path can flip it); findings stream stdout JSON into `easm_findings` with ON CONFLICT DO UPDATE dedup on (project_id, bbot_event_type, canonical_target) and appear in the dashboard within seconds
  3. Launching an active scan fails with 403 unless all three gate fields are set server-side: `projects.active_scans_authorised=true`, a typed `scope_acknowledgement_text` phrase matching the project's scope, and an `active_auth_confirmed_at` timestamp within the authorisation window — direct curl bypass of the UI is blocked (integration test in Phase 13)
  4. Calling the scan endpoint with an experimental/aggressive BBOT module returns 422 referencing the stable-tier safelist; safelist lives in the backend and is the only source of truth
  5. High-confidence finding types (`FINDING`+HIGH, `VULNERABILITY`, `SUBDOMAIN_TAKEOVER_CANDIDATE`, `TECHNOLOGY`) are promoted to canonical `events` via an explicit allowlist and are visible in the standard events feed; low-confidence findings stay in `easm_findings` only and do not pollute the main intel view
  6. A Redis semaphore `bbot:concurrent_scans` (default 2, env-configurable) caps concurrent scans per worker host; launching a 3rd scan while 2 are running enqueues rather than starting immediately
  7. EASM container isolation uses a dedicated `bbot_scans` volume, and `docs/ops/easm.md` documents the `/var/run/docker.sock` mount as an elevated-privilege requirement including threat-model implications
**Plans**: 14 plans
  - [ ] 11-00-PLAN.md — Wave 0 test stubs + NDJSON fixtures + BBOT module safelist live verification checkpoint
  - [ ] 11-01-PLAN.md — Migration 010 + ORM models + Pydantic schemas + api-client regen (EASM-01/02/04/06/10 schema)
  - [ ] 11-02-PLAN.md — bbot_safelist.py frozen set + easm_scope.py seed derivation + BBOT settings + .env.example (EASM-03/05)
  - [ ] 11-03-PLAN.md — easm_promoter.py allowlist + STIX SDO mapping + L-4 ON DELETE SET NULL integration test (EASM-06/10)
  - [ ] 11-04a-PLAN.md — bbot_runner.py subprocess + semaphore + reaper + persist primitives + unit tests (EASM-01/02/03/09)
  - [ ] 11-04b-PLAN.md — Dramatiq actor on queue='easm' + scheduler jobs (cleanup + dismiss + orphan reaper) + actor integration tests (EASM-02/06/09/10)
  - [ ] 11-05-PLAN.md — backend routers/easm.py (9 endpoints) + /api/events include_bbot filter (EASM-02/05/06/07/08/09)
  - [ ] 11-06-PLAN.md — PATCH + DELETE /api/projects/{id}/easm-gate gate flip/revoke on projects router (EASM-04 / C-3)
  - [ ] 11-07-PLAN.md — ops/docker-compose.yml easm-worker service + bbot_scans volume + compose regression test (EASM-01/10)
  - [ ] 11-08-PLAN.md — Frontend /projects/[id]/easm dashboard + FindingsTable + FindingsFilterBar + lib/api.ts (EASM-07)
  - [ ] 11-09-PLAN.md — Frontend ScanLaunchDialog + scan history list + scan detail + DiffView (EASM-02/05/07/08)
  - [ ] 11-10-PLAN.md — Frontend EASMGateForm live (replaces EASMGatePreview) + SettingsTabContent wiring + 24h banner (EASM-04)
  - [ ] 11-11-PLAN.md — ProjectTabs EASM tab addition + EventsClient include_bbot Switch + BBOT provenance badge + api-client regen (EASM-06/07)
  - [ ] 11-12-PLAN.md — docs/ops/easm.md operator runbook (safelist + docker.sock threat model + retention + upgrade + disaster recovery) (EASM-01/10)
**UI hint**: yes (`/projects/[id]/easm`, `/projects/[id]/easm/scans`, `/projects/[id]/easm/scans/[scanId]`, active-scan gate form, findings table, scan history, diff view)
**Research flag**: YES — completed. See `.planning/phases/11-easm-via-bbot/11-RESEARCH.md` for BBOT subprocess plumbing, container_id capture, orphan reaper, safelist validation, docker.sock threat model.

### Phase 12: Brand Protection
**Goal**: An Analyst defines brand terms per project, the `brand_monitor` actor scans ingested events + crt.sh CT logs + dnstwist lookalikes every 15 minutes, HIGH-severity matches synthesise a canonical event that the existing M1 webhook pipeline delivers — with zero new webhook code
**Depends on**: Phase 10 (migration 009 FKs `projects.id`)
**Parallel-safe with**: Phase 11 (different tables, actor, queue, frontend)
**Requirements**: BRP-01, BRP-02, BRP-03, BRP-04, BRP-05
**Pitfalls addressed**: H-5, H-6, M-5, M-8, L-3 (GDPR retention on `brand_matches`)
**Success Criteria** (what must be TRUE):
  1. Admin or Analyst creates, edits, and deletes brand terms per project at `/projects/[id]/brand/terms` with term_type enum (keyword / domain / product / person); creating a `term_type='person'` surfaces a GDPR notice and terms under 6 characters surface a specificity warning with reference to a stoplist
  2. The `brand_monitor` Dramatiq actor runs on APScheduler IntervalTrigger(15 min) and scans three sources per term: `events.search_tsv` ILIKE + `pg_trgm` trigram similarity, crt.sh CT API for domain-type terms (precert/cert dedup on san + not_before), and dnstwist as a subprocess (`--threads 10 --format json`, 120s timeout, batched 5 terms at a time); matches dedupe via UNIQUE(project_id, brand_term_id, matched_value, match_source)
  3. HIGH / MEDIUM / LOW match severity is computed server-side — HIGH = domain lookalike on an active brand term with dnstwist lookup success; MEDIUM = CT log match; LOW = FTS match in ingested event
  4. Per-match action UI at `/projects/[id]/brand` offers confirm / dismiss-with-30-day-default-suppression / watchlist; dismissal is never permanent (threat actors register dormant lookalikes for later activation) and the suppression review surfaces expiring dismissals
  5. HIGH-severity matches synthesise a canonical event with `stix_type='brand-match-alert'` and `project_id` tag; the existing M1 `webhook_dispatch_tick` delivers alerts through Slack Block Kit, Teams Power Automate, Discord embeds, and Generic JSON with zero new webhook code
**Plans**: 12 plans
  - [ ] 12-00-PLAN.md — Wave 0 test stubs + dnstwist key-naming live-verify checkpoint + env keys (BRP-01..05)
  - [ ] 12-01-PLAN.md — Migration 011 + ORM models + Pydantic schemas + api-client regen (BRP-01..05 schema)
  - [ ] 12-02-PLAN.md — brand_stoplist + crtsh_client + dnstwist_parser + brand_severity (BRP-02/03)
  - [ ] 12-03-PLAN.md — brand_synth + brand_preview (BRP-05 + H-5)
  - [x] 12-04-PLAN.md — brand_monitor orchestrator (BRP-02/03)
  - [x] 12-05-PLAN.md — Dramatiq actor (queue=brand-monitor) + 4 scheduler jobs (BRP-02/04)
  - [x] 12-06-PLAN.md — routers/brand.py (8 endpoints) + /api/events include_brand_match (BRP-01/04/05)
  - [x] 12-07-PLAN.md — Compose worker --queues + dnstwist Dockerfile + regression test (BRP-02)
  - [x] 12-08-PLAN.md — Frontend /projects/[id]/brand dashboard + MatchTable + FilterBar + SuppressionReviewBanner (BRP-04)
  - [ ] 12-09-PLAN.md — Frontend /projects/[id]/brand/terms + TermsClient + BrandTermDialog with GDPR (BRP-01)
  - [ ] 12-10-PLAN.md — ProjectTabs Brand tab + /events include_brand_match Switch + provenance badge (BRP-05)
  - [ ] 12-11-PLAN.md — docs/ops/brand.md operator runbook (BRP-02/05)
**UI hint**: yes (`/projects/[id]/brand`, `/projects/[id]/brand/terms`, match review table)
**Research flag**: no — HIGH confidence, standard patterns

### Phase 12.1: Project Asset Surface from BBOT scan findings (INSERTED)

**Goal**: An operator browses a read-only per-project asset inventory at `/projects/[id]/assets` that surfaces every BBOT `bbot_event_type` landing in `easm_findings` (including the low-confidence types never promoted to canonical `events`), aggregated one row per (type, canonical_target) with first_seen/last_seen/scan_count history, auto-computed in/out/unscoped flag against `project_scope_rows`, and a free-text operator note as the only write surface.
**Requirements**: (none in REQUIREMENTS.md — inserted phase; CONTEXT.md is authoritative. Local IDs: ASSET-AGG, ASSET-SCOPE, ASSET-UI, ASSET-NOTE, ASSET-EXPORT)
**Depends on**: Phase 12
**Pitfalls addressed**: H-4 (preserved — no manual promote-to-event; EASM-06 allowlist remains sole promotion path)
**Plans**: 9 plans
  - [x] 12.1-00-PLAN.md — Wave 0 test stubs (backend + frontend)
  - [x] 12.1-01-PLAN.md — Migration 012 asset_notes + AssetNote ORM
  - [x] 12.1-02-PLAN.md — Pydantic v2 schemas (AssetRow/Detail/Summary/NotePatch/ExportFormat)
  - [x] 12.1-03-PLAN.md — assets_query service (aggregation SELECT, scope dispatch, asset_id_for)
  - [x] 12.1-04a-PLAN.md — routers/assets.py read surface (list + summary + detail)
  - [x] 12.1-04b-PLAN.md — routers/assets.py PATCH note + export + main.py registration
  - [x] 12.1-05a-PLAN.md — Frontend page + AssetsClient + summary cards + filter bar + textarea install
  - [x] 12.1-05b-PLAN.md — AssetsTable + AssetDetailDrawer + useNoteAutosave hook
  - [x] 12.1-06-PLAN.md — ProjectTabs Assets entry + api-client regen + ROADMAP update
**UI hint**: yes (`/projects/[id]/assets` — summary cards, filter bar, table, detail drawer with note autosave)
**Research flag**: YES — completed. See `.planning/phases/12.1-project-asset-surface-from-bbot-scan-findings/12.1-RESEARCH.md`.

### Phase 13: Production Readiness Hardening
**Goal**: v2.0 turns from code-complete to production-safe: every blocker pitfall has a regression-preventing integration test, operational drills are documented and rehearsed, and the loopback-only binding that has guarded the v1.5 lab deployment is removed behind the now-live authentication layer
**Depends on**: Phase 9, Phase 10, Phase 11, Phase 12 (validates the complete v2.0 surface end-to-end)
**Requirements**: PROD-01, PROD-02, PROD-03, PROD-04, PROD-05, PROD-06, PROD-07
**Constraint validated**: PROJECT.md — "no production use without auth" — the v2.0 release is production-deployable after this phase completes
**Success Criteria** (what must be TRUE):
  1. A cross-project leakage integration test confirms that an Analyst scoped to Project A cannot see Project B events via `/api/events`, `/projects/[b]/intel`, `/projects/[b]/graph`, or a direct AGE BFS — regardless of shared actor, shared technique, or filter-parameter manipulation
  2. An active-scan gate penetration test sends a direct curl `POST` to the EASM scan endpoint with `active=true` but without the two-factor gate fields and receives 403; the same test run with UI-valid fields but a tampered JWT claim also receives 403
  3. An authenticated Analyst setting `X-Dashboard-Role: red` while their JWT claim is Blue receives Blue-filtered data on every dashboard endpoint — the header is stripped at the proxy and ignored by `events_query` and `graph_traversal`
  4. SECRET_KEY rotation E2E drill succeeds: rotate key in `.env`, run `POST /api/admin/rekey-credentials`, verify no `sources` row becomes unreadable; `docs/ops/secret-rotation.md` captures the exact command sequence and a rollback plan
  5. Load test with 50k events × 10 projects runs EXPLAIN ANALYZE on `events_query(project_id=X)` and stays under 200ms p95 with the composite index `events(project_id, observed_at DESC)` in place
  6. Authentik recovery procedure is tested end-to-end: rebuild `authentik-db` from snapshot, re-issue OIDC client credentials, verify SSO login against the rebuilt IdP; `docs/ops/authentik-recovery.md` captures the procedure
  7. `ops/docker-compose.yml` removes the `127.0.0.1:` loopback prefix from the public-facing service bindings (api + web) and the v2.0 release is tagged; compose without `AUTH_ENABLED=true` refuses to expose those ports
**Plans**: 9 plans
  - [x] 13-00-PLAN.md — Wave 0 fixtures + harnesses (two-project seed, load seed, Caddy + entrypoint harnesses)
  - [x] 13-01-PLAN.md — PROD-01 cross-project leakage integration test
  - [x] 13-02-PLAN.md — PROD-02 active-scan gate pentest
  - [x] 13-03-PLAN.md — PROD-03 X-Dashboard-Role spoof defense-in-depth
  - [x] 13-04-PLAN.md — PROD-07 compose + Caddy + entrypoint guard (PROD-03 edge strip)
  - [ ] 13-05-PLAN.md — PROD-05 load test (50k × 10) + evidence
  - [ ] 13-06-PLAN.md — PROD-04 SECRET_KEY rotation drill
  - [ ] 13-07-PLAN.md — PROD-06 Authentik recovery drill
  - [ ] 13-08-PLAN.md — v2.0 fresh-deploy smoke + tag handoff
**UI hint**: no (tests, ops docs, config changes)
**Research flag**: no — standard hardening checklist execution

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Foundation | v1.5 | 8/8 | Complete | 2026-04-17 |
| 2. Ingestion Pipeline | v1.5 | 8/8 | Complete | 2026-04-17 |
| 3. Source Registry & Retention | v1.5 | 10/10 | Complete | 2026-04-17 |
| 4. Query API & Archiver | v1.5 | 8/8 | Complete | 2026-04-17 |
| 5. Dual Dashboard Shell | v1.5 | 9/9 | Complete | 2026-04-18 |
| 6. Combined Threat Visualisation | v1.5 | 9/9 | Complete | 2026-04-18 |
| 7. Webhook Alerts | v1.5 | 8/8 | Complete | 2026-04-18 |
| 8. Pre-Auth Infrastructure Hardening | 7/7 | Complete   | 2026-04-18 | - |
| 9. Authentication Foundation | 9/10 | In Progress|  | - |
| 10. Projects Foundation | 13/14 | In Progress|  | - |
| 11. EASM via BBOT | 14/14 | Complete    | 2026-04-22 | - |
| 12. Brand Protection | 13/13 | Complete    | 2026-04-24 | - |
| 12.1. Project Asset Surface | v2.0 | 9/9 | Complete    | 2026-04-24 |
| 13. Production Readiness Hardening | v2.0 | 5/9 | In Progress | - |

## v2.0 Dependency Graph

```
Phase 8 (Infra Hardening)
   │
   ▼
Phase 9 (Authentication)
   │
   ▼
Phase 10 (Projects)
   │
   ├────────────┬────────────┐
   ▼            ▼
Phase 11    Phase 12
(EASM)      (Brand Protection)
   │            │
   └────────────┴────────────┐
                             ▼
                        Phase 13
                   (Production Readiness)
```

**Hard dependencies:**
- Phase 8 → Phase 9: `AUTH_ENABLED` flag + rekey infra must precede auth code
- Phase 9 → Phase 10: `request.state.user` required for `Depends(require_admin_role)`
- Phase 10 → Phase 11: `projects.active_scans_authorised` + `scope_acknowledgement_text` + `active_auth_confirmed_at` columns pre-exist in migration 009 for C-3 gate
- Phase 10 → Phase 12: `projects.id` FK required by migration 009
- Phase 10 migration must complete cleanly — rollback is HIGH-cost (pg_restore + manual chunk decompress)
- {Phase 11, Phase 12} → Phase 13: all four themes in production before hardening gate

**Soft dependencies:**
- OpenAPI codegen (Phase 8) — without it, Phases 10/11/12 risk schema drift
- Synthesised-event + webhook-reuse pattern alignment between Phases 11 and 12 — worth coordinating early

**Parallel-safe:**
- Phase 11 ∥ Phase 12 (disjoint migrations, routers, queues, frontends)

## v2.0 Descope Candidates

If milestone risk demands descope, the following are the first candidates for v2.1 movement. INFRA and PROD requirements stay — they are prerequisites and quality-gates that validate the PROJECT.md "no production use without auth" constraint.

| Requirement | Phase | Reason Defer-Eligible |
|-------------|-------|-----------------------|
| PRJ-06 | Phase 10 | Cross-project compare — HIGH cost, independent of other PRJ items |
| PRJ-07 | Phase 10 | Per-project STIX + CSV export — standalone feature, not required for scope-intersection correctness |
| EASM-08 | Phase 11 | Scan history diff UI — nice-to-have, not required for scan correctness or active-scan gate |

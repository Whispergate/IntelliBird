# Requirements: IntelliBird v2.0 M2 Engagement

**Defined:** 2026-04-18
**Core Value:** A single operator can see the current cyber threat landscape — world events, actor activity, CVEs, feed signal — in one place, filter and tag it, and drill from a geo view into the attack graph behind any event.
**Milestone scope:** Transform IntelliBird from loopback-only lab tool into production-grade engagement platform: auth unlocks non-lab deployment, Projects enable multi-engagement scope separation, EASM via BBOT adds external attack surface discovery, Brand Protection watches for brand signals in ingested intel + external sources.

## v2 Requirements

### Pre-Auth Infrastructure Hardening

Groundwork that must land before Authentication to prevent blocker pitfalls C-1 (SECRET_KEY rotation corrupts `sources.credentials_enc`) and H-1 (Route Handler proxy silently bypasses auth during rollout).

- [x] **INFRA-01**: `sources.credentials_enc` rows tagged with `credentials_key_version` so HKDF-derived key rotations are reversible
- [x] **INFRA-02**: Admin `POST /api/admin/rekey-credentials` endpoint re-encrypts all credentials with the current SECRET_KEY (setup-token gated, pre-auth)
- [x] **INFRA-03**: Backend startup decrypt sanity check logs CRITICAL + raises UI banner when an encrypted row fails to decrypt under the current key
- [x] **INFRA-04**: `AUTH_ENABLED` feature flag wired end-to-end (backend middleware bypass + Next.js Route Handler proxy preservation + frontend NoAuthBanner) so backend auth can land before frontend token injection
- [x] **INFRA-05**: OpenAPI-to-TypeScript codegen generates `web/app/api-client.ts` from backend schema to prevent v2.0 schema drift across new routers
- [ ] **INFRA-06**: `docs/ops/secret-rotation.md` documents the rekey procedure and the consequences of skipping it

### Authentication

Local + SSO auth, role model, session management. Removes the loopback-only constraint.

- [x] **AUTH-01**: Admin can create local user accounts with Argon2-hashed passwords via `/api/admin/users` (first-user bootstrap for initial admin); Authentik OIDC SSO with groups-claim → role mapping (Admin/Analyst/Viewer) lands SSO users as Viewer by default
- [x] **AUTH-02**: Three roles — Admin, Analyst, Viewer — enforced at router level via `require_admin_role` / `require_analyst_role` dependencies; role derived exclusively from JWT claim (X-Dashboard-Role header is stripped at the proxy and no longer trusted)
- [x] **AUTH-03**: JWT access token (15 min) + refresh token (7 day, httpOnly cookie) session flow with Redis JTI blocklist for logout; session persists across browser refresh until refresh expiry
- [x] **AUTH-04**: Role-based dashboard visibility — Red/Blue routing derived from JWT role claim, `events_query` and `graph_traversal` switched from header to claim, conditional NoAuthBanner when `AUTH_ENABLED=false`

### Projects / Per-Engagement Scoping

Multi-engagement scope separation. AlphaStrike-style scope tabs. Every EASM and BRP artefact references a project.

- [x] **PRJ-01**: Admin or Analyst can create/edit/archive projects with name, engagement_type enum (red_team / tiber / bbest / internal / intel_only), description, created_by (Authentik sub, TEXT)
- [x] **PRJ-02**: Per-project scope tabs for 7 scope types (keyword, service, domain, certificate, whois, as_number, ip_range) with per-row contact + include/exclude + active_test_scope / intel_scope toggle per TIBER-EU
- [x] **PRJ-03**: Per-project intel view at `/projects/[id]/intel` filters `events_query` by scope-intersection at query time (CIDR `<<` for IP, subdomain suffix for domains, `tsvector @@` for keywords) — no ingest-time multiplication
- [x] **PRJ-04**: Per-project attack graph at `/projects/[id]/graph` scopes AGE BFS via JOIN-to-events on `project_id` (not via AGE node properties) to prevent cross-project graph leakage
- [x] **PRJ-05**: Projects can bind specific sources via `project_sources` for source-restricted engagements (useful for air-gapped TIBER exercises)
- [x] **PRJ-06**: Cross-project compare view shows shared actors/infra across two or more projects (deferred to late milestone — HIGH-complexity; may move to v2.1 if milestone risk requires)
- [x] **PRJ-07**: Per-project export — STIX 2.1 bundle + CSV raw events (deferred to late milestone — may move to v2.1 if milestone risk requires)

### External Attack Surface Monitoring (EASM) via BBOT

BBOT-powered project-scoped recon. Passive-by-default; active scans gated by two-factor written acknowledgement. Runs in a dedicated compose service.

- [x] **EASM-01**: Dedicated `easm-worker` compose service running BBOT 2.8.4 via Docker subprocess (`docker run blacklanternsecurity/bbot:stable ...`) on a dedicated Dramatiq `easm` queue — never pip-installed into the API/worker image
- [x] **EASM-02**: Per-project passive EASM scan via `run_bbot_scan` Dramatiq actor; scan result streams stdout JSON into `easm_findings` with ON CONFLICT DO UPDATE dedup on (project_id, bbot_event_type, canonical_target)
- [x] **EASM-03**: Passive-only is the immutable default; `-rf passive` flag enforced programmatically in the worker independent of UI
- [x] **EASM-04**: Active scan requires all three: `projects.active_scans_authorised=true` + typed `scope_acknowledgement_text` phrase + `active_auth_confirmed_at` timestamp — enforced backend-side, bypass-proof via API
- [x] **EASM-05**: Backend module-safelist returns 422 on experimental/aggressive modules; stable-tier safelist documented
- [x] **EASM-06**: High-confidence finding types (`FINDING`+HIGH, `VULNERABILITY`, `SUBDOMAIN_TAKEOVER_CANDIDATE`, `TECHNOLOGY`) promote to canonical `events` via allowlist; low-confidence findings stay in `easm_findings` only
- [x] **EASM-07**: Per-project EASM dashboard at `/projects/[id]/easm` lists findings with severity, source module, first-seen, last-seen; filters by type + module
- [x] **EASM-08**: Scan history view with diff against previous scan (NEW / CHANGED / RESOLVED buckets) — deferred to late milestone; may move to v2.1
- [x] **EASM-09**: Redis semaphore `bbot:concurrent_scans` caps concurrent scans (default 2) to protect worker host; config via env
- [x] **EASM-10**: BBOT scan container isolation — dedicated `bbot_scans` volume, `/var/run/docker.sock` mount documented as an elevated-privilege requirement in `docs/ops/`

### Brand Protection

Per-project brand terms monitored against ingested intel + crt.sh CT logs + dnstwist lookalikes. High-severity matches alert via the existing M1 webhook pipeline (zero new webhook infrastructure).

- [x] **BRP-01**: Per-project brand terms CRUD at `/projects/[id]/brand/terms` with term_type enum (keyword / domain / product / person) and GDPR notice on `term_type='person'`
- [x] **BRP-02**: `brand_monitor` Dramatiq actor on APScheduler IntervalTrigger(15 min) scans three sources per term — `events.search_tsv` ILIKE + `pg_trgm`, crt.sh CT API for domain-type terms, dnstwist subprocess for lookalikes — dedupe against `brand_matches` UNIQUE on (project_id, brand_term_id, matched_value, match_source)
- [x] **BRP-03**: HIGH / MEDIUM / LOW match severity — HIGH = domain lookalike on active brand + dnstwist lookup success; MEDIUM = CT log match; LOW = FTS match in ingested event; computed server-side
- [x] **BRP-04**: Per-match action UI (confirm / dismiss with 30-day default suppression / watchlist) at `/projects/[id]/brand`; dismissal never permanent (threat actors register dormant lookalikes for later activation); brand term specificity warning <6 chars + stoplist
- [x] **BRP-05**: HIGH-severity matches synthesise a canonical event (`stix_type='brand-match-alert'`, project_id tag) so existing `webhook_dispatch_tick` delivers alerts through all four M1 webhook destinations — zero new webhook code

### Production Readiness Hardening

Validates the milestone's locked PROJECT.md constraint ("no production use without auth") by adding the integration-test and operational-drill coverage that turns a deployable release into a production-grade one. Without this, v2.0 is code-complete but not production-safe.

- [ ] **PROD-01**: Cross-project leakage integration test — Project A user cannot see Project B events via `/events`, `/projects/[b]/intel`, `/projects/[b]/graph`, or AGE BFS
- [x] **PROD-02**: Active-scan gate penetration test — direct curl POST to EASM scan endpoint with `active=true` but without the two-factor gate fields returns 403
- [ ] **PROD-03**: X-Dashboard-Role header-spoofing test — authenticated Analyst setting `X-Dashboard-Role: red` (while JWT claim is Blue) returns Blue-filtered data regardless
- [ ] **PROD-04**: SECRET_KEY rotation E2E drill — rotate key, run `rekey_credentials`, verify no `sources` row becomes unreadable; documented in `docs/ops/secret-rotation.md`
- [ ] **PROD-05**: Load test — 50k events × 10 projects, EXPLAIN ANALYZE on `events_query(project_id=X)` stays under 200ms p95 with `events(project_id, observed_at DESC)` composite index
- [ ] **PROD-06**: Authentik recovery procedure tested end-to-end (rebuild `authentik-db` from snapshot, re-issue OIDC credentials, verify SSO login); documented in `docs/ops/authentik-recovery.md`
- [x] **PROD-07**: Remove loopback-only binding from `ops/docker-compose.yml` after Phase 1 AUTH lands; Phase 5 re-exposes ports publicly behind auth

## v3 Requirements (Deferred)

Tracked but not in v2.0 roadmap. Candidates for v2.1 or a later milestone.

### AI Summarisation

- **AI-01**: Pluggable LLM adapter for local (Ollama) + hosted (OpenAI, Anthropic) models via LiteLLM
- **AI-02**: Per-event AI summary on demand in EventDetailDrawer
- **AI-03**: Actor timeline synthesis across multiple events for a single actor
- **AI-04**: AI-assisted severity rerank on top of the deterministic scoring engine

### TIBER / CBEST Artefact Generation

- **TIBER-01**: TTI report generator — actor cards + target profile + TTP table from project scope
- **TIBER-02**: TIBER phase tagging across events (Targeting / Recon / Weaponization / Delivery / …)
- **TIBER-03**: Threat scenario builder — actor → target → TTP graph editor
- **TIBER-04**: PDF / Markdown TTI report export

### Continuous Monitoring

- **MON-01**: Per-source watch profiles with drift detector (3σ volume anomaly)
- **MON-02**: Vanishing-source detector (alert when a source has ingested 0 events in N ticks)
- **MON-03**: Monitoring dashboard with health-over-time charts

### Rule-Based Scoring Engine

- **SCORE-01**: Rule-based severity scoring engine (actor reputation × IOC recency × source confidence)
- **SCORE-02**: Admin rule editor UI with live score preview
- **SCORE-03**: Score surfaced in event list + EventDetailDrawer

### Additional Integrations

- **INT-01**: MISP direct API integration (beyond TAXII) for IOC sharing
- **INT-02**: Additional threat-sharing platform adapters (OpenCTI, TheHive)

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| SaaS multi-tenant hosting | Self-hosted only per PROJECT.md constraint; team/SOC on-prem deployment target |
| Air-gapped deployment as primary mode | Online feeds assumed; `project_sources` binding partially addresses it for TIBER but full offline is out-of-scope for v2.0 |
| Endpoint telemetry / EDR ingest | IntelliBird aggregates threat intel, not host telemetry |
| Incident response case management | Out of domain; interop via STIX export instead |
| Auto-provisioning SSO users as Analyst | Anti-feature (Features research) — default to Viewer until Admin promotes; prevents entire Authentik org pool from accessing dashboards |
| Auto-dismiss brand matches as false positive | Anti-feature (Features research) — trains a filter without analyst review; defeats SOC purpose |
| Permanent brand suppression | Threat actors register dormant lookalikes for later activation; suppression must expire (default 30 days) |
| BBOT pip-installed into API/worker image | Pitfall C-5 — BBOT multiprocessing fails inside Dramatiq daemon; Docker subprocess only |
| Local `users` table | Authentik is the sole user store; `projects.created_by` stores Authentik `sub` as TEXT with no FK |
| CertStream realtime CT monitoring in M2 | crt.sh polling at 15 min sufficient for SOC brand-protection latency; CertStream as a v2.1 candidate |
| ML severity scoring | Rule-based scoring engine deferred; ML rerank is v2.1 at earliest |

## Traceability

Which phases cover which requirements. Populated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 | Phase 8 | Complete |
| INFRA-02 | Phase 8 | Complete |
| INFRA-03 | Phase 8 | Complete |
| INFRA-04 | Phase 8 | Complete |
| INFRA-05 | Phase 8 | Complete |
| INFRA-06 | Phase 8 | Pending |
| AUTH-01 | Phase 9 | Complete |
| AUTH-02 | Phase 9 | Complete |
| AUTH-03 | Phase 9 | Complete |
| AUTH-04 | Phase 9 | Complete |
| PRJ-01 | Phase 10 | Complete |
| PRJ-02 | Phase 10 | Complete |
| PRJ-03 | Phase 10 | Complete |
| PRJ-04 | Phase 10 | Complete |
| PRJ-05 | Phase 10 | Complete |
| PRJ-06 | Phase 10 | Complete |
| PRJ-07 | Phase 10 | Complete |
| EASM-01 | Phase 11 | Complete |
| EASM-02 | Phase 11 | Complete |
| EASM-03 | Phase 11 | Complete |
| EASM-04 | Phase 11 | Complete |
| EASM-05 | Phase 11 | Complete |
| EASM-06 | Phase 11 | Complete |
| EASM-07 | Phase 11 | Complete |
| EASM-08 | Phase 11 | Complete |
| EASM-09 | Phase 11 | Complete |
| EASM-10 | Phase 11 | Complete |
| BRP-01 | Phase 12 | Complete |
| BRP-02 | Phase 12 | Complete |
| BRP-03 | Phase 12 | Complete |
| BRP-04 | Phase 12 | Complete |
| BRP-05 | Phase 12 | Complete |
| PROD-01 | Phase 13 | Pending |
| PROD-02 | Phase 13 | Complete |
| PROD-03 | Phase 13 | Pending |
| PROD-04 | Phase 13 | Pending |
| PROD-05 | Phase 13 | Pending |
| PROD-06 | Phase 13 | Pending |
| PROD-07 | Phase 13 | Complete (13-04) |

**Coverage:**
- v2 requirements: 39 total (6 INFRA + 4 AUTH + 7 PRJ + 10 EASM + 5 BRP + 7 PROD)
- Mapped to phases: 39
- Unmapped: 0 ✓

**Note on count vs PROJECT.md "26 requirements":** PROJECT.md's 26-requirement scope (4 AUTH + 7 PRJ + 10 EASM + 5 BRP) remains the user-facing feature commitment. INFRA and PROD requirements were surfaced by research as prerequisite + verification requirements needed to satisfy the PROJECT.md constraint "no production use without auth." They are infrastructure and quality-gates, not user-facing features. If milestone risk demands descope, INFRA and PROD stay; PRJ-06, PRJ-07, and EASM-08 are the first candidates for v2.1 movement.

---
*Requirements defined: 2026-04-18 after v1.5 archive and research synthesis*
*Last updated: 2026-04-18 after initial definition*

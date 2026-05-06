# Roadmap: IntelliBird

## Milestones

- ✅ **v1.5 IntelliBird M1** — Phases 1-7 (shipped 2026-04-18) — see [milestones/v1.5-ROADMAP.md](milestones/v1.5-ROADMAP.md)
- ✅ **v2.0 IntelliBird M2 Engagement** — Phases 8-14 (shipped 2026-04-25) — see [milestones/v2.0-ROADMAP.md](milestones/v2.0-ROADMAP.md)
- ✅ **v3.0 IntelliBird M3 Engagement** — Phases 15-18 (shipped 2026-04-26) — see [milestones/v3.0-ROADMAP.md](milestones/v3.0-ROADMAP.md)
- ✅ **v3.1 Pre-Release Polish** — Phases 19-21 (shipped 2026-04-29) — see [milestones/v3.1-ROADMAP.md](milestones/v3.1-ROADMAP.md)
- 🚧 **v4.0 Threat Intelligence Platform Maturity** — Phases 22-34 (defined 2026-05-03)

## Phases

<details>
<summary>✅ v1.5 IntelliBird M1 (Phases 1-7) — SHIPPED 2026-04-18</summary>

- [x] Phase 1: Foundation
- [x] Phase 2: Ingestion Pipeline
- [x] Phase 3: Source Registry & Retention
- [x] Phase 4: Query API & Archiver
- [x] Phase 5: Dual Dashboard Shell
- [x] Phase 6: Combined Threat Visualisation
- [x] Phase 7: Webhook Alerts

See [milestones/v1.5-ROADMAP.md](milestones/v1.5-ROADMAP.md).

</details>

<details>
<summary>✅ v2.0 IntelliBird M2 Engagement (Phases 8-14) — SHIPPED 2026-04-25</summary>

- [x] Phase 8: Pre-Auth Infrastructure Hardening
- [x] Phase 9: Authentication Foundation
- [x] Phase 10: Projects Foundation
- [x] Phase 11: EASM via BBOT
- [x] Phase 12: Brand Protection
- [x] Phase 12.1: Project Asset Surface (INSERTED)
- [x] Phase 13: Production Readiness Hardening
- [x] Phase 14: v2.0 Audit Closure

See [milestones/v2.0-ROADMAP.md](milestones/v2.0-ROADMAP.md).

</details>

<details>
<summary>✅ v3.0 IntelliBird M3 Engagement (Phases 15-18) — SHIPPED 2026-04-26</summary>

- [x] Phase 15: Scoring Engine Foundation
- [x] Phase 16: Continuous Monitoring
- [x] Phase 17: AI Infrastructure + Summarisation
- [x] Phase 18: TIBER Report Generation

See [milestones/v3.0-ROADMAP.md](milestones/v3.0-ROADMAP.md).

</details>

<details>
<summary>✅ v3.1 Pre-Release Polish (Phases 19-21) — SHIPPED 2026-04-29</summary>

- [x] Phase 19: Test Infrastructure Hardening
- [x] Phase 20: Project Graph + UX Debt
- [x] Phase 21: Brand Polish + Hygiene

See [milestones/v3.1-ROADMAP.md](milestones/v3.1-ROADMAP.md).

</details>

### v4.0 Threat Intelligence Platform Maturity (Phases 22-34)

**Milestone Goal:** Mature IntelliBird from "engagement intel aggregator" into a full SOC/red-team TIP — atomic IOC management, on-demand enrichment, deep/dark collection, outbound federation, native case workflow, multi-hop graph pivoting, and counter-disinformation tradecraft.

**Source plan:** `/home/lavender/.claude/plans/please-find-points-vast-hearth.md`

- [x] **Phase 22: IOC Foundation** — First-class atomic indicator table, bulk import, TTL decay, cross-event pivots — SHIPPED 2026-05-03 (6/6 plans)
- [x] **Phase 23: IOC Enrichment APIs** — VirusTotal / AbuseIPDB / GreyNoise / OTX / Shodan / URLhaus reputation + quota guard (completed 2026-05-03)
- [x] **Phase 24: Dark-Web Collection** — Tor + paste + Telegram with isolated egress and OPSEC compartmentation (completed 2026-05-03)
- [x] **Phase 25: Threat Actors, Campaigns & Audit Log** — Cross-engagement actor catalog, campaign grouping, hypertable audit trail (completed 2026-05-03)
- [x] **Phase 26: TAXII Outbound Server** — Spec-correct federation publishing with per-partner ACLs (completed 2026-05-03)
- [x] **Phase 27: Sandbox + YARA** — File-detonation pipeline paired with YARA scanning of samples and STIX patterns (completed 2026-05-04)
- [x] **Phase 28: Passive DNS, WHOIS & Multi-hop Graph** — Infrastructure pivoting via shared registrar/IP plus 2-3 hop traversal (completed 2026-05-04)
- [x] **Phase 29: Sigma Rule Engine** — Community Sigma rule sets auto-tagging events at ingest (completed 2026-05-04)
- [x] **Phase 30: Notification Channels** — Email / PagerDuty / Opsgenie / ntfy reusing webhook dispatcher (completed 2026-05-04)
- [x] **Phase 31: Case Management** — Lightweight cases, kanban, IOC + event linking (completed 2026-05-04)
- [x] **Phase 32: CertStream + MISP** — Sub-second CT log streaming and bidirectional MISP sync (completed 2026-05-06)
- [x] **Phase 33: Disinformation + Pattern-of-Life Timeline** — CIB heuristics on social listening + temporal heatmap (completed 2026-05-06)
- [ ] **Phase 34: Browser Extension** — Manifest V3 right-click pivot from external tools to IntelliBird IOC search

## Phase Details

### Phase 22: IOC Foundation
**Goal**: Operator can store, search, bulk-import, whitelist, and TTL-expire atomic indicators in a dedicated table that backfills from existing event tags.
**Depends on**: Phase 10 (project chokepoint), Phase 17 (AI suggestion staging shape)
**Requirements**: IOC-01, IOC-02, IOC-03, IOC-04, IOC-05, IOC-06, IOC-07, IOC-08
**Reuse points**:
  - `events_query.build_scope_predicate` for cross-project ACL on `GET /api/iocs`
  - STIX bundle parser from TIBER exporter for `bulk-import` STIX path
  - `ai_suggestion_expiry` scheduler pattern for TTL decay job
  - Migration 020 `brand_stoplist_terms` shape for per-project FK + CASCADE
**Pitfalls**:
  - `iocs` table will grow large; partition by `last_seen` if hypertable conversion considered (defer unless volume forces it)
  - IDN normalisation must use `idna.encode(uts46=True)` per Phase 20 precedent for domain IOCs
  - Backfill from `events.tags[]` must run idempotently (re-runnable on migration redo)
**Success Criteria** (what must be TRUE):
  1. Operator imports 1000-row CSV via `POST /api/iocs/bulk-import` and sees rows in project IOCs tab; duplicates dedup by `(type, normalized_value, project_id)`
  2. Operator searches `GET /api/iocs?type=ip&value=1.2.3.4` and receives every event referencing that IP across allowed projects (Admin sees all, Observer sees own project only)
  3. Operator marks an IOC whitelisted; subsequent `enrich_ioc` (Phase 23) and event-detail rendering exclude it from default views
  4. Daily scheduler job sets `status='expired'` on rows where `last_seen + ttl_days < NOW()`; expired rows hidden from default queries but still queryable via `?include_expired=true`
  5. After migration apply, `iocs` row count > 0 from backfill of existing event tags; `ioc_event_links` populated; cross-project leakage tests extended to assert no IOC bleeds across project boundaries
**OPSEC**: Per-project opt-in; cross-project IOC search requires Admin role.
**Plans**: 6 plans
- [x] 22-01-test-scaffolding-PLAN.md — Wave 0 test stubs (17 files)
- [x] 22-02-schema-models-PLAN.md — Migration 023, IOC + IOCEventLink models, normaliser, schemas
- [x] 22-03-read-routes-acl-PLAN.md — Cross-project scope predicate + GET routes (search, get-by-id, linked-events)
- [x] 22-04-writes-scheduler-backfill-PLAN.md — Whitelist endpoint, TTL expiry scheduler, ingest hook, admin backfill
- [x] 22-05-bulk-import-PLAN.md — CSV/JSON/STIX parsers, Dramatiq actor, bulk-import endpoint
- [x] 22-06-frontend-ui-PLAN.md — IOCs tab, table, drawer, bulk-import dialog, backfill widget — SHIPPED 2026-05-03

### Phase 23: IOC Enrichment APIs
**Goal**: Every newly-created IOC is auto-enriched against analyst-configured reputation providers, with results visible in the event detail drawer and quotas guarded by Redis circuit breakers.
**Depends on**: Phase 22 (IOC table), Phase 17 (encrypted-credentials pattern)
**Requirements**: ENRICH-01, ENRICH-02, ENRICH-03, ENRICH-04, ENRICH-05
**Reuse points**:
  - `crypto.encrypt_credentials` + `AIProvider.credentials_enc` pattern for per-project API keys
  - `services/llm/client.py` provider-abstraction shape for `services/enrichment/external/{vt,abuseipdb,greynoise,otx,shodan,urlhaus}.py`
  - `services/redis_client.py` per-loop client + Lua atomic budget pattern from AI tokens
  - `EventDetailDrawer` AI Summary section pattern for new "Enrichment" section
**Pitfalls**:
  - VT free tier 4 req/min — must batch + dedupe; rolling-window counter must survive worker restart (Redis persistence)
  - Air-gapped fallback — providers must degrade gracefully when no API key configured (do not crash ingest path)
  - Circuit-breaker on repeated quota exhaust must auto-recover after cooldown (mirror `webhook_dispatcher` retry shape)
  - `ioc_enrichments` table grows fast; TimescaleDB hypertable on `(fetched_at, ioc_id)` recommended
**Success Criteria** (what must be TRUE):
  1. Admin pastes a VirusTotal API key in project settings; new SHA256 IOCs receive enrichment within 60s and surface a malicious/suspicious/clean badge in the event drawer
  2. Sustained ingestion of >4 IPs/min hits VT quota → circuit-breaker opens; Redis cache `enrich:vt:{ip}` serves cached results for 24h; no quota errors propagate to ingest path
  3. Operator with no API keys configured sees ingest continue normally; enrichment section renders "no provider configured" rather than erroring
  4. Each provider's results stored as one row per `(ioc_id, provider)` in `ioc_enrichments`; raw JSON retained for re-rendering with new UI without re-fetching
**OPSEC**: External-API per-project opt-in; UI warns "data leaves perimeter when this provider is enabled".
**Plans**: 6 plans
- [x] 23-01-PLAN.md — Wave 0 test scaffolding (14 stub files)
- [x] 23-02-PLAN.md — Migration 024, ORM models, Pydantic schemas
- [x] 23-03-PLAN.md — Provider service layer (quota, circuit breaker, cache, 6 external modules)
- [x] 23-04-PLAN.md — enrich_ioc actor + ingest hook
- [x] 23-05-PLAN.md — Provider settings API + rekey sweep + router registration
- [ ] 23-06-PLAN.md — Frontend UI (EnrichmentProvidersCard, IOCDetailDrawer, IOCsSection, api-client)

### Phase 24: Dark-Web Collection
**Goal**: Operator can configure Tor-routed `.onion` scrapes, paste-site polling, and public Telegram channel ingestion through an isolated egress profile, with auto-extraction of credential pairs and BTC wallets.
**Depends on**: Phase 22 (IOC table receives auto-extracted indicators), Phase 2 (RSS/HTML scrape worker shape)
**Requirements**: DARK-01, DARK-02, DARK-03, DARK-04, DARK-05, DARK-06, DARK-07
**Reuse points**:
  - `poll_html_scrape` actor skeleton in `workers/rss.py` / `workers/html_scrape.py`
  - `_persist_event_for_bindings` for fan-out
  - Existing IOC regex enrichment in `ingest/normalise.py`
  - Compose `--profile easm` precedent for `--profile darkweb` gating
**Pitfalls**:
  - Tor exit fingerprinting — `tor` compose service MUST sit on its own network with no clearnet egress; EASM container MUST NOT route through it
  - Telegram requires API key + burner phone; persistence of session state in volume; only public channels (no auto-join private invites)
  - Paste sites rate-limit aggressively; respect `robots.txt`; per-source backoff
  - Default `confidence=0.4` so dark-web noise does not auto-promote to S-tier alerts
**Success Criteria** (what must be TRUE):
  1. Operator runs `docker compose --profile darkweb up`; `tor` service comes up on its own network; new `tor_html` source type fetches a known `.onion` test URL and persists an event with `source_type='tor_html'`
  2. Operator adds a paste source (e.g. paste.ee RSS); subsequent paste matching a CVE pattern auto-extracts the CVE ID and persists with `confidence=0.4`
  3. Operator adds a public Telegram channel via Telethon API key; channel posts ingest as events; private invite-only channels rejected at validation
  4. Dark-web event content containing `email:hash` patterns auto-creates IOC rows of type `email`; BTC wallets auto-create `btc` IOCs; both linked via `ioc_event_links`
  5. Adding any `tor_html` / `paste` / `telegram` source surfaces an OPSEC warning banner in the UI; operator must explicitly tick "I authorise this source" before save succeeds
**OPSEC**: Dedicated Tor egress; no cross-contamination with EASM or operator browser; burner Telegram persona.
**Plans**: 7 plans
Plans:
- [ ] 24-01-PLAN.md — Wave 0 test scaffolding (8 stub files)
- [ ] 24-02-PLAN.md — Migration 025, ORM model, pyproject.toml deps
- [ ] 24-03-PLAN.md — tor_html + paste + telegram workers, broker + scheduler
- [x] 24-04-PLAN.md — OPSEC gate, rekey sweep for session_enc
- [ ] 24-05-PLAN.md — Credential pair IOC extraction (_text_extraction.py)
- [x] 24-06-PLAN.md — Docker Compose tor service + tor-worker + darkweb_net
- [x] 24-07-PLAN.md — Frontend OPSEC warning banner + checkbox (checkpoint)

### Phase 25: Threat Actors, Campaigns & Audit Log
**Goal**: Global threat-actor catalog and campaign entities persist across engagements; every mutation is recorded in a TimescaleDB audit log browsable by Admins.
**Depends on**: Phase 22 (IOC table for case linking later), Phase 17 (AI suggestion alias-match shape)
**Requirements**: ACTOR-01, ACTOR-02, ACTOR-03, ACTOR-04, ACTOR-05, ACTOR-06, AUDIT-01, AUDIT-02, AUDIT-03
**Reuse points**:
  - `bootstrap_attack` STIX pull — extend to ingest `intrusion-set` SDOs into `threat_actors`
  - `TiberActorProfile` UI patterns (Phase 18) for `/actors` route
  - `events` hypertable retention pattern for `audit_log` hypertable
  - AuthMiddleware (Phase 9) attaches `user_sub` + `request_id` to request context for middleware logging
**Pitfalls**:
  - Audit middleware must run AFTER dependency resolution but BEFORE response serialisation; use FastAPI `BaseHTTPMiddleware` carefully (does not see route-level deps natively — may need custom router-aware middleware)
  - `before_jsonb` / `after_jsonb` diff capture requires SQLAlchemy `before_update` event listener or explicit serialisation in service layer
  - Fuzzy actor alias match (ACTOR-04) must not auto-promote uncertain matches — stage as `ai_suggestion` per existing pattern
  - Campaign `project_id NULL = global` overlap with project-scoped queries needs explicit handling in `events_query`
**Success Criteria** (what must be TRUE):
  1. After `bootstrap_attack` runs, `threat_actors` table contains MITRE intrusion-set rows (e.g. APT29, Lazarus) with aliases populated; `/actors` page renders the catalog
  2. AI suggestion path extracts an actor mention; if alias matches an existing row, suggestion auto-links to the actor; if no match, stages as pending suggestion (analyst confirms before catalog write)
  3. Lead+ user creates a campaign, links 5 events; `/actors/{id}` profile page shows the campaign in a timeline and a Cytoscape sub-graph of actor → campaign → events
  4. Every non-GET API call appends a row to `audit_log` with `user_sub`, `action`, `resource_type`, `resource_id`, `before_jsonb`, `after_jsonb`, `request_id`; Admin browses `/admin/audit` and filters by user/resource/date
  5. Audit log hypertable retention policy mirrors `events` (90d hot, configurable archival); cross-project leakage tests confirm Observer cannot read other projects' audit rows
**OPSEC**: Audit log is read-only via UI; direct DB access is operator responsibility.
**Plans**: 6 plans
Plans:
- [x] 25-01-PLAN.md — Wave 0 test scaffolding (8 stub files)
- [x] 25-02-PLAN.md — Migration 026, ORM models (ThreatActor, Campaign, CampaignEvent, ActorEventLink, AuditLog), audit service helper, rapidfuzz
- [ ] 25-03-PLAN.md — actor_writer.py STIX upsert + bootstrap_attack extension + fuzzy alias matcher + suggestion_validator replacement
- [ ] 25-04-PLAN.md — REST routes: actors CRUD, campaigns CRUD, admin/audit read + main.py registration
- [ ] 25-05-PLAN.md — Frontend /actors list + /actors/[id] profile (ActorSubGraph, CampaignCard, badges, cose-bilkent)
- [ ] 25-06-PLAN.md — Frontend /admin/audit page (AuditDiffViewer, ActionBadge, filters, checkpoint)

### Phase 26: TAXII Outbound Server
**Goal**: External partners can pull project events as STIX 2.1 bundles via spec-correct TAXII 2.1 collections gated by per-partner API keys and TLP markings.
**Depends on**: Phase 25 (audit log captures partner pulls), Phase 18 (STIX exporter)
**Requirements**: TAXII-01, TAXII-02, TAXII-03, TAXII-04, TAXII-05
**Reuse points**:
  - `services/tiber/exporters/stix.py` STIX 2.1 bundle generator — generalise to non-TIBER scope
  - `events_query.build_scope_predicate` chokepoint for TLP-marking ACL
  - Cursor-pagination utilities from `events_query.py`
**Pitfalls**:
  - Spec compliance MUST be exact: `Content-Type: application/taxii+json;version=2.1`; per-page cap 100 objects; `more`/`next` envelope per spec
  - TLP enforcement — only WHITE/GREEN expose by default; AMBER/RED gated per-collection ACL on `taxii_clients` row
  - Partner API key revocation must be effective within one request (no caching)
  - TAXII discovery endpoint must NOT leak project names if partner key not provided
**Success Criteria** (what must be TRUE):
  1. Public partner with valid API key hits `GET /taxii2/` and receives spec-compliant discovery response listing collections they have ACL for
  2. Partner pulls `GET /taxii2/api/collections/{id}/objects/`; response is paginated STIX 2.1 bundle of project events as indicator/observed-data SDOs; Content-Type strictly `application/taxii+json;version=2.1`
  3. Admin issues a partner key restricted to TLP:GREEN; partner request returns events but AMBER/RED events are filtered out at the predicate layer (PROD-01-style leakage test extended)
  4. Per-request page cap enforced at 100 objects; `more=true` + `next` cursor returned when collection exceeds page
  5. Admin revokes partner key; subsequent partner requests return 401 within the same second (no cache lag)
**OPSEC**: TLP markings enforced server-side; per-partner key revocable; all pulls audited.
**Plans**: 5 plans
Plans:
- [ ] 26-01-PLAN.md — Wave 0 test scaffolding (3 test stubs + migration stub)
- [ ] 26-02-PLAN.md — Migration 027, TaxiiClient ORM model, Pydantic schemas
- [ ] 26-03-PLAN.md — taxii_bundle.py (event->SDO, TLP predicate) + taxii_auth.py (partner key dependency)
- [ ] 26-04-PLAN.md — TAXII router (5 endpoints) + AuthMiddleware exemption + unit/integration tests green
- [ ] 26-05-PLAN.md — Admin CRUD API + /admin/taxii-clients React page (checkpoint)

### Phase 27: Sandbox + YARA
**Goal**: When a SHA256 IOC is created on a sandbox-enabled project, the platform fetches the sample, submits to the configured sandbox, persists the report, scans the sample with active YARA rules, and auto-tags the event with returned MITRE techniques and rule families.
**Depends on**: Phase 22 (IOC table is the trigger source), Phase 23 (provider-abstraction shape)
**Requirements**: SANDBOX-01, SANDBOX-02, SANDBOX-03, SANDBOX-04, SANDBOX-05, YARA-01, YARA-02, YARA-03
**Reuse points**:
  - Provider-abstraction shape from Phase 23 (`services/sandbox/{cuckoo,anyrun,joesandbox,hybridanalysis,triage}.py`)
  - `attack_technique_tags` write path for auto-tagging from sandbox MITRE output
  - AI worker async polling pattern (`workers/ai.py`) for sandbox-completion polling
  - Encrypted credentials pattern
**Pitfalls**:
  - Sandbox runs take 5–15 min — polling must not pin a worker; use scheduled re-poll actor with backoff
  - Free-tier sandboxes make submissions PUBLIC — UI must warn before enabling per project; default off
  - Sample fetch via VT Premium or MalwareBazaar may fail (sample not available); record `status='sample_unavailable'` rather than retrying forever
  - `yara-python` requires native YARA binary in worker container; add to Dockerfile and confirm hermetic build
  - `sandbox_reports` table grows large; TimescaleDB hypertable on `(submitted_at, event_id)`
**Success Criteria** (what must be TRUE):
  1. Project enables sandbox with API key; new SHA256 IOC triggers `submit_sample` actor; sample fetched from MalwareBazaar; submitted to provider; `sandbox_reports` row created with `status='pending'`
  2. Polling actor flips status to `complete`; event detail drawer renders Sandbox Report section with process tree, network IOCs, MITRE techniques
  3. ATT&CK techniques returned by sandbox auto-write into `attack_technique_tags` with `tag_source='auto'` and visible provenance in graph
  4. Admin uploads YARA rule via `/admin/yara-rules`; subsequent sample matching rule auto-tags event with rule name + family; STIX `pattern` strings at ingest also scanned and tagged
  5. Project with sandbox disabled shows no submission; new SHA256 IOC creation completes normally without external call
**OPSEC**: Per-project opt-in; UI banner "free-tier sandbox makes submissions public" before enable.
**Plans**: 7 plans
Plans:
- [x] 27-01-PLAN.md — Wave 0: test stubs (7 files) + Dockerfile libyara-dev + pyproject.toml yara-python
- [ ] 27-02-PLAN.md — Migration 028: sandbox_configs, sandbox_reports hypertable, yara_rules, yara_matches + ORM models + Pydantic schemas
- [ ] 27-03-PLAN.md — Sandbox provider modules (cuckoo, anyrun, joesandbox, hybridanalysis, triage) + sample_fetch.py + yara_engine.py
- [ ] 27-04-PLAN.md — YARA admin router + sandbox config router + main.py registration
- [ ] 27-05-PLAN.md — Sandbox submit + poll actors + broker queue + IOC ingest hook
- [ ] 27-06-PLAN.md — GET sandbox-report endpoint + STIX pattern YARA scan hook in TAXII ingest
- [ ] 27-07-PLAN.md — Frontend: YARA admin page + SandboxReportSection in EventDetailDrawer + api-client helpers (checkpoint)

### Phase 28: Passive DNS, WHOIS & Multi-hop Graph
**Goal**: Domain IOCs receive WHOIS + passive-DNS enrichment that powers shared-infrastructure pivots; the attack graph supports analyst-driven 1-3 hop traversal with cross-project isolation preserved.
**Depends on**: Phase 22 (IOC table), Phase 23 (provider plumbing), Phase 20 (project graph chokepoint)
**Requirements**: ENRICH-06, ENRICH-07, ENRICH-08, GRAPH-01, GRAPH-02, GRAPH-03, GRAPH-04
**Reuse points**:
  - Provider-abstraction shape from Phase 23
  - Apache AGE Cypher (deferred from v3.1 Phase 20 — finally adopted here)
  - Cytoscape canvas + `events_query.build_scope_predicate` chokepoint
  - `attack_technique_tags` join shape for `:DomainPivot` edge type
**Pitfalls**:
  - `MATCH (s)-[:SEEN_IN*1..3]->(t)` BFS can explode; hard cap traversal at 200 nodes per request
  - Cross-project isolation MUST hold across deeper paths — extend PROD-01 leakage tests to 2-hop and 3-hop assertions BEFORE shipping endpoint
  - WHOIS rate limits across providers vary wildly; 7-day cache TTL non-negotiable
  - Centrality computation (PageRank/betweenness) on >500-node graphs slows render; compute server-side and serialise per-node score
  - Migration adds AGE node label `:DomainPivot` + relationship `:SHARES_INFRA` — must be reversible
**Success Criteria** (what must be TRUE):
  1. Operator with SecurityTrails API key sees new domain IOC enriched with WHOIS within 60s; cached 7 days (re-fetch suppressed)
  2. Cytoscape graph renders `:DomainPivot` nodes connecting domains by shared registrar / registration email / historical IP for an actor's infrastructure cluster
  3. Right-click on a graph node → "Expand 1 hop" / "Expand 3 hops" / "Path to…"; `GET /api/projects/{id}/graph/traverse?seed=…&hops=3` returns bounded BFS as Cytoscape JSON
  4. Node size encodes centrality (PageRank score); larger nodes are more connected hubs
  5. PROD-01 leakage suite extended with 2-hop and 3-hop traversal assertions; zero cross-project nodes appear in any traversal
**OPSEC**: Provider opt-in per project; AGE Cypher queries pass through `build_scope_predicate` chokepoint.
**Plans**: 8 plans across 7 waves

Plans:
- [ ] 28-01-PLAN.md — DB migration: passive_dns_records, whois_cache, AGE labels, pyproject deps (wave 0)
- [ ] 28-02-PLAN.md — ORM models + GraphResponse schema extension (wave 1)
- [ ] 28-03-PLAN.md — Passive DNS provider modules (SecurityTrails/Mnemonic/RiskIQ) + WHOIS service (wave 2)
- [ ] 28-04-PLAN.md — AGE sync service: DomainPivot MERGE + SHARES_INFRA edges + worker wiring (wave 3)
- [ ] 28-05-PLAN.md — PROD-01 extension: 2-hop and 3-hop traverse isolation tests (wave 4, HARD GATE)
- [ ] 28-06-PLAN.md — Traverse endpoint GET /graph/traverse with centrality (wave 5)
- [ ] 28-07-PLAN.md — Frontend: context menu, DomainPivot styles, centrality sizing (wave 6)
- [ ] 28-08-PLAN.md — Integration tests: ENRICH-06/07/08 + traverse smoke tests (wave 6)

### Phase 29: Sigma Rule Engine
**Goal**: Operator can paste community Sigma rules and have every new event automatically tagged when it matches, with rule effectiveness testable against a sample window.
**Depends on**: Phase 22 (IOC table for IOC-based Sigma rules), Phase 25 (audit log captures rule changes)
**Requirements**: SIGMA-01, SIGMA-02, SIGMA-03, SIGMA-04
**Reuse points**:
  - `_persist_event_for_bindings` post-insert hook for rule eval
  - `attack_technique_tags` write path
  - `events_query` field shape for the field-mapping layer
**Pitfalls**:
  - Sigma is event-log-shaped; IntelliBird events have different fields — the field-mapping layer (SIGMA-04) is the load-bearing piece, not the rule engine itself
  - `pySigma` rule compilation can throw on malformed YAML — surface clear error in UI on paste
  - Per-event rule eval at ingest must not regress p95 latency; benchmark against current ~150ms budget
  - Rule disable must take effect immediately (no worker reload required)
**Success Criteria** (what must be TRUE):
  1. Admin pastes a Sigma YAML rule from SigmaHQ at `/admin/sigma-rules`; rule compiles and persists to `sigma_rules` table; UI tests rule against last-100-events sample and shows match count
  2. New event matching enabled rule receives auto-tag from rule's `tags[]` and bumps `tag_relevance` scoring component; provenance recorded with `tag_source='auto'`
  3. Admin disables a rule; subsequent events do not receive its tags within one ingest cycle
  4. Field-mapping layer translates Sigma fields (`title`, `description`, `raw_stix.objects[*].pattern`) to IntelliBird event shape; mapping documented in `docs/ops/sigma-mapping.md`
**Plans**: 6 plans
- [x] 29-01-PLAN.md — Wave 0 test scaffolding + pySigma dep
- [x] 29-02-PLAN.md — Migration 030, SigmaRule ORM model, Pydantic schemas
- [x] 29-03-PLAN.md — sigma_engine.py (parser + evaluator + tag writer) + sigma-mapping.md
- [x] 29-04-PLAN.md — Ingest hook: wire evaluate_sigma_rules into _persist_event
- [ ] 29-05-PLAN.md — Admin CRUD router (POST/GET/PATCH/DELETE/test) + main.py registration
- [ ] 29-06-PLAN.md — Frontend /admin/sigma-rules page + api-client.ts helpers

### Phase 30: Notification Channels
**Goal**: Admin can route alerts to email, PagerDuty, Opsgenie, and ntfy alongside existing Slack/Teams/Discord webhooks, reusing the existing dispatch pipeline.
**Depends on**: Phase 7 (webhook dispatcher), Phase 25 (audit log captures destination changes)
**Requirements**: NOTIF-01, NOTIF-02, NOTIF-03, NOTIF-04, NOTIF-05
**Reuse points**:
  - `services/webhook_dispatcher.py` batching, retry, burst-suppression
  - `webhook_destination_type` ENUM (extension)
  - `crypto.encrypt_credentials` for SMTP credentials
  - `--profile notify` compose precedent for self-hosted ntfy
**Pitfalls**:
  - SMTP via aiosmtplib must support STARTTLS + implicit TLS; many self-hosted SMTP relays use port 587/STARTTLS
  - PagerDuty Events API v2 dedup key must be stable per-event; auto-resolve when event archived
  - ntfy self-hosted requires compose service + topic auth token if private
  - Opsgenie + PagerDuty payload renderers must respect their respective severity mappings (S→P1, A→P2, etc.)
**Success Criteria** (what must be TRUE):
  1. Admin adds an email destination with SMTP credentials; S-tier event triggers email delivery via aiosmtplib within burst-suppression window; bounce → exponential backoff retry per existing webhook pattern
  2. Admin adds PagerDuty destination; new S-tier event creates incident; same event re-fired uses dedup key (no duplicate); event archive triggers auto-resolve
  3. Admin runs `docker compose --profile notify up`; ntfy service starts; ntfy destination publishes to topic; subscriber receives push notification
  4. Admin adds Opsgenie destination via Alert API; alert created on S-tier event; severity mapped per project rule overrides
  5. All 4 new destination types respect existing burst-suppression (5 HIGH/project/hour) and auto-disable after 5 consecutive failures
**Plans**: 7 plans
Plans:
- [ ] 30-01-PLAN.md — Wave 1: aiosmtplib dep + test stubs
- [ ] 30-02-PLAN.md — Wave 2: Migration 031 ENUM extension + Pydantic schema widening
- [ ] 30-03-PLAN.md — Wave 3: PagerDuty/Opsgenie/ntfy payload builders + GenieKey auth header
- [ ] 30-04-PLAN.md — Wave 4: _dispatch_email + email branch in _drain_and_dispatch + test-send guard
- [ ] 30-05-PLAN.md — Wave 5: PD routing_key body injection + PD auto-resolve hook in archiver
- [ ] 30-06-PLAN.md — Wave 5: ntfy compose service (docker-compose.yml)
- [ ] 30-07-PLAN.md — Wave 6: Frontend schema + WebhookDialog per-type credential sections (checkpoint)

### Phase 31: Case Management
**Goal**: Analysts can open cases, attach events and IOCs, track status through a kanban, and request AI roll-up summaries — without leaving IntelliBird for an external tool.
**Depends on**: Phase 22 (IOC table for `case_iocs` link), Phase 25 (audit log captures case mutations)
**Requirements**: CASE-01, CASE-02, CASE-03, CASE-04, CASE-05
**Reuse points**:
  - AI digest pattern (Phase 17) for "summarise case" actor on `ai` queue
  - Project-scoped RBAC from Phase 9
  - shadcn/ui drawer + table patterns
**Pitfalls**:
  - `case_events` link table must FK against the events hypertable as soft UUID (no hard FK to TimescaleDB hypertable — same precedent as `brand_matches.event_id`)
  - Activity log per case (CASE-03) overlaps with global audit log (Phase 25); decision: case activity log is a UI projection of audit_log filtered by `resource_type='case'`
  - Kanban drag-drop must batch status writes (avoid one PATCH per drag)
**Success Criteria** (what must be TRUE):
  1. Analyst opens a case at `/projects/{id}/cases/new`; assigns severity, assignee, summary; case appears in both kanban and table view
  2. Analyst attaches 10 events and 5 IOCs to the case via `case_events` and `case_iocs` link tables; case detail page renders linked items grouped by type
  3. Status transitions (open → in_progress → resolved → closed) appear in case activity log with user + timestamp; activity log surfaces audit_log rows filtered to this case
  4. Analyst clicks "AI Summarise"; `ai_summarise_case` actor produces narrative roll-up of all linked events; result cached on the case row
  5. Cross-project leakage tests confirm Observer in Project A cannot read Project B's cases
**Plans**: 7 plans
- [ ] 31-01-PLAN.md — Wave 0 test scaffold (test_cases_crud.py stubs + leakage test stub)
- [ ] 31-02-PLAN.md — Migration 032_cases + ORM models + Pydantic schemas
- [ ] 31-03-PLAN.md — Cases router (CRUD + evidence attach + AI summarise trigger) + main.py registration
- [ ] 31-04-PLAN.md — ai_summarise_case actor in ai.py (poll-based, writes cases.summary_md)
- [ ] 31-05-PLAN.md — Implement test bodies (6 CRUD tests green + test_case_isolation green)
- [ ] 31-06-PLAN.md — Frontend kanban + table view (@dnd-kit/core + 5 new files)
- [ ] 31-07-PLAN.md — Case detail page + api-client helpers + ProjectTabs Cases tab

### Phase 32: CertStream + MISP
**Goal**: Brand monitoring upgrades from 15-min crt.sh polling to sub-second CertStream WebSocket; MISP integration adds bidirectional sync (pull attributes as IOCs, push validated AI suggestions as proposals).
**Depends on**: Phase 22 (IOC table is MISP attribute target), Phase 25 (threat_actors table is MISP galaxy target), Phase 12 (brand monitor)
**Requirements**: CERT-01, CERT-02, CERT-03, MISP-01, MISP-02, MISP-03, MISP-04
**Reuse points**:
  - `brand_monitor` worker for CertStream filter integration
  - `threat_actors` table from Phase 25 for MISP galaxy mapping
  - `iocs` table for MISP attribute persistence
  - AI suggestion staging pattern for MISP push opt-in
**Pitfalls**:
  - CertStream WebSocket disconnects frequently — must auto-reconnect with backoff; persist last cursor if available
  - dnstwist patterns must be loaded into the WebSocket filter at connect time AND re-loaded on project edit (no missed window)
  - PyMISP push must be opt-in per suggestion type; never auto-push unvalidated AI extractions
  - MISP galaxy → `threat_actors` mapping must dedupe on `mitre_group_id` to avoid duplicate APT29 entries
**Success Criteria** (what must be TRUE):
  1. Operator runs `certstream_worker` (or compose service); WebSocket connects to `wss://certstream.calidog.io`; CT log entries matching project dnstwist patterns persist as brand-monitor events with `tag_source='certstream'` within 2 seconds of CA logging
  2. Operator can disable 15-min `crt.sh` poll (CertStream replaces) OR run both for redundancy; UI surfaces both modes
  3. Admin configures MISP URL + API key per project; PyMISP pulls attributes by tag/galaxy; attributes persist as rows in the `iocs` table (Phase 22)
  4. Validated AI suggestion (e.g. confirmed CVE) can be pushed to MISP as a proposal via per-suggestion-type opt-in toggle
  5. MISP galaxy clusters mapped → `threat_actors` rows; duplicate detection by `mitre_group_id` prevents catalog pollution
**OPSEC**: MISP push opt-in per suggestion type; CertStream uses public service (no key required) but operator may self-host.
**Plans**: 6 plans
Plans:
- [x] 32-01-PLAN.md — Wave 0 test scaffolding (6 unit stub files)
- [x] 32-02-PLAN.md — Migration 033, MispConfig ORM, pymisp dep, ENUM extensions
- [x] 32-03-PLAN.md — CertStream worker + brand_monitor guard + docker-compose service
- [x] 32-04-PLAN.md — MISP pull job + push actor + scheduler + ai.py hook
- [x] 32-05-PLAN.md — MISP CRUD router + Pydantic schemas + main.py registration
- [x] 32-06-PLAN.md — Frontend CT Log Mode selector + MISP settings section (checkpoint)

### Phase 33: Disinformation + Pattern-of-Life Timeline
**Goal**: Counter-disinformation tradecraft via Mastodon/4chan/Reddit social listening with CIB heuristics, plus a temporal timeline view exposing actor operational rhythm.
**Depends on**: Phase 25 (threat_actors for narrative attribution), Phase 17 (AI suggestion pipeline for narrative classification)
**Requirements**: DISINFO-01, DISINFO-02, DISINFO-03, DISINFO-04, TIMELINE-01, TIMELINE-02, TIMELINE-03
**Reuse points**:
  - Worker pattern from RSS / TAXII workers
  - `_persist_event_for_bindings` for fan-out
  - AI suggestion prompt extension shape from Phase 17
  - `events_query.py` filters for timeline view
  - Recharts (already used elsewhere in project widgets)
**Pitfalls**:
  - Mastodon firehose can be high-volume; per-instance rate-limit + per-project topic filter required
  - CIB MinHash similarity needs a vector store or brute-force comparison window — start with brute-force last-N-posts then optimise
  - Twitter/X API now paid — default ship without; document opt-in path
  - Timeline view must respect project scope predicate; do not leak cross-project event timestamps
**Success Criteria** (what must be TRUE):
  1. Operator adds Mastodon firehose source; posts ingest as events with `source_type='social_listening'`
  2. CIB detector flags clusters where N≥5 accounts post template-similar content within 5-minute window; clusters surface in `/dashboard` "Influence Operations" widget with account-age + synchrony evidence
  3. AI suggestion path classifies social events as `narrative_op` and extracts claim/amplifier/audience triple
  4. Operator visits `/projects/{id}/timeline`; sees stacked area chart of events by tag/actor over time AND hour-of-day × day-of-week heatmap; both respect existing `events_query` filters (project scope, dashboard role, tier, tags)
  5. Cross-project leakage tests cover the timeline endpoint
**OPSEC**: Twitter/X paid integration off by default; Mastodon firehose opt-in per project.
**Plans**: 7 plans

Plans:
- [ ] 33-01-PLAN.md — Wave 0 test scaffolds for all Phase 33 test targets
- [ ] 33-02-PLAN.md — DB migration: feed_type_enum extension, source_config column, cib_clusters table, new deps
- [ ] 33-03-PLAN.md — Social listening worker (Mastodon/4chan/Reddit) + APScheduler registration
- [ ] 33-04-PLAN.md — CIB detector (MinHashLSH) + AI narrative_op extension + GET /api/projects/{id}/cib-clusters endpoint
- [ ] 33-05-PLAN.md — Timeline API router (/series + /heatmap endpoints)
- [ ] 33-06-PLAN.md — Timeline frontend page + Influence Ops widget (BlueWidgets injection) + ProjectTabs update
- [ ] 33-07-PLAN.md — Full backend test sweep + human verify checkpoint

### Phase 34: Browser Extension
**Goal**: Analyst working in any external tool can right-click selected text and pivot to IntelliBird IOC search in one click.
**Depends on**: Phase 22 (`/iocs` search endpoint exists)
**Requirements**: EXT-01, EXT-02, EXT-03
**Reuse points**:
  - Existing operator session cookie + Auth.js v5 session
  - `GET /api/iocs?value={text}` endpoint from Phase 22
**Pitfalls**:
  - Manifest V3 service worker model differs from V2 background pages — context menu registration uses `chrome.contextMenus.create` in service worker
  - CORS / cookie scope must work across operator's IntelliBird origin; if Caddy edge is on `localhost`, extension must allow that origin
  - Not Chrome Store target — distribute as zip; document manual load
**Success Criteria** (what must be TRUE):
  1. Operator loads the extension zip from `/docs/ops/browser-extension/` into Chrome/Firefox/Edge dev mode
  2. Operator selects an IP address on any webpage; right-click menu shows "Lookup in IntelliBird"; click opens new tab to `/iocs?value=<ip>` pre-filtered with operator's existing session
  3. Documentation at `/docs/ops/browser-extension/README.md` covers install, origin allowlist config, and uninstall
**OPSEC**: Operator-loaded only; not published to web stores; no telemetry.
**Plans**: 4 plans
Plans:
- [x] 34-01-PLAN.md — Wave 0 test stubs (IOCsGlobalClient.test.tsx + background.test.js, Red phase)
- [ ] 34-02-PLAN.md — Browser extension files (manifest.json, background.js, options, icons, polyfill)
- [ ] 34-03-PLAN.md — Global /iocs Next.js page (RSC + IOCsGlobalClient + TopNav link)
- [ ] 34-04-PLAN.md — Distribution zip + operator README + human verification checkpoint

## Coverage

✅ All 80 v4.0 requirements mapped to exactly one phase. No orphans, no duplicates.

| REQ-ID range | Phase |
|---|---|
| IOC-01..08 | Phase 22 |
| ENRICH-01..05 | Phase 23 |
| DARK-01..07 | Phase 24 |
| ACTOR-01..06, AUDIT-01..03 | Phase 25 |
| TAXII-01..05 | Phase 26 |
| SANDBOX-01..05, YARA-01..03 | Phase 27 |
| ENRICH-06..08, GRAPH-01..04 | Phase 28 |
| SIGMA-01..04 | Phase 29 |
| NOTIF-01..05 | Phase 30 |
| CASE-01..05 | Phase 31 |
| CERT-01..03, MISP-01..04 | Phase 32 |
| DISINFO-01..04, TIMELINE-01..03 | Phase 33 |
| EXT-01..03 | Phase 34 |

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1-21 | v1.5–v3.1 | — | Complete | 2026-04-29 |
| 22. IOC Foundation | 5/6 | Complete    | 2026-05-03 | - |
| 23. IOC Enrichment APIs | 6/6 | Complete    | 2026-05-03 | - |
| 24. Dark-Web Collection | 4/7 | In Progress|  | - |
| 25. Threat Actors, Campaigns & Audit Log | 6/6 | Complete   | 2026-05-03 | - |
| 26. TAXII Outbound Server | 5/5 | Complete   | 2026-05-03 | - |
| 27. Sandbox + YARA | 7/7 | Complete    | 2026-05-04 | - |
| 28. Passive DNS, WHOIS & Multi-hop Graph | 8/8 | Complete    | 2026-05-04 | - |
| 29. Sigma Rule Engine | 6/6 | Complete    | 2026-05-04 | - |
| 30. Notification Channels | 8/8 | Complete    | 2026-05-04 | - |
| 31. Case Management | 7/7 | Complete   | 2026-05-04 | - |
| 32. CertStream + MISP | 6/6 | Complete | 2026-05-06 | - |
| 33. Disinformation + Pattern-of-Life Timeline | 3/7 | In Progress|  | - |
| 34. Browser Extension | v4.0 | 1/4 | In Progress | - |

---
*Last updated: 2026-05-04 — Phase 30 planned (7 plans, 6 waves)*

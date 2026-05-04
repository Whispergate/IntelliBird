# Requirements: IntelliBird v4.0 — Threat Intelligence Platform Maturity

**Defined:** 2026-05-02
**Source plan:** `/home/lavender/.claude/plans/please-find-points-vast-hearth.md`
**Core Value:** A single operator can see the current cyber threat landscape — world events, actor activity, CVEs, feed signal — in one place, filter and tag it, and drill from a geo view into the attack graph behind any event.

## v4.0 Requirements

### Tier 1 — Atomic IOC management (foundation for everything else)

- [x] **IOC-01**: User can store atomic indicators (IP, IPv6, domain, URL, sha256, sha1, md5, email, btc, eth, mutex, registry_key, filename) in a dedicated `iocs` table with normalised value, first/last seen, source, confidence, TTL.
- [x] **IOC-02**: User can bulk-import IOCs via CSV, JSON, or STIX 2.1 bundle through `POST /api/iocs/bulk-import`.
- [x] **IOC-03**: User can search IOCs across all events by value or normalised value via `GET /api/iocs?type=ip&value=…` (cross-project for Admin, project-scoped otherwise).
- [x] **IOC-04**: User can mark an IOC as whitelisted (false-positive suppression) via `POST /api/iocs/{id}/whitelist`.
- [x] **IOC-05**: System automatically expires IOCs whose `last_seen + ttl_days < NOW()` via daily scheduler job; expired IOCs hidden from default queries but retained.
- [x] **IOC-06**: User can view per-project IOCs in a sortable table tab on the project page (filter by type, age, confidence, status).
- [x] **IOC-07**: System backfills `iocs` table from existing `events.tags[]` IOC strings on first migration apply.
- [x] **IOC-08**: M2M `ioc_event_links` table records every event referencing each IOC, enabling cross-event pivots.

### Tier 1 — IOC enrichment integrations

- [x] **ENRICH-01**: Admin can configure per-project (or global) API keys for VirusTotal, AbuseIPDB, GreyNoise, OTX direct, Shodan, URLhaus through encrypted settings (reuses `crypto.encrypt_credentials`).
- [x] **ENRICH-02**: System auto-enriches every newly-created IOC against enabled providers via async worker actor `enrich_ioc`; results stored in `ioc_enrichments` table (one row per provider).
- [x] **ENRICH-03**: System honours per-provider quota limits via Redis rolling-window counter (e.g. VT free tier 4 req/min) with circuit-breaker abort on repeated quota exhaust.
- [x] **ENRICH-04**: User can view IOC enrichment results in event detail drawer (reputation badges: clean/suspicious/malicious/unknown + provider attribution + pivot links).
- [x] **ENRICH-05**: System caches enrichment results in Redis (`enrich:{provider}:{indicator}` TTL 24h) to respect free-tier quotas.
- [ ] **ENRICH-06**: Admin can configure passive DNS providers (SecurityTrails, Mnemonic PassiveTotal, RiskIQ Community) with same provider-abstraction pattern as §ENRICH-01.
- [ ] **ENRICH-07**: System enriches each new domain IOC with WHOIS registration data cached for 7 days.
- [ ] **ENRICH-08**: Cytoscape graph adds `:DomainPivot` node type connecting domains by shared registrar / registration email / historical IP for infrastructure clustering.

### Tier 1 — Dark-web / paste / Telegram collection

- [x] **DARK-01**: System runs a dedicated Tor SOCKS5 proxy compose service (profile `darkweb`) isolated from EASM and operator egress.
- [x] **DARK-02**: User can add `tor_html` source type that scrapes `.onion` HTML through the Tor proxy with per-source crawl depth.
- [x] **DARK-03**: User can add `paste` source type ingesting from ghostbin, paste.ee, paste.rs, dpaste, controld, rentry through their RSS or scrapable index.
- [x] **DARK-04**: User can add `telegram` source type ingesting public Telegram channel posts via Telethon (read-only API key + burner number).
- [x] **DARK-05**: System auto-extracts `.onion` URLs, victim-name candidates, BTC wallets, and credential pair patterns (`email:hash`, `email:plaintext`) from dark-web event content.
- [x] **DARK-06**: Dark-web sources default to `confidence=0.4` (lower than RSS=0.7) so noise does not auto-promote to high-tier alerts; analyst tagging promotes confidence.
- [x] **DARK-07**: UI surfaces a "data exfiltration risk" warning on dark-web source forms; operator must explicitly authorise each `.onion` URL or Telegram channel.

### Tier 1 — Sandbox / file-detonation

- [x] **SANDBOX-01**: Admin can configure per-project sandbox provider (Cuckoo, ANY.RUN, Joe Sandbox, Hybrid Analysis, Triage) with API key encrypted via existing crypto pattern.
- [x] **SANDBOX-02**: System auto-fetches file samples by SHA256 (from VirusTotal Premium or MalwareBazaar) and submits to configured sandbox when a new `iocs.type='sha256'` is created AND project has `sandbox_enabled=true`.
- [x] **SANDBOX-03**: System polls sandbox for completion and stores result in `sandbox_reports` table linked to event.
- [x] **SANDBOX-04**: Event detail drawer shows "Sandbox Report" section (process tree, network IOCs, MITRE techniques) when available.
- [x] **SANDBOX-05**: System auto-tags event with ATT&CK techniques returned by sandbox output (`tag_source='auto'` via existing `attack_technique_tags` write path).

### Tier 2 — TAXII outbound server

- [x] **TAXII-01**: System exposes a TAXII 2.1 discovery endpoint at `GET /taxii2/` per spec.
- [x] **TAXII-02**: System exposes paginated `GET /taxii2/api/collections/` and `GET /taxii2/api/collections/{id}/objects/` returning STIX 2.1 bundles of project events as indicator/observed-data SDOs.
- [x] **TAXII-03**: Admin can issue per-partner API keys via `taxii_clients` table; rate-limited per key; revocable.
- [x] **TAXII-04**: Each project exposes one read-only TAXII collection auto-mapped to its events; per-collection ACL gates AMBER/RED TLP markings.
- [x] **TAXII-05**: Response Content-Type strictly `application/taxii+json;version=2.1`; per-request page cap 100 objects.

### Tier 2 — Global threat-actors + campaigns

- [x] **ACTOR-01**: System stores global `threat_actors` table (id, primary_name, aliases TEXT[], country, motivation, sophistication, first_seen, profile_md, mitre_group_id) surviving across engagements.
- [x] **ACTOR-02**: System bootstraps actor catalog from MITRE ATT&CK `intrusion-set` STIX objects (extends existing `bootstrap_attack` pull).
- [x] **ACTOR-03**: System stores `campaigns` table (id, name, actor_id FK nullable, start_date, end_date, summary_md, project_id NULL=global) with M2M `campaign_events` link.
- [x] **ACTOR-04**: AI suggestion-extraction path auto-links extracted `actor_names[]` to existing `threat_actors` rows via fuzzy alias match; unknown actors stage as pending suggestions.
- [x] **ACTOR-05**: User can browse `/actors` route — actor list, profile pages with timeline of associated events, Cytoscape sub-graph centred on actor.
- [x] **ACTOR-06**: User can manually create + edit actor profiles (Lead+ role); link/unlink campaigns + events from profile UI.

### Tier 2 — Multi-hop graph traversal

- [ ] **GRAPH-01**: System exposes `GET /api/projects/{id}/graph/traverse?seed={id}&hops={1-3}&edge_filter[]=…` returning bounded BFS via AGE Cypher (`MATCH (s)-[:SEEN_IN*1..3]->(t)`).
- [ ] **GRAPH-02**: Cytoscape canvas adds right-click context menu: "Expand 1 hop" / "Expand 3 hops" / "Path to…" (analyst-driven exploration).
- [ ] **GRAPH-03**: System computes node centrality (PageRank, betweenness) via Cytoscape built-in algorithms; UI encodes centrality as node size.
- [ ] **GRAPH-04**: Multi-hop traversal preserves cross-project isolation (PROD-01 leakage tests still pass against deeper paths).

### Tier 2 — Sigma rule engine

- [ ] **SIGMA-01**: System ingests Sigma YAML rules into `sigma_rules` table (per-project or global, level, tags[], enabled toggle) via `pySigma` library.
- [ ] **SIGMA-02**: System evaluates each new event against active rule set after `_persist_event_for_bindings`; matches inject auto-tags + bump `tag_relevance` score component.
- [ ] **SIGMA-03**: Admin UI at `/admin/sigma-rules` lets operator paste/upload Sigma YAML, test against last-100-events sample, enable/disable.
- [ ] **SIGMA-04**: System provides a Sigma-field-mapping layer translating Sigma fields (`title`, `description`, `raw_stix.objects[*].pattern`) to IntelliBird event shape.

### Tier 2 — Notification channels (email + PagerDuty + ntfy)

- [ ] **NOTIF-01**: `webhook_destination_type` ENUM extended with `email`, `pagerduty`, `opsgenie`, `ntfy`.
- [ ] **NOTIF-02**: Admin can add email destination (SMTP via aiosmtplib; SMTP_HOST/USER encrypted in `app_settings`); reuse webhook batching, retry, burst-suppression.
- [ ] **NOTIF-03**: Admin can add PagerDuty Events API v2 destination; map S-tier event to incident create / dedup / auto-resolve.
- [ ] **NOTIF-04**: Admin can add ntfy.sh destination publishing to topic (self-hosted ntfy compose service profile `notify`).
- [ ] **NOTIF-05**: Admin can add Opsgenie destination via Alert API.

### Tier 2 — Lightweight case management

- [ ] **CASE-01**: System stores `cases` table (id, project_id, title, status ENUM(open, in_progress, on_hold, resolved, closed), severity, assignee_user_sub, opened_at, closed_at, summary_md).
- [ ] **CASE-02**: M2M `case_events` and `case_iocs` link tables enable analyst to attach evidence to a case.
- [ ] **CASE-03**: Per-case activity log records notes + status transitions (also satisfies audit trail for case workflow).
- [ ] **CASE-04**: User can browse `/projects/{id}/cases` route in both kanban and table view; filter by status/severity/assignee.
- [ ] **CASE-05**: AI "summarise case" actor produces narrative roll-up of all linked events (reuses existing digest pattern).

### Tier 3 — Audit log

- [x] **AUDIT-01**: System stores `audit_log` TimescaleDB hypertable (time, user_sub, action, resource_type, resource_id, project_id, before_jsonb, after_jsonb, request_id) with same retention pattern as `events`.
- [x] **AUDIT-02**: FastAPI middleware logs all non-GET requests after dependency resolution; includes user, resource, before/after diff for mutations.
- [x] **AUDIT-03**: Admin can browse `/admin/audit` UI filtered by user / resource type / date range; read-only.

### Tier 3 — CertStream realtime cert transparency

- [ ] **CERT-01**: System runs `certstream_worker` connecting to `wss://certstream.calidog.io` (or self-hosted CertStream) filtering domains via dnstwist patterns already loaded per project.
- [ ] **CERT-02**: CertStream hits persist as brand-monitor events with `tag_source='certstream'`.
- [ ] **CERT-03**: Operator can disable 15-min `crt.sh` poll OR run alongside CertStream for redundancy.

### Tier 3 — MISP direct API (PyMISP)

- [ ] **MISP-01**: Admin can configure MISP instance URL + API key per project; encrypted credentials.
- [ ] **MISP-02**: System pulls MISP attributes by tag/galaxy via PyMISP and persists as IOCs (reuses §IOC-01 table).
- [ ] **MISP-03**: System can push validated `ai_suggestions` to MISP as proposals via PyMISP push (operator opt-in per suggestion type).
- [ ] **MISP-04**: System maps MISP galaxy clusters → IntelliBird `threat_actors` (reuses §ACTOR-01 table).

### Tier 3 — Disinformation / CIB detection

- [ ] **DISINFO-01**: System adds `social_listening` source type ingesting from Mastodon firehose (free) + 4chan/Reddit (free); paid Twitter/X opt-in.
- [ ] **DISINFO-02**: Heuristic detector flags Coordinated Inauthentic Behaviour: account-age clustering, post-time synchrony |Δt|<5min across N accounts, MinHash template-text similarity.
- [ ] **DISINFO-03**: AI suggestion prompt extended to classify event as `narrative_op` and extract claim/amplifier/audience triple.
- [ ] **DISINFO-04**: Dashboard adds "Influence Operations" widget showing recent CIB clusters + narrative themes.

### Tier 3 — Pattern-of-life timeline view

- [ ] **TIMELINE-01**: User can browse `/projects/{id}/timeline` showing stacked area chart of events by tag/actor over time.
- [ ] **TIMELINE-02**: Same page renders heatmap of activity by hour-of-day × day-of-week (detect operational-rhythm signatures).
- [ ] **TIMELINE-03**: Timeline reuses existing `events_query.py` filters (project scope, dashboard role, tier, tags).

### Tier 3 — YARA rule scanning

- [x] **YARA-01**: Admin can store YARA rules in `yara_rules` table (per-project or global, enabled toggle) via `yara-python` library.
- [x] **YARA-02**: System scans file samples fetched by sandbox provider (§SANDBOX-02) against active YARA rules; matches auto-tag event with rule name + family.
- [x] **YARA-03**: System scans `events.raw_stix` `pattern` strings against active YARA rules at ingest.

### Tier 3 — Browser extension for analyst pivoting

- [ ] **EXT-01**: System ships a Manifest V3 browser extension (Chrome/Firefox/Edge) that adds right-click "Lookup in IntelliBird" on any selected text.
- [ ] **EXT-02**: Selected text routes to `/iocs?value={text}` opening pre-filtered IOC search in new tab with operator's existing session cookie.
- [ ] **EXT-03**: Extension distributed as zip in `/docs/ops/browser-extension/`; not Chrome Store target — operator-loaded only.

## Future Requirements (deferred)

| Feature | Reason |
|---|---|
| Real-time chat / collaboration on cases | Out of TIP scope; operator uses Slack/Mattermost |
| Mobile app | Web-first per CLAUDE.md; no mobile SOC use case identified |
| Multi-region HA / clustered deployment | Single-host Docker Compose per CLAUDE.md constraint |
| Custom report templates beyond TIBER | TIBER + CBEST shipped; per-engagement custom templates demand-driven |
| Hosted SaaS offering | Self-hosted only per project constitution |

## Out of Scope

| Feature | Reason |
|---|---|
| Active offensive tooling integration (C2, payload generation) | IntelliBird is intel platform; offensive work belongs in red-team toolkits, not TIP |
| Built-in vulnerability scanning beyond BBOT EASM | Existing EASM via BBOT subprocess is sufficient; deeper scanning belongs in dedicated scanner (Nessus, Nuclei) |
| Mass cred-stuffing / takedown automation | Legal liability + OPSEC risk too high for self-hosted operator tool |
| Direct social-platform takedown / report submission | Out of intel-cell role; legal/PR teams handle takedowns |
| Hosted dark-web crawler-as-a-service | Intel Owl / DarkOwl / Recorded Future commercial coverage; build only the local-collection harness |

## Traceability

Filled by `gsd-roadmapper` 2026-05-03. Every v4.0 requirement maps to exactly one phase.

| Requirement | Phase | Status |
|---|---|---|
| IOC-01 | Phase 22 | Complete |
| IOC-02 | Phase 22 | Complete |
| IOC-03 | Phase 22 | Complete |
| IOC-04 | Phase 22 | Complete |
| IOC-05 | Phase 22 | Complete |
| IOC-06 | Phase 22 | Complete |
| IOC-07 | Phase 22 | Complete |
| IOC-08 | Phase 22 | Complete |
| ENRICH-01 | Phase 23 | Complete |
| ENRICH-02 | Phase 23 | Complete |
| ENRICH-03 | Phase 23 | Complete |
| ENRICH-04 | Phase 23 | Complete |
| ENRICH-05 | Phase 23 | Complete |
| ENRICH-06 | Phase 28 | Pending |
| ENRICH-07 | Phase 28 | Pending |
| ENRICH-08 | Phase 28 | Pending |
| DARK-01 | Phase 24 | Complete |
| DARK-02 | Phase 24 | Complete |
| DARK-03 | Phase 24 | Complete |
| DARK-04 | Phase 24 | Complete |
| DARK-05 | Phase 24 | Complete |
| DARK-06 | Phase 24 | Complete |
| DARK-07 | Phase 24 | Complete |
| SANDBOX-01 | Phase 27 | Complete |
| SANDBOX-02 | Phase 27 | Complete |
| SANDBOX-03 | Phase 27 | Complete |
| SANDBOX-04 | Phase 27 | Complete |
| SANDBOX-05 | Phase 27 | Complete |
| TAXII-01 | Phase 26 | Complete |
| TAXII-02 | Phase 26 | Complete |
| TAXII-03 | Phase 26 | Complete |
| TAXII-04 | Phase 26 | Complete |
| TAXII-05 | Phase 26 | Complete |
| ACTOR-01 | Phase 25 | Complete (25-02) |
| ACTOR-02 | Phase 25 | Complete |
| ACTOR-03 | Phase 25 | Complete (25-02) |
| ACTOR-04 | Phase 25 | Complete |
| ACTOR-05 | Phase 25 | Complete |
| ACTOR-06 | Phase 25 | Complete |
| GRAPH-01 | Phase 28 | Pending |
| GRAPH-02 | Phase 28 | Pending |
| GRAPH-03 | Phase 28 | Pending |
| GRAPH-04 | Phase 28 | Pending |
| SIGMA-01 | Phase 29 | Pending |
| SIGMA-02 | Phase 29 | Pending |
| SIGMA-03 | Phase 29 | Pending |
| SIGMA-04 | Phase 29 | Pending |
| NOTIF-01 | Phase 30 | Pending |
| NOTIF-02 | Phase 30 | Pending |
| NOTIF-03 | Phase 30 | Pending |
| NOTIF-04 | Phase 30 | Pending |
| NOTIF-05 | Phase 30 | Pending |
| CASE-01 | Phase 31 | Pending |
| CASE-02 | Phase 31 | Pending |
| CASE-03 | Phase 31 | Pending |
| CASE-04 | Phase 31 | Pending |
| CASE-05 | Phase 31 | Pending |
| AUDIT-01 | Phase 25 | Complete (25-02) |
| AUDIT-02 | Phase 25 | Complete (25-02) |
| AUDIT-03 | Phase 25 | Complete |
| CERT-01 | Phase 32 | Pending |
| CERT-02 | Phase 32 | Pending |
| CERT-03 | Phase 32 | Pending |
| MISP-01 | Phase 32 | Pending |
| MISP-02 | Phase 32 | Pending |
| MISP-03 | Phase 32 | Pending |
| MISP-04 | Phase 32 | Pending |
| DISINFO-01 | Phase 33 | Pending |
| DISINFO-02 | Phase 33 | Pending |
| DISINFO-03 | Phase 33 | Pending |
| DISINFO-04 | Phase 33 | Pending |
| TIMELINE-01 | Phase 33 | Pending |
| TIMELINE-02 | Phase 33 | Pending |
| TIMELINE-03 | Phase 33 | Pending |
| YARA-01 | Phase 27 | Complete |
| YARA-02 | Phase 27 | Complete |
| YARA-03 | Phase 27 | Complete |
| EXT-01 | Phase 34 | Pending |
| EXT-02 | Phase 34 | Pending |
| EXT-03 | Phase 34 | Pending |

**Coverage:**
- v4.0 requirements: 80 total (across 17 features / 3 tiers)
- Mapped to phases: 80 ✓
- Unmapped: 0
- Phases: 13 (Phase 22 — Phase 34)

---
*Requirements defined: 2026-05-02*
*Last updated: 2026-05-02 — initial v4.0 milestone definition*

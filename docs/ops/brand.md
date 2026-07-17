# IntelliBird Brand Protection Operator Runbook

**Applies to:** IntelliBird v2.0+ (shipped)
**dnstwist version pinned:** `dnstwist>=20240219` (verified shape against `dnstwist 20250130`, see `docs/research/dnstwist-key-verification.md`)

**Related:**
- `ops/.env.example` — all `BRAND_*` keys
- `ops/docker-compose.yml` — `worker` service `--queues` list (brand-monitor co-located)
- `docs/ops/easm.md` — EASM runbook (sibling subsystem — contrast docker.sock model)
- `docs/ops/projects.md` — project authority matrix (brand terms CRUD follow same rules)
- `docs/ops/auth-setup.md` — Authentik setup (Lead/Admin roles gate term CRUD)
- `backend/app/services/brand_stoplist.py` — DEFAULT_STOPLIST constant (sole source of truth)
- `backend/app/workers/brand.py` — `brand_monitor_scan_project` Dramatiq actor
- `backend/app/scheduler/jobs.py` — four `brand_*` APScheduler jobs

---

## Table of Contents

1. [Overview](#1-overview)
2. [Environment Configuration](#2-environment-configuration)
3. [Stoplist Management](#3-stoplist-management)
4. [GDPR Retention](#4-gdpr-retention-l-3-closure)
5. [crt.sh Rate Limiting](#5-crtsh-rate-limiting-h-6-closure)
6. [dnstwist Subprocess](#6-dnstwist-subprocess-m-8-closure)
7. [Noise Downgrade](#7-noise-downgrade-h-5-closure)
8. [Dismissal Lifecycle](#8-dismissal-lifecycle-m-5-closure)
9. [Webhook Reuse](#9-webhook-reuse-brp-05)
10. [Scheduler Job Catalogue](#10-scheduler-job-catalogue)
11. [Queue and Worker Topology](#11-queue-and-worker-topology)
12. [Upgrade Procedure](#12-upgrade-procedure)
13. [Troubleshooting](#13-troubleshooting)
14. [Deferred Items](#14-deferred-items)
15. [Cross-References](#15-cross-references)

---

## 1. Overview

Per-project brand-term monitoring. Operators register brand terms (keyword, domain, product, or person strings) on a project's Brand tab; the `brand_monitor_scan_project` Dramatiq actor scans three sources per term on every tick:

| Source | What it does | Severity |
|---|---|---|
| **Events FTS** (`pg_trgm`) | Trigram search against the events table `title` + `stix_id` columns | `low` |
| **crt.sh CT logs** | Certificate transparency lookups for `%.{term}` | `medium` |
| **dnstwist lookalikes** | Permutation engine against `{term}` with live DNS resolution | `high` (only when DNS resolved) / `low` (ServFail/empty) |

The scheduler fires `brand_monitor_tick` on an APScheduler IntervalTrigger (default 15 min) which enqueues one `brand_monitor_scan_project.send(project_id)` call per non-archived project on the dedicated `brand-monitor` Dramatiq queue.

**HIGH-severity matches synthesise a canonical event** via `backend/app/services/brand_synth.py` with `source_type='brand-monitor'` and tags `['brand-match', 'brand-match:high', 'brand-match:{source}', 'project:{id}']`. The **existing M1 `webhook_dispatch_tick`** from picks these up through tag-based preset subscriptions — **zero new webhook code was added in ** (BRP-05 closure).

Architectural contrast with EASM: Brand Protection runs entirely **in-process** (pure-Python `dnstwist` + `httpx`). No docker.sock mount, no ephemeral container lifecycle, no elevated privileges. The `brand-monitor` queue is co-located on the shared `worker` container alongside `ingest`, `maintenance`, and `webhooks`.

---

## 2. Environment Configuration

All keys are set in `ops/.env` and read via Pydantic Settings in `backend/app/config.py`. Never use `os.environ.get()` at runtime — always go through the settings singleton.

| Env var | Default | Purpose |
|---|---|---|
| `BRAND_STOPLIST_EXTRA` | (empty) | Comma-separated extra stoplist words; unioned with `DEFAULT_STOPLIST` at call-time via `load_runtime_stoplist()` |
| `BRAND_NOISE_THRESHOLD` | `100` | Matches/24h that auto-downgrade a term to `watch_only` (H-5) |
| `BRAND_WEBHOOK_SEVERITY_THRESHOLD` | `HIGH` | `HIGH` or `MEDIUM` — threshold for synth + webhook firing (Literal-typed for compile-time safety) |
| `BRAND_MONITOR_INTERVAL_SECONDS` | `900` | APScheduler interval for `brand_monitor_tick` (15 minutes) |

To apply a change:

```bash
# Edit ops/.env, then restart worker + scheduler
docker compose up -d --force-recreate worker scheduler
```

> **Note:** The `worker` container consumes the `brand-monitor` queue. The `scheduler` container fires `brand_monitor_tick`. Both need a restart to pick up env changes. The `api` container does not need restart unless env keys are read in request paths (they are not in).

---

## 3. Stoplist Management

The `DEFAULT_STOPLIST` is a `frozenset[str]` code constant defined in `backend/app/services/brand_stoplist.py` — **224 entries** across four categories (common short English, generic product/brand, action/state, common tech). This is well over the CONTEXT.md target of ~150 entries. All entries are lowercase; the test suite asserts this.

**Matching semantics:**

- `is_stoplisted(value)` strips whitespace, lowercases the input, then does a membership test against the runtime stoplist (DEFAULT ∪ `BRAND_STOPLIST_EXTRA`).
- `is_short(value)` returns `len(stripped) < 6` — short terms are noise-prone even when not in the stoplist.
- Terms on the stoplist are **ACCEPTED** by the term-validation endpoint but flagged `high_noise_risk=true`. The UI surfaces this as an amber warning and the monitor restricts FTS scope to `title+stix_id` only (no full-text body sweep).

**Operator additions** (deployment-global):

```bash
# In ops/.env — comma-separated, whitespace-tolerant
BRAND_STOPLIST_EXTRA=myproduct,example,internal

docker compose up -d --force-recreate worker scheduler
```

The extra set is unioned with `DEFAULT_STOPLIST` at every `load_runtime_stoplist()` call. No code change is required to add exclusions. No container rebuild is required.

**Per-project editable stoplist is DEFERRED to v2.1** (see §14 Deferred Items and `12-CONTEXT.md §Deferred Ideas`). In v2.0 the stoplist is global; per-project escape hatches can be achieved by crafting more specific term values (longer, more unique) rather than adding shorter terms and then trying to exclude them.

---

## 4. GDPR Retention (L-3 closure)

Person-type brand matches carry GDPR data-subject implications and are purged after a configurable retention window. Non-person matches (keyword, domain, product) follow the events-table TimescaleDB archiver rules instead.

**Retention knob:** `projects.gdpr_person_match_retention_days` (default `90`).

- Per-project override via the project Settings tab (`PATCH /api/projects/{id}` — `Lead` or `Global Admin` authority required).
- Backing column lives on the `projects` table so the retention value travels with the project and does not require a container restart to take effect.

**Purge schedule:** `brand_gdpr_purge_job` runs **daily at 03:00 UTC** (APScheduler `CronTrigger(hour=3, minute=0, UTC)`).

**What the job runs (simplified):**

```sql
DELETE FROM brand_matches
USING brand_terms, projects
WHERE brand_matches.brand_term_id = brand_terms.id
  AND brand_terms.project_id = projects.id
  AND brand_terms.term_type = 'person'
  AND brand_matches.first_seen <
      NOW() - (projects.gdpr_person_match_retention_days::text
               || ' days')::interval;
```

- **Scope:** `term_type='person'` only — hard scope, non-negotiable. Keyword/domain/product matches are **never** purged by this job.
- **Age basis:** `first_seen` (not `last_seen`). A re-observed stale person match still counts as stale — the subject's data was collected 100 days ago even if we saw it again today. Compliance-aligned.
- **Per-project retention:** The JOIN against `projects` lets different projects carry different retention values; one DELETE handles the whole dataset without a Python-side loop.

**GDPR consent audit trail:**

When an operator adds or edits a `term_type='person'` brand term, the router emits a structured log line with:

- `event: 'brand_term_person_consent'`
- `project_id`
- `user_sub` (Authentik sub of the operator)
- `term_value_sha256` (SHA256 hash of the term value — **never the plaintext**)
- `timestamp`

There is **no queryable `gdpr_consent_log` table in v2.0** (deferred to v2.1). Consent evidence lives in structured logs with the SHA256 hash allowing an operator to correlate a specific term back to its consent-capture record during a data-subject-access request without leaving the subject's name in the database log.

---

## 5. crt.sh Rate Limiting (H-6 closure)

The monitor polls `https://crt.sh/?q=%.{term}&output=json` for `domain` and `product` term types **only**. Keyword and person terms do NOT hit crt.sh (a person's name against CT logs is noise; keyword terms are too broad).

**Request shape:** `httpx.AsyncClient.get("https://crt.sh/", params={"q": f"%.{term}", "output": "json"})`

The `params=` kwarg forces `%` → `%25` URL-encoding (canonical form; see `12-02-SUMMARY.md` Deviation 2 for why this matters).

**429 backoff sequence** (implemented in `backend/app/services/crtsh_client.py`):

| Attempt | Response | Action |
|---|---|---|
| 1 | 429 | sleep 30s, retry |
| 2 | 429 | sleep 60s, retry |
| 3 | 429 | sleep 120s, retry |
| 4 | 429 | log `crtsh_persistent_429_skipping_cycle`, return `[]` |
| any | 5xx | return `[]` immediately (skip cycle) |
| any | network error | return `[]` immediately |
| any | malformed JSON | return `[]` |
| any | 200 | parse + return |

**Dedup key:** `(san, not_before)`. Precert/cert pairs with identical SAN and `not_before` collapse to one row. Different `not_before` timestamps (renewals) keep both rows.

**SAN normalisation:** strip → `lstrip("*.")` → strip → lowercase. Wildcard certs collapse to their base domain.

**Database-level dedup:** `UNIQUE (project_id, brand_term_id, matched_value, match_source)` on `brand_matches` prevents duplicates across polling cycles.

**No certstream websocket.** H-6 is an explicit lock: `certstream` would deliver 3-5M certs/day and overwhelm the `brand-monitor` queue. crt.sh's paginated JSON is the only CT source in v2.0. A paid CT log subscription (e.g. Google Argon, Cloudflare Nimbus) is a v2.1 candidate if crt.sh availability becomes a chronic issue (§13 Troubleshooting).

---

## 6. dnstwist Subprocess (M-8 closure)

The monitor shells out to the installed `dnstwist` binary for permutation generation + live DNS resolution.

**Invocation:**

```python
subprocess.run(
    ["dnstwist", "--threads", "10", "--format", "json", term],
    timeout=120,
    capture_output=True,
)
```

- `--threads 10` — dnstwist's internal worker count. Matches the M-8 pitfall guidance (high enough to keep wallclock bounded on permutation-heavy TLDs; low enough not to starve the shared `worker` container).
- `--format json` — required. Parser at `backend/app/services/dnstwist_parser.py` expects the snake_case key shape (`dns_a`, `dns_aaaa`, `dns_mx`, `dns_ns`, `domain`, `fuzzer`) verified against `dnstwist 20250130` live output (`docs/research/dnstwist-key-verification.md`). Defensive hyphen/underscore fallbacks retained for version-drift insurance.
- `timeout=120` — wallclock cap. `subprocess.TimeoutExpired` is caught, logged as `brand_dnstwist_timeout`, and the term is skipped (non-fatal; other terms in the batch continue).

**Batching:** the monitor batches 5 terms per worker invocation with a 5-second `asyncio.sleep` between batches. This prevents a single project with 50 terms from pinning the worker thread for 10 minutes of dnstwist execution.

**`lookup_success` derivation** (parser-internal, not emitted by dnstwist):

```python
has_a  = any(entry not in {"!ServFail", ""} for entry in perm.get("dns_a",  []))
has_ns = any(entry not in {"!ServFail", ""} for entry in perm.get("dns_ns", []))
lookup_success = has_a or has_ns
```

Severity: `lookup_success=True` → `high`, `lookup_success=False` → `low`. MX-only or AAAA-only is treated as partial signal and falls to `low` — matches the severity truth table in `12-RESEARCH.md`.

**`*original` row filter:** the top-level `parse_dnstwist_output()` skips the row where `fuzzer == "*original"` (the target domain itself would otherwise pollute the match stream). Per-row `parse_permutation()` does NOT skip — callers iterating manually (diagnostics) still see it.

### 6.1 Upgrade Procedure

dnstwist is installed transitively via `backend/pyproject.toml` + `uv.lock` — **not** a separate `RUN pip install` line in `ops/api.Dockerfile`. To upgrade:

```bash
# 1. Update the version pin in backend/pyproject.toml
#    "dnstwist>=20240219" → "dnstwist>=20250130" (or newer)

# 2. Refresh the lockfile
cd backend && uv lock --upgrade-package dnstwist

# 3. Rebuild the api image (uv sync runs during build, baking the new dnstwist in)
docker compose build api

# 4. Bounce worker + scheduler (worker runs the actor; scheduler fires the tick)
docker compose up -d worker scheduler

# 5. Verify inside the running worker
docker compose exec worker dnstwist --version
docker compose exec worker python -c "import dnstwist; print(dnstwist.__file__)"
```

> **Note:** If `dnstwist` emits new or renamed JSON keys in a future release, the parser's defensive hyphen/underscore fallback chain should still cover the shape. If it doesn't, re-run the live verification recipe in `docs/research/dnstwist-key-verification.md` and update the key list — do not silently widen the parser.

**Regression guard:** `backend/tests/integration/test_compose_brand_queue.py::test_dnstwist_is_installed_in_image` asserts `dnstwist` appears as a real dependency declaration (not just a comment) in `pyproject.toml` / `requirements.txt` / Dockerfile `pip install` lines. Removing the pin would fail CI.

---

## 7. Noise Downgrade (H-5 closure)

Brand terms that produce excessive matches auto-downgrade from `mode='active'` to `mode='watch_only'`. Watch-only terms are still scanned but do NOT synthesise events and do NOT fire webhooks — the match rows are recorded for operator review and the UI surfaces a banner.

**Threshold:** `BRAND_NOISE_THRESHOLD` env var (default `100`). Read at tick-time via `settings.BRAND_NOISE_THRESHOLD` — operators can flip the threshold live via `.env` + container restart without a code change.

**Schedule:** `brand_noise_downgrade_sweep_job` runs **nightly at 04:30 UTC** (APScheduler `CronTrigger(hour=4, minute=30, UTC)`).

**What the job runs (simplified):**

```sql
UPDATE brand_terms bt
SET mode = 'watch_only'
WHERE bt.mode = 'active'
  AND (
    SELECT count(*) FROM brand_matches bm
    WHERE bm.brand_term_id = bt.id
      AND bm.first_seen > NOW() - INTERVAL '24 hours'
  ) > :threshold;
```

**Re-activation:** manual only. An operator reviews the term on the project Brand tab's Terms table, uses the Mode Switch to flip back to `active`, and ideally tightens the term value first (e.g. `ib` → `intellibird-corp`). A UI banner on the Brand tab surfaces the list of currently-downgraded terms until they are either re-activated or deleted.

**Why not auto-reactivate?** Because a term that generated >100 matches in 24 hours is producing noise — auto-reactivation would just downgrade it again the next night. The operator must intervene with a tighter term definition.

---

## 8. Dismissal Lifecycle (M-5 closure)

Brand matches carry a `lifecycle_status` column (`new` / `confirmed` / `dismissed` / `watchlist`) and an optional `dismiss_until TIMESTAMPTZ` column for time-bounded dismissals.

**Default behaviour:** dismissing a match via the UI sets `lifecycle_status='dismissed'` and `dismiss_until=NOW() + INTERVAL '30 days'`.

**Schedule:** `brand_dismiss_expiry_sweep_job` runs **hourly** (APScheduler `IntervalTrigger(hours=1)`).

**What the job runs (simplified):**

```sql
UPDATE brand_matches
SET lifecycle_status = 'new', dismiss_until = NULL
WHERE lifecycle_status = 'dismissed'
  AND dismiss_until IS NOT NULL
  AND dismiss_until < NOW();
```

**Suppression review banner:** the Brand tab surfaces an amber banner listing dismissals expiring within **7 days** — giving the operator a chance to re-triage (confirm, re-dismiss, or promote to watchlist) before the sweep automatically reactivates them.

**Permanent dismissal:** available via the Suppression Review dialog "Indefinite" button. Sets `dismiss_until=NULL` explicitly. The sweep clause `AND dismiss_until IS NOT NULL` excludes these rows, so they are never auto-reactivated. Use sparingly — threat actors register dormant assets for later activation.

**Watchlist lifecycle:** matches set to `lifecycle_status='watchlist'` are never auto-dismissed and never auto-reactivated. They are operator-pinned and persist until manually changed. Useful for long-running engagements where a suspicious lookalike domain is being monitored for activation.

Mirrors the `easm_dismiss_expiry_sweep_job` 1:1 in SQL shape, cadence, and semantics — separate tables only because `brand_matches` and `easm_findings` cascade differently.

---

## 9. Webhook Reuse (BRP-05)

**Zero new webhook code was written in.** HIGH-severity brand matches synthesise canonical events that the existing M1 `webhook_dispatch_tick` picks up via tag-based preset subscriptions. This is the load-bearing design decision of BRP-05.

**Flow:**

1. Monitor scan finds a match with severity ≥ `BRAND_WEBHOOK_SEVERITY_THRESHOLD` (default `HIGH`).
2. `backend/app/services/brand_synth.py::synthesise_event()` writes a row to `events` with:
   - `source_type = 'brand-monitor'`
   - `stix_type = 'indicator'`
   - `tags = ['brand-match', 'brand-match:high', 'brand-match:{source}', 'project:{id}']`
     - `{source}` is one of `fts`, `ct_log`, `dnstwist`
     - `{id}` is the project UUID
   - `title = f"Brand match: {matched_value} ({source})"`
   - `description` carrying the term value + source-specific detail
3. `brand_matches.event_id` is set to the new event's UUID (soft reference; no FK because `events` is a TimescaleDB hypertable).
4. `brand_matches.webhook_fired_at` is set to `NOW()` to prevent re-fire when the match is re-opened from a dismissal.
5. The existing ** `webhook_dispatch_tick`** scans the events table on its normal cadence, matches the new row against preset subscription filters, and delivers to configured webhook endpoints. No code executes in the delivery path.

**Configuring a brand-protection webhook preset:**

Navigate to the global Webhooks settings (outside the project context), create a preset, and configure tag filters such as:

- `brand-match:high` — every HIGH-severity brand match across all projects
- `brand-match:dnstwist` — only dnstwist lookalike matches (typically the highest-signal source)
- `project:{uuid}` combined with `brand-match` — project-scoped brand alerts
- `brand-match:ct_log` — CT log hits (useful if `BRAND_WEBHOOK_SEVERITY_THRESHOLD=MEDIUM`)

**Re-fire prevention:** The `webhook_fired_at` column is checked before each tick. A match that was previously fired, then dismissed, then auto-reactivated by the dismiss-expiry sweep will NOT re-fire unless an operator explicitly resets the column (not exposed as a UI action in v2.0 — DB-level only).

**Severity threshold tuning:**

```bash
# In ops/.env — lower the bar to fire on MEDIUM (CT log hits) as well
BRAND_WEBHOOK_SEVERITY_THRESHOLD=MEDIUM
docker compose up -d --force-recreate worker scheduler
```

Only `HIGH` and `MEDIUM` are accepted (Pydantic `Literal['HIGH','MEDIUM']` — invalid values fail Settings validation at startup).

---

## 10. Scheduler Job Catalogue

All four jobs are registered via `register_brand_jobs(scheduler, settings)` in `backend/app/scheduler/jobs.py`. Job IDs are stable strings — ops can query `APScheduler.get_job(...)` by these exact names.

| Job ID | Trigger | Purpose | Requirement |
|---|---|---|---|
| `brand_monitor_tick` | `IntervalTrigger(BRAND_MONITOR_INTERVAL_SECONDS, default 900s)` | Enqueue `brand_monitor_scan_project.send(pid)` for every non-archived project | BRP-02 |
| `brand_gdpr_purge` | `CronTrigger(hour=3, minute=0, UTC)` | DELETE person-type `brand_matches` older than per-project retention days | L-3 (GDPR) |
| `brand_noise_downgrade_sweep` | `CronTrigger(hour=4, minute=30, UTC)` | Flip `mode='active'→'watch_only'` when 24h match count > `BRAND_NOISE_THRESHOLD` | H-5 |
| `brand_dismiss_expiry_sweep` | `IntervalTrigger(hours=1)` | Reactivate dismissed `brand_matches` when `dismiss_until < NOW()` | BRP-04 |

All four jobs are **idempotent** — running them twice in quick succession produces no additional side effects beyond the first run. See `backend/tests/integration/test_brand_suppression_expiry.py::test_dismiss_expiry_sweep_idempotent` and `test_brand_gdpr_purge.py::test_gdpr_purge_is_noop_on_empty_dataset` for the regression guards.

**Tick flow (BRP-02):**

```
brand_monitor_tick (scheduler)
  └── SELECT id FROM projects WHERE archived IS NOT TRUE
      └── for each project_id:
          brand_monitor_scan_project.send(str(project_id))   # Redis queue hop
              └── worker picks up from `brand-monitor` queue
                  └── brand_monitor_scan_project(actor body)
                      └── asyncio.run(_async_scan(project_id))
                          └── FTS + CT log + dnstwist branches compose
                              brand_stoplist.is_stoplisted
                              brand_severity.score
                              crtsh_client.fetch_certs
                              dnstwist_parser.parse_dnstwist_output
                              brand_synth.synthesise_event  (HIGH matches only)
```

The scheduler uses a **sync `psycopg2`** connection for project discovery (APScheduler is sync; attempting async I/O here would spawn an event loop per tick). The actor body uses an **async** engine created inside `_async_scan` and disposed in `finally` — per-loop engine pattern mandated by the BBOT lesson (module-global engines leak event-loop affinity across Dramatiq worker threads).

---

## 11. Queue and Worker Topology

**Dedicated queue:** `brand-monitor`. Actor `brand_monitor_scan_project` is bound with:

```python
@dramatiq.actor(
    queue_name="brand-monitor",
    max_retries=2,
    min_backoff=5_000,
    max_backoff=60_000,
)
```

Transient failures (Redis blip, DB deadlock, crt.sh 5xx) retry twice with 5s → 60s exponential backoff. Persistent failures surface as WARNING-level log lines after the third attempt rather than infinite-looping.

**Co-location on the shared `worker` container** (NOT a dedicated `brand-worker` service):

```yaml
# ops/docker-compose.yml (abridged)
worker:
  image: intellibird-api:m1
  command: dramatiq app.workers.broker --queues ingest maintenance webhooks brand-monitor --processes 1 --threads 4
```

**Why co-located (contrast EASM):**

- `dnstwist` is a pure-Python package + optional GeoIP mmdb — **no docker.sock mount needed**.
- `crt.sh` is an HTTPS call — no elevated privileges.
- FTS is a DB query — no elevated privileges.
- Keeping `brand-monitor` off `easm-worker` preserves the docker.sock blast-radius discipline (see `docs/ops/easm.md §1`). The regression test `backend/tests/integration/test_compose_brand_queue.py::test_brand_monitor_queue_not_on_easm_worker` enforces this as a negative invariant.

**CPU isolation (M-8):** enforced at the **queue** level, not the container level. If dnstwist subprocess CPU becomes a noisy neighbour to `ingest` (NVD, RSS, TAXII) or `webhooks`, the next escalation is to split the `worker` container into two copies of the same image with disjoint `--queues` lists — no code change required, just Compose wiring.

**Regression guards:**

- `test_worker_queues_include_brand_monitor` — asserts `brand-monitor` is in the `worker` service `--queues` list.
- `test_brand_monitor_queue_not_on_easm_worker` — asserts `brand-monitor` is NOT in the `easm-worker` service `--queues` list.
- `test_dnstwist_is_installed_in_image` — asserts `dnstwist` is a real dependency declaration (not a comment mention).

Both test helpers tokenise `--queues` tolerantly of both shell-string and YAML-list `command:` forms, so a cosmetic refactor between the two styles cannot silently drop the queue.

---

## 12. Upgrade Procedure

See §6.1 for `dnstwist` upgrades specifically. General upgrade flow:

1. **Pull new backend code**: `git pull` (upstream or feature branch merge).
2. **Refresh deps**: `cd backend && uv lock && cd ..`.
3. **Apply migrations**: `docker compose exec api alembic upgrade head`.
4. **Rebuild images**: `docker compose build api` (picks up new pyproject.toml / lock).
5. **Bounce containers**: `docker compose up -d --force-recreate api worker scheduler`.
6. **Smoke test**:
   - `docker compose logs -f scheduler | grep brand_` — confirm all four brand jobs register at startup.
   - Create a throwaway brand term on a test project, wait one tick (15 min by default; or set `BRAND_MONITOR_INTERVAL_SECONDS=60` on the test host), confirm `brand_matches` rows appear.
   - Confirm a webhook preset subscribed to `brand-match:high` fires when a HIGH match is synthesised.

**Rollback:** `alembic downgrade` to the previous migration revision, then redeploy the previous image tag. The brand-protection schema is disjoint from EASM (different tables, different enums), so rollback is independent of.

---

## 13. Troubleshooting

### 13.1 `brand_dnstwist_timeout` log spam

**Symptom:** Worker logs repeatedly emit `brand_dnstwist_timeout` for one or more terms.

**Cause:** `dnstwist` may stall on high-permutation TLDs (e.g. `.com`, `.co`) or when DNS resolvers are slow. The 120-second `subprocess.run` timeout fires and the term is skipped for that cycle.

**Fixes:**

- Confirm the installed dnstwist version: `docker compose exec worker dnstwist --version`.
- Reduce `--threads` from 10 to 5 in `backend/app/workers/brand.py` (trade-off: slower dnstwist wallclock, fewer timeouts).
- Raise the subprocess timeout — grep for `timeout=120` in `brand.py` and adjust. Budget total wallclock so the 5-term batch + 5s sleeps still fits inside the 15-minute `brand_monitor_tick` interval.
- Tighten noisy terms (shorter strings permute into more domains; `ib` permutes into millions of candidates, `intellibird-corp` permutes into thousands).

### 13.2 crt.sh persistent 429 (skipping cycle)

**Symptom:** Worker logs show `crtsh_persistent_429_skipping_cycle` repeatedly; CT log matches stop appearing in `brand_matches`.

**Cause:** crt.sh is community-run and does rate-limit aggressively during busy periods. Our client gives up after 30s/60s/120s of backoff.

**Fixes:**

- Wait it out — crt.sh 429 episodes typically last hours, not days. FTS and dnstwist branches continue to produce matches in the meantime.
- **Reduce poll frequency:** set `BRAND_MONITOR_INTERVAL_SECONDS=1800` (30 min) or higher. Fewer requests per hour = less 429 exposure.
- Switch to a paid CT log subscription (Google Argon, Cloudflare Nimbus, Let's Encrypt Oak). This is a **v2.1 candidate** — the client library landscape is fragmented and none ship a drop-in replacement for our current httpx.AsyncClient flow.
- Do NOT add a cache layer. crt.sh responses are append-only CT log snapshots; a cache would delay new cert observations and weaken the monitor's signal.

### 13.3 No webhooks firing for HIGH matches

**Symptom:** Brand matches with severity `high` appear in the DB but webhook endpoints never receive deliveries.

**Verification checklist:**

1. **Severity threshold:** `BRAND_WEBHOOK_SEVERITY_THRESHOLD=HIGH` (default). Setting it to `MEDIUM` is fine; any other value fails Pydantic validation at startup.
2. **Event synthesis:** `SELECT id, title, tags FROM events WHERE source_type='brand-monitor' ORDER BY observed_at DESC LIMIT 5;` — confirm canonical events are being written.
3. **webhook_fired_at:** `SELECT id, severity, webhook_fired_at FROM brand_matches WHERE severity='high' ORDER BY first_seen DESC LIMIT 5;` — confirm the column is being set by `brand_synth.synthesise_event`.
4. **Preset subscription:** open the Webhooks UI, verify the preset tag filter includes `brand-match:high` (or `brand-match` as a parent tag). Missing subscription = no delivery.
5. **webhook_dispatch_tick status:** `docker compose logs scheduler | grep webhook_dispatch_tick` — confirm the tick is running on its normal cadence.
6. **Endpoint reachability:** `docker compose logs worker | grep webhook_delivery` — confirm deliveries are being attempted and surfacing any HTTP errors from the endpoint.

### 13.4 Term auto-downgraded unexpectedly to watch_only

**Symptom:** A brand term flips to `mode='watch_only'` overnight and the Brand tab surfaces the noise banner.

**Cause:** The term produced more than `BRAND_NOISE_THRESHOLD` matches (default 100) in the preceding 24 hours.

**Diagnosis:**

```sql
SELECT count(*), max(first_seen) - min(first_seen) AS span
FROM brand_matches bm
JOIN brand_terms bt ON bm.brand_term_id = bt.id
WHERE bt.value = 'ib'
  AND bm.first_seen > NOW() - INTERVAL '24 hours';
```

**Fixes:**

- **Tighten the term:** delete + re-add with a longer, more specific value. `ib` → `intellibird` → `intellibird-corp`.
- **Raise the threshold** if the match volume is expected and useful: `BRAND_NOISE_THRESHOLD=500` in `ops/.env` + restart scheduler. Trade-off: webhook volume scales linearly.
- **Re-activate manually:** UI → project Brand tab → Terms table → Mode Switch → `active`. The sweep will re-downgrade tomorrow night if the underlying noise is still >threshold.

### 13.5 Brand jobs missing at scheduler startup

**Symptom:** `docker compose logs scheduler` at container boot shows no `brand_monitor_tick` / `brand_gdpr_purge` / etc. registration lines.

**Cause:** `register_brand_jobs(scheduler, settings)` may have failed silently during `build_scheduler`. follows the precedent of wrapping job registration in try/except to survive transient Postgres unavailability at scheduler startup.

**Diagnosis:**

```bash
docker compose logs scheduler 2>&1 | grep -iE "brand|scheduler_error|register_brand"
```

Look for `scheduler_brand_registration_failed` warnings. Typically indicates a DB connectivity issue at scheduler boot, not a code bug.

**Fix:** restart the scheduler container after the DB is healthy: `docker compose restart scheduler`.

### 13.6 GDPR purge not deleting expected rows

**Symptom:** Person-type matches older than the retention window are still present in `brand_matches`.

**Checklist:**

1. **Term type:** `SELECT term_type FROM brand_terms WHERE id = '<match_brand_term_id>';` — must be `'person'`. Keyword/domain/product terms are NOT in scope for GDPR purge.
2. **Retention value:** `SELECT id, name, gdpr_person_match_retention_days FROM projects WHERE id = '<project_id>';` — confirm it is a sane integer (default `90`, not `9000` or `NULL`).
3. **Age basis:** job uses `first_seen`, not `last_seen`. A match observed yesterday but first seen 100 days ago IS in scope. A match first seen yesterday is NOT, even if the term has been in the system for years.
4. **Job actually ran:** `docker compose logs scheduler | grep brand_gdpr_purge` around 03:00 UTC. If the scheduler container was down at 03:00, the job did not fire — next run is tomorrow. Trigger manually if urgent:
   ```bash
   docker compose exec scheduler python -c "
   from app.scheduler.jobs import brand_gdpr_purge_job
   brand_gdpr_purge_job()
   "
   ```

---

## 14. Deferred Items

The following capabilities are scoped to v2.1 and are not present in (v2.0):

| Item | Reason deferred |
|---|---|
| Per-project editable stoplist | v2.0 stoplist is a global code constant + env-extra union; per-project override adds a new table + UI surface. CONTEXT.md §Deferred Ideas. |
| Queryable `gdpr_consent_log` table | Structured logs with SHA256-hashed term values are sufficient for v2.0 compliance evidence; queryable table adds a new schema + rotation policy. |
| CertStream realtime CT monitoring | 3-5M certs/day firehose exceeds v2.0 queue capacity; paid CT subscription (Argon/Nimbus/Oak) is the v2.1 upgrade path. |
| ML severity rerank | v2.0 severity is a pure-function truth table (fts→low, ct_log→medium, dnstwist+success→high); ML rerank requires a training loop + model versioning. |
| Dedicated `brand-worker` container | v2.0 co-locates `brand-monitor` queue on shared `worker` (M-8 queue-level isolation is sufficient). Physical isolation via separate container is a Compose wiring change only — no code required — if dnstwist CPU becomes a noisy neighbour. |
| Auto-reactivation of noise-downgraded terms | Requires operator judgement — v2.0 keeps it manual deliberately. |
| UI regex editor for term matching | v2.0 terms are plain strings; regex support would need a separate `value_regex` column + UI linting. |

---

## 15. Cross-References

| Reference | Link |
|---|---|
| PITFALLS §H-5 | Noise-downgrade sweep — nightly `brand_noise_downgrade_sweep_job` (§7) |
| PITFALLS §H-6 | crt.sh 429 backoff + certstream exclusion (§5) |
| PITFALLS §M-5 | Dismissal lifecycle + hourly expiry sweep (§8) |
| PITFALLS §M-8 | dnstwist CPU isolation — dedicated queue + subprocess timeout (§6, §11) |
| PITFALLS §L-3 | GDPR person-match retention — daily purge job (§4) |
| BRP-02 | Per-project brand-term monitoring (§1, §10, §11) |
| BRP-05 | Webhook reuse — zero new webhook code, tag-based subscription (§9) |
| | Production Readiness Hardening — brand-protection surfaces folded into the integration test bundle |
| `backend/app/services/brand_stoplist.py` | `DEFAULT_STOPLIST`, `is_stoplisted`, `is_short`, `load_runtime_stoplist` |
| `backend/app/services/brand_severity.py` | Pure-function severity truth table |
| `backend/app/services/crtsh_client.py` | Async CT log client — 429 backoff + precert/cert dedup |
| `backend/app/services/dnstwist_parser.py` | JSON parser — defensive key fallbacks + ServFail-aware `lookup_success` derivation |
| `backend/app/services/brand_synth.py` | Canonical-event synthesis for webhook reuse |
| `backend/app/workers/brand.py` | `brand_monitor_scan_project` Dramatiq actor |
| `backend/app/scheduler/jobs.py` | `register_brand_jobs()` + four `brand_*` jobs |
| `backend/tests/integration/test_compose_brand_queue.py` | Compose regression — worker queue + dnstwist dep |
| `docs/research/dnstwist-key-verification.md` | dnstwist 20250130 JSON key shape evidence |
| `docs/ops/easm.md` | EASM runbook — docker.sock contrast (§11) |
| `docs/ops/projects.md` | Project authority matrix (term CRUD gates) |
| `docs/ops/secret-rotation.md` | `SECRET_KEY` rotation (does not touch brand_matches; pure-metadata) |
| `ops/.env.example` | All four `BRAND_*` keys |
| `ops/docker-compose.yml` | `worker` `--queues ingest maintenance webhooks brand-monitor` |

---

Last updated: 2026-04-23 (shipped).
Related: [easm.md](easm.md), [projects.md](projects.md), [auth-setup.md](auth-setup.md), [../../ops/.env.example](../../ops/.env.example).

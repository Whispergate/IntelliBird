# IntelliBird EASM (BBOT) Operations Runbook

**Applies to:** IntelliBird v2.0+ (shipped)
**BBOT version pinned:** `blacklanternsecurity/bbot:stable` (2.8.4 as of 2026-04-20)
**BBOT image digest:** `sha256:ae34a24ee3f30eb334466450303dc2df739b5505aa0c248fa0f603b167f0fc69`

**Related:**
- `ops/.env.example` - all `BBOT_*` keys
- `ops/docker-compose.yml` - `easm-worker` service definition
- `docs/ops/secret-rotation.md` - `SECRET_KEY` rotation (affects `project_easm_credentials`)
- `docs/ops/auth-setup.md` - Authentik setup (Lead/Admin roles gate the active-scan flip)
- `docs/ops/projects.md` - project authority matrix and scope row semantics
- `ROADMAP.md §` - PROD-02 active-scan gate penetration test

---

## Table of Contents

1. [Security - Elevated Privilege Warning](#1-security--elevated-privilege-warning)
2. [Architecture](#2-architecture)
3. [Migrations](#3-migrations)
4. [Environment Keys](#4-environment-keys)
5. [Module Safelist](#5-module-safelist)
6. [Active-Scan Gate](#6-active-scan-gate)
7. [Retention](#7-retention)
8. [Upgrade Procedure](#8-upgrade-procedure)
9. [Disaster Recovery](#9-disaster-recovery)
10. [Post-Deploy Checklist](#10-post-deploy-checklist)
11. [Credentials (Per-Project API Keys)](#11-credentials-per-project-api-keys)
12. [Deferred Items](#12-deferred-items)
13. [Cross-References](#13-cross-references)

---

## 1. Security - Elevated Privilege Warning

**The `easm-worker` Compose service mounts `/var/run/docker.sock:/var/run/docker.sock`. This grants the container root-equivalent host access (OWASP Docker Security Cheat Sheet 2025). Any code path that reaches `easm-worker` can `docker run` arbitrary images with host-root privileges. Container escape from `easm-worker` is effectively a host compromise.**

Threat model:

- The `easm-worker` process spawns BBOT via `docker run`. Access to the Docker socket means the process can launch any image, mount any host path, or exec into existing containers - this is equivalent to root on the Docker host.
- An attacker with RCE inside `easm-worker` (e.g. via a malformed BBOT NDJSON event exploiting the log parser) gains full host access.
- The attack surface is bounded by the BBOT module safelist and the fact that BBOT targets derive exclusively from `project_scope_rows` - but the socket mount itself cannot be scoped.

> **Note:** Do NOT copy the `/var/run/docker.sock` mount to `api`, `worker`, or `scheduler` services. The unit test `backend/tests/unit/easm/test_compose_easm.py` asserts this invariant - a failing test after a Compose refactor means the mount has leaked to a disallowed service.

Mitigations in place:

- `easm-worker` consumes only the `easm` Dramatiq queue - the command is pinned to `dramatiq app.workers.broker --queues easm --processes 1 --threads 2`, preventing it from processing general ingest or maintenance work.
- All `docker run` argument construction is server-assembled from the backend-enforced module safelist and validated `project_scope_rows` - zero operator-string pass-through to subprocess arguments (M-3 pitfall closure).
- BBOT scan containers run on the Compose **default bridge network**, not the internal `intellibird` network - BBOT reaches external DNS and HTTP but cannot laterally reach `api`, `db`, or `redis`.
- BBOT containers carry labels `intellibird.easm=true` and `intellibird.scan_id=<uuid>` - auditable via `docker events --filter label=intellibird.easm=true`.
- `BBOT_IMAGE_TAG` pins the image (default `blacklanternsecurity/bbot:stable`); operators should pin a digest in production (see §8 Upgrade Procedure).

Host hardening recommendations (operator-owned):

- Run the Docker daemon under a non-root user namespace (`userns-remap`) - consult your distribution's Docker documentation.
- Apply AppArmor or SELinux profiles to the `easm-worker` container if your host supports them.
- Monitor `docker events --filter label=intellibird.easm=true` for unexpected container launches.
- Network-level: confirm scan containers cannot reach the Compose internal bridge by inspecting the default bridge settings (`docker network inspect bridge`).

> **Note:** The `loopback-only` host-port binding requirement (PROD-07) documented in applies to the `easm-worker` service as well - it publishes no ports and relies entirely on the shared Redis and Postgres containers via the internal network.

---

## 2. Architecture

BBOT runs inside **ephemeral** Docker containers spawned by `easm-worker`, NEVER inside the `api`, `worker`, or `scheduler` service image. This is required because BBOT's internal parallelism uses `multiprocessing` with daemonic child processes, which crash when launched from inside a Dramatiq worker thread (BBOT GitHub issue #2354 - no upstream fix; PITFALLS §C-5).

Execution flow:

1. Operator triggers a passive or active scan via the UI or API.
2. `POST /api/projects/{id}/easm/scans` validates the request (modules ⊆ safelist, scope non-empty, active-scan gate if `mode=active`), inserts an `easm_scans` row with `status='queued'`, and dispatches `run_bbot_scan(scan_id)` to the `easm` Dramatiq queue.
3. `easm-worker` actor acquires the Redis semaphore (`bbot:concurrent_scans` INCR), then issues `docker run -d --label intellibird.easm=true --label intellibird.scan_id=<uuid> ...` - the detached container ID is stored in `easm_scans.container_id` before log streaming begins (PITFALLS §Pitfall 2).
4. The worker streams NDJSON lines via `docker logs --follow <container_id>`, parsing each line as a BBOT event.
5. Findings write to `easm_findings` with `ON CONFLICT (project_id, bbot_event_type, canonical_target) DO UPDATE` (M-4 cross-scan dedup). The `content_hash` is `sha256(project_id || bbot_event_type || canonical_target)` - no scan_id, no timestamp - so the same target found by two scans updates one row rather than creating duplicates.
6. High-confidence findings (`VULNERABILITY`, `SUBDOMAIN_TAKEOVER_CANDIDATE`, `TECHNOLOGY`, `FINDING` with severity HIGH or CRITICAL) are promoted to canonical `events` rows with `source_type='bbot'` and `easm_scan_id=<scan_id>`.
7. On completion or cancellation, the semaphore is decremented in a `finally` block.

Key services:

| Service | Role |
|---|---|
| `easm-worker` | Dramatiq consumer - queue `easm`, processes 1, threads 2 |
| `scheduler` | APScheduler - fires `easm_scan_history_cleanup` (04:00 UTC), `easm_dismiss_expiry_sweep` (hourly), `easm_orphan_reaper` (hourly) |
| `redis` | Shared broker + semaphore key `bbot:concurrent_scans` |
| `db` | PostgreSQL - `easm_scans`, `easm_findings`, `project_easm_credentials` tables |

Feed contamination prevention (PITFALLS §H-4):

- `/api/events` excludes `source_type='bbot'` by default.
- Pass `include_bbot=true` to include promoted BBOT events in the main intel feed.
- `easm_findings` is NOT a TimescaleDB hypertable - it is a plain PostgreSQL table with a composite index on `(project_id, last_seen DESC)`.

---

## 3. Migrations

**Migration 010** (`backend/alembic/versions/010_easm.py`) adds all EASM schema. The ROADMAP originally named this "Migration 008" but the actual chain is 008 (users/auth) → 009 (projects/memberships) → **010 (easm)**.

New tables:

| Table | Description |
|---|---|
| `easm_scans` | One row per scan launch - status, mode, modules, container_id, timings, launched_by (Authentik sub) |
| `easm_findings` | One row per BBOT event - dedup UNIQUE `(project_id, bbot_event_type, canonical_target)` |
| `project_easm_credentials` | Per-project encrypted API keys - optional; ships empty |

New columns:

| Table | Column | Purpose |
|---|---|---|
| `projects` | `active_auth_confirmed_by TEXT NULL` | Authentik sub of Lead who flipped the gate |
| `events` | `easm_scan_id UUID NULL FK ON DELETE SET NULL` | Promoted events survive scan cleanup (L-4) |

Run upgrade:

```bash
docker compose exec api alembic upgrade head
```

Rollback (destructive - all EASM tables dropped, no data recovery):

```bash
docker compose exec api alembic downgrade 009_projects_and_memberships
```

After downgrade, `events.easm_scan_id` is removed and promoted BBOT events lose their scan link. Re-run scans to rebuild findings.

---

## 4. Environment Keys

All keys are set in `ops/.env` and read via Pydantic Settings in `backend/app/config.py`. Never use `os.environ.get()` for these at runtime - always go through the settings singleton.

| Key | Default | Meaning |
|---|---|---|
| `BBOT_PASSIVE_MAX_SECONDS` | `7200` (2h) | Wallclock cap on passive scans - container is killed if exceeded |
| `BBOT_ACTIVE_MAX_SECONDS` | `1800` (30m) | Wallclock cap on active scans |
| `BBOT_CONCURRENT_LIMIT` | `2` | Host-wide concurrent scan cap enforced via Redis semaphore |
| `BBOT_SCAN_HISTORY_LIMIT` | `5` | Per-project scan retention - older scans pruned nightly |
| `BBOT_EXPERIMENTAL_OVERRIDE` | `` (empty) | Comma-separated extra module names to union into the safelist at startup |
| `BBOT_IMAGE_TAG` | `blacklanternsecurity/bbot:stable` | BBOT Docker image reference - pin digest in production (see §8) |
| `BBOT_ACTIVE_AUTH_TTL_SECONDS` | `604800` (7d) | Rolling TTL for active-scan gate authorisation |

To apply a change:

```bash
# Edit ops/.env, then restart easm-worker (and scheduler if BBOT_SCAN_HISTORY_LIMIT changed)
docker compose up -d --force-recreate easm-worker scheduler
```

---

## 5. Module Safelist

The stable-passive module set is a `frozenset[str]` defined in `backend/app/services/bbot_safelist.py`. The backend is the **sole source of truth** - the UI populates its module multi-select from `GET /api/easm/safelist`. Any module not in the safelist is rejected at the router layer with HTTP 422 before the scan is queued.

**BBOT 2.8.4 stable-passive modules** (verified 2026-04-20 via `docker run --rm blacklanternsecurity/bbot:stable -l`):

| Module | API Key Required | Credential Provider | Notes |
|---|---|---|---|
| `subdomaincenter` | No | - | subdomain.center API |
| `dnsdumpster` | No | - | dnsdumpster.com passive DNS |
| `crt` | No | - | crt.sh certificate transparency - name is `crt`, NOT `crt.sh` |
| `otx` | Yes | `otx` | AlienVault OTX - requires `OTX_API_KEY` |
| `shodan_dns` | Yes | `shodan` | Shodan passive DNS - requires `SHODAN_API_KEY` |
| `wayback` | No | - | archive.org Wayback Machine |
| `github_codesearch` | Yes | `github` | GitHub code search - requires `GITHUB_TOKEN` |
| `certspotter` | No | - | Certspotter CT logs |
| `hackertarget` | No | - | hackertarget.com API |
| `anubisdb` | No | - | jldc.me subdomain database |
| `bevigil` | Yes | `bevigil` | OSINT from mobile apps - requires `BEVIGIL_API_KEY` |
| `chaos` | Yes | `chaos` | ProjectDiscovery Chaos - requires `CHAOS_API_KEY` |
| `urlscan` | No | - | urlscan.io |
| `securitytrails` | Yes | `securitytrails` | SecurityTrails - requires `SECURITYTRAILS_API_KEY` |

> **Note:** `sublist3r` is **NOT** in BBOT 2.8.x and is **NOT** in the safelist. It was removed from BBOT upstream. Any operator familiar with older BBOT documentation that references `sublist3r` must use `subdomaincenter` instead (PITFALLS §Pitfall 3).

> **Note:** The BBOT module name is `crt`, not `crt.sh`. `crt.sh` is the external service; the BBOT module is named `crt`. Using `crt.sh` as a module name will produce a 422 from the safelist validator.

Modules marked "API Key Required" are skipped silently by BBOT when the corresponding credential is absent - the scan still runs; those modules simply produce no output. This means a deployment without any API keys is fully functional using the 8 key-free modules.

To expand the safelist for a specific deployment without modifying code:

```bash
# In ops/.env
BBOT_EXPERIMENTAL_OVERRIDE=bufferoverrun,leakix,rapiddns
docker compose up -d --force-recreate easm-worker
```

The override is unioned with `BBOT_STABLE_PASSIVE_MODULES` at startup. Operators are responsible for verifying that override modules exist in the installed BBOT version (`docker run --rm blacklanternsecurity/bbot:stable -l | grep <module>`).

Active scans use the **same safelist** as passive scans - no additional modules are unlocked in v2.0. Active mode removes the `-rf passive` BBOT flag (permitting port probing and active DNS brute within the existing module set) but does not expand the module list. Active-module safelist expansion is a v2.1 item.

---

## 6. Active-Scan Gate

Active scans carry CFAA/CMA liability unless the operator has documented written authorisation for each engagement scope (PITFALLS §C-3). IntelliBird enforces a three-factor server-side gate before any active scan is queued.

**All three conditions must be true** (backend-enforced; checked at the router layer before queue dispatch):

1. `projects.active_scans_authorised = true`
2. `projects.scope_acknowledgement_text` byte-exact, case-sensitive match to `projects.name`
3. `NOW() - projects.active_auth_confirmed_at < BBOT_ACTIVE_AUTH_TTL_SECONDS` (default 7 days rolling)

Authority to flip the gate: **Lead** or **Global Admin** only (Contributor and Analyst cannot flip - see authority matrix in §6.4).

### 6.1 Flip via UI (recommended)

Lead or global Admin → `/projects/<id>/?tab=settings` → EASM gate card:

1. Type the project name verbatim into the scope-acknowledgement input.
2. Tick "I confirm that written authorisation exists for active scans against this project's scope".
3. Click "Authorise active scans".

On success, `active_scans_authorised=true`, `active_auth_confirmed_at=NOW()`, and `active_auth_confirmed_by=<current user Authentik sub>` are set atomically.

### 6.2 Flip via API

```bash
curl -X PATCH https://<host>/api/projects/<project_id>/easm-gate \
  -H "Authorization: Bearer <JWT>" \
  -H "Content-Type: application/json" \
  -d '{"scope_acknowledgement_text":"<EXACT project name>","confirm_authorisation":true}'
```

The `scope_acknowledgement_text` value must be byte-exact (case-sensitive) to the project's `name` column. Any mismatch returns 422 `scope_acknowledgement_mismatch`.

### 6.3 Revoke

```bash
curl -X DELETE https://<host>/api/projects/<project_id>/easm-gate \
  -H "Authorization: Bearer <JWT>"
```

Clears all four gate columns (`active_scans_authorised=false`, `active_auth_confirmed_at=NULL`, `active_auth_confirmed_by=NULL`, `scope_acknowledgement_text=NULL`). Takes effect immediately. In-flight active scans complete but no new active scans launch until re-authorised.

### 6.4 Authority Matrix

| Action | Global Admin | Global Analyst | Global Viewer | Project Lead | Project Contributor | Project Observer |
|---|---|---|---|---|---|---|
| Launch passive scan | Yes | Yes | No | Yes | Yes | No |
| Launch active scan | Yes | No | No | Yes | No | No |
| Flip active-scan gate | Yes | No | No | Yes | No | No |
| Cancel running scan | Yes | No | No | Yes | Yes (own) | No |
| Confirm/dismiss/watchlist finding | Yes | Yes | No | Yes | Yes | No |
| View findings and scan history | Yes | Yes | Yes | Yes | Yes | Yes |

Effective access = intersection of global role and project role. A global Analyst who is a project Observer can view findings but cannot flip the gate or launch active scans.

### 6.5 TTL Expiry

The `/projects/[id]/easm` dashboard shows an amber warning banner when `NOW() - active_auth_confirmed_at > 6 days` (24h soft warning before the hard 7-day cutoff). Once expired, the backend returns 403 `authorisation_expired` on active-scan launch attempts.

### 6.6 Audit Trail

Every gate flip and scan launch is captured in structured logs with `user_sub`, `project_id`, `scan_id`, `mode`, `timestamp`, and `reason`. The `active_auth_confirmed_by` column records the Authentik sub of the authorising Lead. A dedicated `easm_scan_audit` table is deferred to v2.1.

> ** PROD-02:** Integration test that direct curl to `POST /api/projects/<id>/easm/scans` with `mode='active'` and all three gate fields absent returns 403. This test is the canonical regression guard for C-3 closure.

---

## 7. Retention

### 7.1 Scan history cap

Per-project scan retention is controlled by `BBOT_SCAN_HISTORY_LIMIT` (default `5`). The APScheduler job `easm_scan_history_cleanup` runs daily at 04:00 UTC and deletes scans beyond the most-recent N per project:

```sql
-- What the cleanup job runs (simplified):
DELETE FROM easm_scans s
WHERE s.id NOT IN (
    SELECT id FROM (
        SELECT id, ROW_NUMBER() OVER (PARTITION BY project_id ORDER BY started_at DESC) AS rn
        FROM easm_scans
    ) ranked
    WHERE rn <= 5  -- BBOT_SCAN_HISTORY_LIMIT
);
```

### 7.2 Cascade behaviour

- `easm_findings.scan_id ON DELETE CASCADE` - non-promoted findings die with the scan row.
- `events.easm_scan_id ON DELETE SET NULL` - promoted events **survive** scan cleanup. The "BBOT / \<scan date\>" provenance badge falls back to "BBOT (historical scan)" when `easm_scan_id IS NULL` (PITFALLS §L-4 closure).

This means promoted high-confidence findings remain permanently in the main intel feed regardless of scan retention settings.

### 7.3 Dismissed findings

Findings set to `lifecycle_status='dismissed'` carry a `dismiss_until` timestamp (default `NOW()+30d`). The hourly `easm_dismiss_expiry_sweep` job resets them to `lifecycle_status='new'` after expiry:

```sql
UPDATE easm_findings
SET lifecycle_status='new', dismiss_until=NULL
WHERE lifecycle_status='dismissed'
  AND dismiss_until IS NOT NULL
  AND dismiss_until < NOW();
```

Dismissal is **never permanent** - threat actors register dormant assets for later activation. Findings on `lifecycle_status='watchlist'` are never dismissed automatically.

### 7.4 Raising retention for TIBER engagements

```bash
# In ops/.env
BBOT_SCAN_HISTORY_LIMIT=25
docker compose up -d --force-recreate easm-worker scheduler
```

The change takes effect on the next nightly cleanup run (04:00 UTC). Existing scans beyond the old limit are not immediately deleted - the higher limit takes effect from that night forward.

---

## 8. Upgrade Procedure

BBOT releases are pinned at `blacklanternsecurity/bbot:stable`. The `:stable` tag tracks the latest stable release without manual intervention, but `:stable` can silently change the underlying image. **Pin a digest in production.**

### 8.1 Pin the image digest

```bash
# In ops/.env
BBOT_IMAGE_TAG=blacklanternsecurity/bbot@sha256:<digest>
```

Current verified digest: `sha256:ae34a24ee3f30eb334466450303dc2df739b5505aa0c248fa0f603b167f0fc69` (BBOT 2.8.4, 2026-04-20).

### 8.2 Evaluate a new BBOT release

Before upgrading in production, verify the module registry has not changed:

```bash
# Pull the new tag and save the module list
docker pull blacklanternsecurity/bbot:stable
docker run --rm blacklanternsecurity/bbot:stable -l > /tmp/new-modules.txt

# Compare passive modules against the verified list
docker run --rm blacklanternsecurity/bbot@sha256:ae34a24ee3f30eb334466450303dc2df739b5505aa0c248fa0f603b167f0fc69 -l > /tmp/old-modules.txt
diff /tmp/old-modules.txt /tmp/new-modules.txt
```

### 8.3 Update the safelist if module names changed

Any module in `BBOT_STABLE_PASSIVE_MODULES` that no longer appears in `-l` output must be removed - otherwise scans will fail with "module not found". Update `backend/app/services/bbot_safelist.py` and `docs/research/bbot-module-verification.md` with:

- New BBOT version and date
- New image sha256 digest
- Updated module name confirmations
- Any corrections to the API-key requirement column

### 8.4 Test against a sandbox project

Before promoting to production:

```bash
# Pull new image explicitly
docker pull blacklanternsecurity/bbot:stable

# Update BBOT_IMAGE_TAG in ops/.env
# Restart easm-worker
docker compose up -d --force-recreate easm-worker

# Launch a passive scan against a sandbox/test project via the UI or API
# Verify findings appear in the EASM tab
```

### 8.5 Rollback

To revert to the previously pinned image:

```bash
# In ops/.env - restore the old digest
BBOT_IMAGE_TAG=blacklanternsecurity/bbot@sha256:<previous-digest>
docker compose up -d --force-recreate easm-worker
```

---

## 9. Disaster Recovery

### 9.1 Stuck Redis semaphore

**Symptom:** Scan launch returns 503 `scan_limit_reached` even though no scans are actively running.

**Cause:** `easm-worker` crashed or was killed between the Redis `INCR` and the `finally: DECR` block (PITFALLS §Pitfall 4). The counter did not decrement.

**Fix (automatic):** The `easm-worker` startup hook `heal_semaphore_from_db` resets `bbot:concurrent_scans` to the count of `easm_scans WHERE status='running'`. Simply restarting the worker heals the drift:

```bash
docker compose restart easm-worker
```

**Fix (manual, if restart fails or DB connectivity was also interrupted):**

```bash
# Confirm how many scans are actually running in DB
docker compose exec db psql -U intellibird intellibird \
  -c "SELECT count(*) FROM easm_scans WHERE status='running';"

# Set the semaphore to match (replace 0 with actual count)
docker compose exec redis redis-cli SET bbot:concurrent_scans 0
```

### 9.2 Orphan BBOT containers

**Symptom:** `docker ps -a --filter label=intellibird.easm=true` shows exited containers not cleaned up.

**Cause:** `easm-worker` crashed during a scan before it could issue `docker rm`.

**Fix (automatic):** `easm-worker` startup runs `reap_orphan_containers()` which removes all exited `intellibird.easm=true` labelled containers. The hourly `easm_orphan_reaper` APScheduler job also runs this.

**Fix (manual):**

```bash
docker ps -a --filter label=intellibird.easm=true --filter status=exited -q \
  | xargs -r docker rm
```

To inspect what is running:

```bash
docker ps --filter label=intellibird.easm=true \
  --format "table {{.ID}}\t{{.Label \"intellibird.scan_id\"}}\t{{.Status}}"
```

### 9.3 Scans stuck in `running` status

**Symptom:** `easm_scans.status='running'` for scans whose `started_at` is older than the wallclock cap plus grace period (passive: 2h + 10m = 2h 10m).

**Cause:** `easm-worker` was restarted mid-scan and the container was cleaned up without updating the DB row.

**Fix (automatic):** `easm-worker` startup runs `reap_orphan_scans()` which marks stale running scans as `orphaned`. The hourly `easm_orphan_reaper` job also runs this.

**Fix (manual):**

```sql
UPDATE easm_scans
SET status='orphaned', error='manual_reset'
WHERE status='running'
  AND started_at < NOW() - INTERVAL '2 hours 10 minutes';
```

### 9.4 Cancel a runaway scan

Via API:

```bash
curl -X DELETE https://<host>/api/projects/<project_id>/easm/scans/<scan_id> \
  -H "Authorization: Bearer <JWT>"
```

The backend issues `docker stop -t 10 <container_id>` then `docker kill <container_id>` if the container is still alive after 10 seconds. The scan row is marked `status='cancelled'`.

Via Docker directly (emergency only):

```bash
# Find the container_id from the DB or from docker ps
docker compose exec db psql -U intellibird intellibird \
  -c "SELECT container_id FROM easm_scans WHERE id='<scan_uuid>';"

docker stop -t 10 <container_id>
```

After a manual Docker stop, the scan row remains `running` until the orphan reaper runs. Reset it manually if needed (see §9.3).

### 9.5 Volume cleanup

The `bbot_scans` Docker volume holds per-scan YAML output files written by BBOT. It grows with each scan and is not automatically pruned (only DB rows are pruned - the volume files accumulate).

```bash
# Inspect volume usage
docker volume inspect bbot_scans

# Hard reset (destroys all scan output files - do this only if DB records are already pruned)
docker compose down
docker volume rm <compose_project_prefix>_bbot_scans
docker compose up -d
```

Replace `<compose_project_prefix>` with your Compose project name prefix (typically `intellibird` or the directory name where `docker-compose.yml` lives). Confirm with `docker volume ls`.

### 9.6 Migration 010 rollback

```bash
docker compose exec api alembic downgrade 009_projects_and_memberships
```

All EASM tables are dropped. Promoted events in `events` lose `easm_scan_id` (column is dropped). There is no data recovery path - re-run scans to rebuild findings. Back up the database before downgrading.

---

## 10. Post-Deploy Checklist

After bringing up the stack for the first time:

- [ ] **Run migration 010:** `docker compose exec api alembic upgrade head` - confirm log line `migration_010 easm tables created`.
- [ ] **Start easm-worker:** `docker compose up -d easm-worker` - confirm it is running via `docker compose ps easm-worker`.
- [ ] **Regenerate API client types:** `cd web && pnpm gen:api` - this step was deferred during plan 11-11 execution because the backend was offline. The `web/app/api-client.ts` file contains interim manually-written types for EASM endpoints that will be replaced by the generated types once the backend is live. Run this against a running stack and commit the result.
- [ ] **Verify EASM tab:** Navigate to `/projects/<id>` in the browser - confirm the EASM tab appears in the project navigation strip.
- [ ] **Smoke-test passive scan:** Launch a passive scan on a test project with at least one `active_test_scope=true` domain scope row. Confirm the scan status progresses from `queued` → `running` → `finished` and findings appear in the EASM findings table.
- [ ] **Verify feed exclusion:** Confirm that `GET /api/events` does not return `source_type='bbot'` rows by default. Pass `include_bbot=true` to confirm promoted events appear.
- [ ] **Check semaphore health:** After the test scan completes, confirm `docker compose exec redis redis-cli GET bbot:concurrent_scans` returns `0` (or matches active scan count).
- [ ] **Verify orphan reaper:** Restart `easm-worker` mid-scan (for non-production testing) and confirm the reaper marks the scan `orphaned` on next startup.
- [ ] **Confirm `.env` BBOT keys:** All 7 `BBOT_*` keys are set in `ops/.env` (see §4 Environment Keys). No key is missing or left at placeholder.

---

## 11. Credentials (Per-Project API Keys)

Six modules in the safelist accept optional API keys: `otx`, `shodan_dns`, `github_codesearch`, `bevigil`, `chaos`, and `securitytrails`. Without credentials these modules are silently skipped; scans still run using the remaining key-free modules.

API keys are stored per-project in `project_easm_credentials` via `app.crypto.encrypt_credentials` with `credentials_key_version` tracking - the same rotation discipline used for `sources.credentials_enc`.

**The v2.0 UI does not surface a credentials entry form** (deferred to v2.1). Operators who need credentialed modules have two options:

**Option A - Environment variable on easm-worker (simplest):**

Set the module's environment variable directly on the `easm-worker` service. BBOT reads these from the container environment:

```bash
# In ops/.env (or docker compose environment block)
SHODAN_API_KEY=<key>
GITHUB_TOKEN=<token>
OTX_API_KEY=<key>
BEVIGIL_API_KEY=<key>
CHAOS_API_KEY=<key>
SECURITYTRAILS_API_KEY=<key>
```

Then restart `easm-worker`: `docker compose up -d --force-recreate easm-worker`.

This approach applies credentials globally (all projects use the same keys). Use `project_easm_credentials` for per-project key isolation.

**Option B - Insert into project_easm_credentials via psql:**

```bash
# Open a Python shell in the api container to get the encrypted value
docker compose exec api python -c "
from app.crypto import encrypt_credentials
print(encrypt_credentials('api_key=<value>'))
"

# Insert the encrypted blob (replace UUIDs and values)
docker compose exec db psql -U intellibird intellibird -c "
INSERT INTO project_easm_credentials (id, project_id, provider, credentials_enc, credentials_key_version)
VALUES (gen_random_uuid(), '<project_uuid>'::uuid, 'shodan', '<encrypted_blob>', 1);
"
```

**Credential rotation:** If you rotate `SECRET_KEY`, run `POST /api/admin/rekey-credentials` (see `docs/ops/secret-rotation.md`). The rekey endpoint covers `project_easm_credentials` alongside `sources.credentials_enc`.

---

## 12. Deferred Items

The following capabilities are scoped to v2.1 and are not present in (v2.0):

| Item | Reason deferred |
|---|---|
| `project_easm_credentials` UI (credential entry form) | v2.0 ships DB table + crypto; UI deferred for scope discipline |
| Active-module safelist expansion | v2.0 active scans use passive safelist under active BBOT flags; new modules (httpx, nuclei) require threat-model review |
| Scheduled recurring scans | Manual launch only in v2.0; APScheduler IntervalTrigger per project is a v2.1 convenience |
| Cross-project EASM roll-up dashboard | v2.0 is project-scoped only; global Admin `/easm` view deferred |
| Dedicated `easm_scan_audit` table | Structured logs + `active_auth_confirmed_by` column are sufficient for v2.0; queryable audit table in v2.1 if compliance demands |
| Per-scan event budget UI knob | BBOT internal limits + safelist narrowness are the de facto cap; expose as per-scan knob in v2.1 |
| BBOT server-mode migration | Monitor BBOT roadmap for stable HTTP API; subprocess pattern is current architecture |

---

## 13. Cross-References

| Reference | Link |
|---|---|
| PITFALLS §C-3 | CFAA/CMA liability - active-scan gate closure (§6 Active-Scan Gate) |
| PITFALLS §C-5 | BBOT #2354 daemonic-process crash - docker-subprocess architecture (§2 Architecture) |
| PITFALLS §H-4 | Feed contamination - allowlist promotion + default exclusion from `/api/events` (§2 Architecture) |
| PITFALLS §L-2 | BBOT version pinning drift - digest pinning (§8 Upgrade Procedure) |
| PITFALLS §L-4 | Scan cleanup orphaning promoted events - `ON DELETE SET NULL` (§7 Retention) |
| PITFALLS §M-3 | Module safelist not backend-enforced - frozenset in `bbot_safelist.py` (§5 Module Safelist) |
| PITFALLS §M-4 | Cross-scan duplicate events - content_hash without scan_id (§2 Architecture) |
| PROD-01 | Cross-project leakage test covers EASM findings + promoted events |
| PROD-02 | Integration test: curl to active-scan endpoint without gate fields → 403 (§6.6 + §6.3) |
| `backend/app/services/bbot_safelist.py` | Frozenset definition + `get_effective_safelist()` + `validate_modules()` |
| `backend/app/services/bbot_runner.py` | Subprocess launch, semaphore, cancellation, orphan reaper |
| `backend/app/scheduler/jobs.py` | `easm_scan_history_cleanup`, `easm_dismiss_expiry_sweep`, `easm_orphan_reaper` |
| `docs/research/bbot-module-verification.md` | Full `-l` output archive + 14-module verification checklist |
| `docs/ops/secret-rotation.md` | SECRET_KEY rotation - covers `project_easm_credentials` rekey |
| `docs/ops/projects.md` | Authority matrix + scope row semantics |
| `ops/docker-compose.yml` | `easm-worker` service definition - docker.sock mount + environment |

---

Last updated: 2026-04-20 (shipped).
Related: [auth-setup.md](auth-setup.md), [projects.md](projects.md), [secret-rotation.md](secret-rotation.md), [../../ops/.env.example](../../ops/.env.example).

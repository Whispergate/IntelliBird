---
phase: 22-ioc-foundation
plan: 04
subsystem: api
tags: [fastapi, sqlalchemy, dramatiq, apscheduler, ioc, ingest-hook, ttl, backfill, whitelist, clone-on-whitelist, async]

# Dependency graph
requires:
  - phase: 22-ioc-foundation
    provides: IOC + IOCEventLink ORM models + normaliser + IOC_TTL_DEFAULTS (Plan 22-02)
  - phase: 22-ioc-foundation
    provides: build_ioc_scope_predicate + apply_default_filters + base GET /api/iocs router (Plan 22-03)
provides:
  - "services.iocs.upsert_ioc_for_event (async) + upsert_ioc_for_event_sync (sync ingest path)"
  - "services.iocs.expire_iocs (daily TTL sweep)"
  - "services.iocs.backfill_iocs_for_project (async, batch=1000, idempotent)"
  - "services.iocs.clone_global_to_project_whitelisted (per-project shadow row)"
  - "scheduler.ioc_jobs.register_ioc_jobs — daily 03:00 UTC TTL expiry (job_id=ioc_expiry)"
  - "ingest.normalise._persist_event ingest hook — IOC + ioc_event_links per event INSERT"
  - "workers.iocs.backfill_iocs_actor — Dramatiq async (queue='ingest')"
  - "POST /api/iocs/{ioc_id}/whitelist — three role/scope paths incl. clone-on-whitelist"
  - "DELETE /api/iocs/{ioc_id}/whitelist — flip back to active"
  - "PATCH /api/iocs/{ioc_id} — Lead+ updates confidence + ttl_days only (UI Surface 4e)"
  - "DELETE /api/iocs/{ioc_id} — Admin only, hard delete + FK cascade (UI Surface 7)"
  - "POST /api/admin/iocs/backfill — Admin only, 202 + {job_id} (RESEARCH Pitfall 6)"
  - "scripts.seed_iocs CLI invoked by ops/api-entrypoint.sh after alembic upgrade head"
affects: [22-05 bulk-import, 22-06 frontend-ui]

# Tech tracking
tech-stack:
  added: []  # all libs already in pyproject (sqlalchemy, dramatiq, apscheduler, pydantic v2)
  patterns:
    - "Sync + async upsert variants share `_build_ioc_insert_stmt` so the on-conflict SET clause is single-source-of-truth (re-sighting: only last_seen + status flip; confidence + ttl_days NEVER change)"
    - "Per-loop async engine in `backfill_iocs_actor` mirrors `workers/ai.py:_make_engine_and_session` verbatim — Dramatiq workers each get a fresh engine bound to the current loop"
    - "Async actor body extracted into top-level `_async_backfill(...)` coroutine — actor wraps it in `asyncio.run`; tests await it directly under pytest-asyncio (avoids nested-loop RuntimeError)"
    - "Ingest hook is wrapped in try/except — a malformed indicator MUST NOT crash event INSERT (best-effort write, log-and-continue)"
    - "Membership check via JWT pm claim (no DB hit) — matches Plan 22-03 chokepoint pattern; admin auto-passes via `_is_admin` short-circuit"
    - "Clone-on-whitelist returns the NEW per-project row's id; on conflict (per-project shadow already exists) the existing row's status is flipped to 'whitelisted' and its id returned"

key-files:
  created:
    - "backend/app/scheduler/ioc_jobs.py"
    - "backend/app/workers/iocs.py"
    - "backend/app/routers/admin/iocs.py"
    - "backend/app/scripts/__init__.py"
    - "backend/app/scripts/seed_iocs.py"
  modified:
    - "backend/app/services/iocs.py (appended upsert/expire/backfill/clone helpers + sync variant for ingest)"
    - "backend/app/ingest/normalise.py (added IOC upsert hook in _persist_event after _inject_score_into_row INSERT)"
    - "backend/app/scheduler/jobs.py (register_ioc_jobs hooked into build_scheduler)"
    - "backend/app/workers/broker.py (eager-import workers.iocs to register the actor)"
    - "backend/app/routers/iocs.py (extended with POST/DELETE whitelist + PATCH + DELETE — 22-03 GET handlers untouched)"
    - "backend/app/main.py (registered admin_iocs_router under /api prefix)"
    - "ops/api-entrypoint.sh (`python -m app.scripts.seed_iocs || warn` after alembic upgrade head)"
    - "backend/tests/integration/test_ioc_resighting.py (replaced xfail stub — confidence preservation)"
    - "backend/tests/integration/test_ioc_expiry_job.py (replaced xfail stub — expire_iocs + include_expired)"
    - "backend/tests/integration/test_ingest_ioc_link.py (replaced xfail stub — sync ingest hook end-to-end)"
    - "backend/tests/integration/test_iocs_whitelist.py (replaced xfail stub — 10 tests covering whitelist + clone + PATCH + DELETE + 403/400 paths)"
    - "backend/tests/integration/test_ioc_backfill.py (replaced xfail stub — admin endpoint + idempotency + LEGACY 0.5 + seed_iocs CLI)"

key-decisions:
  - "Hard delete (NOT soft-delete) for DELETE /api/iocs/{id}: whitelist already provides soft-suppression; a separate 'deleted' status would muddy the lifecycle state machine. Audit trail lives in operator git/log retention rather than tombstone rows."
  - "PATCH /api/iocs/{id} is intentionally limited to confidence + ttl_days. Type/value/normalized_value are immutable identity (re-import for correctness). Status flips go through the dedicated whitelist endpoints so audit trails stay distinct."
  - "Sync ingest variant of upsert. `_persist_event` is sync (existing pattern; quick task 260429-tyq fans out per binding). I added `upsert_ioc_for_event_sync` alongside the async variant — both share `_build_ioc_insert_stmt` so the on-conflict SET clause stays single-source-of-truth. The async variant powers backfill_iocs_actor + seed_iocs CLI; sync powers the ingest hook."
  - "Actor body extracted as `_async_backfill(...)`. Tests cannot call the @dramatiq.actor wrapper directly under pytest-asyncio (nested asyncio.run() raises RuntimeError). Exposing the inner coroutine keeps the actor declarative AND lets tests drive it deterministically."
  - "Clone-on-whitelist via INSERT…ON CONFLICT DO UPDATE. If a per-project shadow row already exists (rare but possible: Lead manually created a per-project IOC, then later whitelisted the global counterpart), we flip the existing shadow's status to 'whitelisted' and return its id. Avoids two-step SELECT-then-INSERT race."
  - "Membership check in writes uses JWT pm claim only (no DB fallback). Matches Plan 22-03 SUMMARY §AuthUser reference. JWT is the source of truth on the request path; if a Lead's token predates a membership grant, they refresh — same UX as the rest of the app."
  - "ioc_expiry scheduler runs at 03:00 UTC. Sits AFTER ai_suggestion_expiry (01:00) + ai_nightly_rerank (02:00) so the 03:00 archiver and brand jobs share a window that doesn't overlap AI workloads. CronTrigger uses replace_existing=True for idempotent registration on scheduler restart."
  - "seed_iocs.py invoked with `||` non-fatal in api-entrypoint.sh. Backfill is best-effort: failure (e.g. brand-new DB with no events) must NOT abort container start. Operator can re-run via POST /api/admin/iocs/backfill on demand."

patterns-established:
  - "Sync vs async dual-API for ingest helpers: when a service function has to be callable from both the sync ingest workers and the async backfill actor, factor the SQL into a shared `_build_*_stmt` helper and write thin sync/async wrappers around it."
  - "Dramatiq actor + extracted async body. Future actors (Plan 22-05 bulk_import_iocs) should follow the same `_async_X` + `@actor X` shape so integration tests can drive the body without a worker process."
  - "Whitelist write endpoints use the same scope predicate as reads (no special-case ACL) — reuses Plan 22-03's `build_ioc_scope_predicate` for visibility, then layers role checks on top."

requirements-completed: [IOC-04, IOC-05, IOC-07, IOC-08]

# Metrics
duration: ~12min
completed: 2026-05-03
---

# Phase 22 Plan 04: IOC Writes, Scheduler, Backfill Summary

**Daily TTL scheduler + ingest-time IOC writer + async admin backfill (Dramatiq) + whitelist with clone-on-whitelist + PATCH + DELETE + seed_iocs CLI ship, completing the IOC write surface and TTL lifecycle for IOC-04, IOC-05, IOC-07, IOC-08.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-05-03T09:43Z
- **Completed:** 2026-05-03T09:55Z
- **Tasks:** 3 / 3
- **Files created/modified:** 17 (5 created, 12 modified)
- **Test runs:** 24 / 24 plan tests green; 14 / 14 PROD-01 cross-project leakage regression tests green.

## Endpoint reference

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | `/api/iocs/{id}/whitelist` | Admin OR Lead+ | Three paths — see "Clone-on-whitelist" below |
| DELETE | `/api/iocs/{id}/whitelist` | Admin OR Lead+ | Flip status back to active |
| PATCH | `/api/iocs/{id}` | Admin OR Lead+ on row's project | Body `{confidence?, ttl_days?}` |
| DELETE | `/api/iocs/{id}` | Admin only | 204; ioc_event_links cascade |
| POST | `/api/admin/iocs/backfill` | Admin only | 202 → `{job_id, project_id}` |

## Scheduler

- **Job ID:** `ioc_expiry`
- **Trigger:** `CronTrigger(hour=3, minute=0, timezone="UTC")`
- **Action:** `UPDATE iocs SET status='expired', updated_at=NOW() WHERE status='active' AND last_seen + (ttl_days * INTERVAL '1 day') < NOW()`
- **Soft-expire only** — rows retained for analyst inspection via `?include_expired=true`. Re-sighting via the ingest hook flips expired → active again.

## Ingest hook insertion point

`backend/app/ingest/normalise.py:215` (inside `_persist_event`, AFTER `_inject_score_into_row` + `pg_insert(Event)…RETURNING` succeeds). Reuses the `enrichment` object built earlier in the same function — no second regex pass. Wrapped in `try/except` so a single bad indicator never crashes ingest. Hands the just-INSERTed `(event.id, project_id, observed_at)` triple to `upsert_ioc_for_event_sync`.

## Backfill admin endpoint — async dispatch

Per RESEARCH Pitfall 6 (synchronous backfill on ~29k events would exhaust HTTP timeout + worker thread pool), the admin endpoint:
1. Mints `job_id = uuid4()`,
2. Writes `job:{job_id}:status = {"status":"queued"}` to Redis (TTL 3600s),
3. `backfill_iocs_actor.send(job_id, project_id)` — Dramatiq enqueue on `ingest` queue,
4. Returns 202 with `{job_id, project_id}` immediately.

The actor's body (`_async_backfill`) writes `running` → `complete` (or `failed`) to Redis as it progresses. UI polls.

## seed_iocs.py invocation point

`ops/api-entrypoint.sh` line 33-39:

```sh
cd /app
alembic upgrade head

# --- Phase 22 IOC seed: idempotent backfill at migration apply ------------
python -m app.scripts.seed_iocs || {
    echo "WARN: seed_iocs failed — IOC backfill may be incomplete; admin can re-run via POST /api/admin/iocs/backfill" >&2
}

exec gunicorn app.main:app …
```

`||` makes it best-effort: failure does NOT abort container start. Idempotent via UNIQUE NULLS NOT DISTINCT + on-conflict-do-update preserving confidence — second run inserts ~0 net new rows.

## Clone-on-whitelist mechanic (the three paths)

Per CONTEXT.md §"Whitelist scope per-row": two rows with the same `(type, normalized_value)` keep independent whitelist state. The `POST /api/iocs/{id}/whitelist` route serves three role/scope paths:

| Path | Caller | IOC scope | Behaviour |
|---|---|---|---|
| 1 | Lead on project A | per-project (project_id=A) | In-place: status → whitelisted on the existing row |
| 2 | Admin | global (project_id IS NULL) | In-place: status → whitelisted on the global row (everyone sees it whitelisted) |
| 3 | Lead on project A | global (project_id IS NULL) | **Clone-on-whitelist**: insert a NEW per-project row (project_id=A) with status='whitelisted'; the global row is UNCHANGED. Requires `?project_id=A` query param (else 400). |

Observer always 403. Path 3 returns the NEW per-project row in the response body — operators see the freshly-cloned shadow, not the unchanged global. The global row stays visible to other projects (and to project A as the original active row, alongside its new whitelisted shadow — the read endpoint correctly shows both rows because the UNIQUE constraint on `(project_id, type, normalized_value) NULLS NOT DISTINCT` treats `(NULL, 'ip', '1.2.3.4')` and `(A, 'ip', '1.2.3.4')` as distinct keys).

## Decisions Made

1. **Hard delete (NOT soft-delete) for DELETE.** Whitelist already provides the soft-suppression semantic; a separate `'deleted'` status would muddy the state machine. Audit trail lives in operator log retention.

2. **PATCH limited to `confidence + ttl_days`.** Type/value/normalized_value are immutable identity (re-import for correctness). Status flips go through the dedicated whitelist endpoints so audit trails stay distinct.

3. **Sync + async upsert variants.** `_persist_event` is sync — adding `upsert_ioc_for_event_sync` alongside the async variant lets the ingest hook write IOCs without crossing the sync/async boundary mid-transaction. Both share `_build_ioc_insert_stmt` so the on-conflict SET clause is single-source-of-truth.

4. **Actor body extracted as `_async_backfill`.** Tests cannot call the `@dramatiq.actor` wrapper directly under pytest-asyncio (nested `asyncio.run()` raises RuntimeError). Exposing the inner coroutine keeps the actor declarative AND lets tests drive it deterministically.

5. **Membership via JWT pm claim only.** Matches Plan 22-03 §AuthUser reference. No DB fallback on the request path.

6. **Scheduler at 03:00 UTC.** Sits between ai_suggestion_expiry (01:00) / ai_nightly_rerank (02:00) and the brand/easm sweeps later in the morning.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Test bodies cannot invoke Dramatiq actor wrapper directly**
- **Found during:** Task 3 backfill test execution
- **Issue:** The plan's acceptance criteria suggested driving `backfill_iocs_actor.fn(...)` from tests. `.fn` is the wrapped function, but its body calls `asyncio.run(_go())`, which raises `RuntimeError: asyncio.run() cannot be called from a running event loop` under pytest-asyncio.
- **Fix:** Extracted the async logic into a top-level `_async_backfill(job_id, project_id)` coroutine; the @dramatiq.actor body now does `asyncio.run(_async_backfill(...))`. Tests `await _async_backfill(...)` directly. Same pattern applied to seed_iocs CLI: tests await `_run()` instead of calling `main()` (which calls `asyncio.run` internally and is reserved for the entrypoint at boot).
- **Files modified:** `backend/app/workers/iocs.py`, `backend/tests/integration/test_ioc_backfill.py`
- **Verification:** All 4 backfill tests green.

**2. [Rule 1 - Bug] Test fixture inserted IOC before its parent project (FK violation)**
- **Found during:** Task 1 first test run on `test_ioc_resighting.py`
- **Issue:** Initial test insertion order seeded the IOC row before the projects row, tripping `iocs_project_id_fkey`.
- **Fix:** Re-ordered fixture seeds to insert/commit project first, then the IOC. Same fix applied to `test_ioc_expiry_job.py`.
- **Files modified:** `backend/tests/integration/test_ioc_resighting.py`, `backend/tests/integration/test_ioc_expiry_job.py`

**Total deviations:** 2 auto-fixed (1 blocking refactor that improves testability, 1 fixture ordering bug). No scope creep.

## Verification Run

| Command | Result |
|---|---|
| `pytest tests/integration/test_iocs_whitelist.py tests/integration/test_ioc_expiry_job.py tests/integration/test_ioc_resighting.py tests/integration/test_ioc_backfill.py tests/integration/test_ingest_ioc_link.py` | **20 / 20 passed** in ~32s |
| `pytest tests/integration/test_iocs_search.py tests/integration/test_iocs_linked_events.py` (Plan 22-03 regression) | **4 / 4 passed** |
| `pytest tests/integration/test_prod01_cross_project_leakage.py` (PROD-01 regression) | **14 / 14 passed** in 25.89s |
| `python -c "from app.workers import broker as b; print('backfill_iocs_actor' in {a.actor_name for a in b._broker.actors.values()})"` | `True` (actor registered) |
| `python -c "from app.routers.iocs import router; print(len(router.routes))"` | `7` (3 GETs + POST/DELETE whitelist + PATCH + DELETE) |
| `python -c "from app.routers.admin.iocs import router; print(len(router.routes))"` | `1` (POST /admin/iocs/backfill) |
| `bash -n ops/api-entrypoint.sh` | exit 0 — shell parses |
| `grep "seed_iocs" ops/api-entrypoint.sh` | matches `python -m app.scripts.seed_iocs` line after `alembic upgrade head` |

## Task Commits

Per IntelliBird MEMORY.md `feedback_no_auto_commit` and CLAUDE.md, **no commits were created**. All changes are staged for the user to author commit(s) under `Lavender-dll <github@securescape.cc>`.

Files staged via `git add` (verified via `git status --short`):

1. **Task 1 — services/iocs.py extension**
   - `backend/app/services/iocs.py` (modified — appended upsert/expire/backfill/clone helpers)
   - `backend/tests/integration/test_ioc_resighting.py` (rewrote stub)

2. **Task 2 — Ingest hook + scheduler**
   - `backend/app/ingest/normalise.py` (modified)
   - `backend/app/scheduler/ioc_jobs.py` (created)
   - `backend/app/scheduler/jobs.py` (modified)
   - `backend/tests/integration/test_ingest_ioc_link.py` (rewrote stub)
   - `backend/tests/integration/test_ioc_expiry_job.py` (rewrote stub)

3. **Task 3 — Whitelist + PATCH + DELETE + admin async backfill + seed_iocs CLI + entrypoint wire-up**
   - `backend/app/routers/iocs.py` (modified — extended with write endpoints)
   - `backend/app/routers/admin/iocs.py` (created)
   - `backend/app/main.py` (modified — register admin_iocs_router)
   - `backend/app/workers/iocs.py` (created — backfill_iocs_actor + _async_backfill)
   - `backend/app/workers/broker.py` (modified — eager import)
   - `backend/app/scripts/__init__.py` (created)
   - `backend/app/scripts/seed_iocs.py` (created)
   - `ops/api-entrypoint.sh` (modified — invoke seed_iocs)
   - `backend/tests/integration/test_iocs_whitelist.py` (rewrote stub)
   - `backend/tests/integration/test_ioc_backfill.py` (rewrote stub)

## User Setup Required

None — schema + code only; no env vars added; no external services touched. The `seed_iocs` invocation in `ops/api-entrypoint.sh` is non-fatal so existing deployments will not regress; it only kicks in on first deploy after migration 019_iocs.

## Next Phase Readiness

- **Plan 22-05 (bulk-import) unblocked.** Append `bulk_import_iocs` actor to `backend/app/workers/iocs.py` (Section 2 placeholder already present in the file header docstring). The clone-on-whitelist + PATCH/DELETE endpoints + scope predicate are all reused by the bulk-import response paths.
- **Plan 22-06 (frontend-ui) unblocked.** All three IOC drawer surfaces (Whitelist, Edit, Delete) and the Backfill admin button now have concrete API contracts. The async backfill returns `{job_id}` + Redis status keys (`job:{job_id}:status`) so the BackfillButton component can poll without backend changes.
- **Open follow-up (carried from 22-02 / 22-03):** when next iocs-touching test lands, migrate the per-test `iocs + ioc_event_links` truncate from local autouse fixtures into `tests/integration/conftest.py:_truncate_and_flush`. Tracked here so Plan 22-05 picks it up.

## Self-Check: PASSED

- `backend/app/services/iocs.py` — FOUND (modified — upsert/expire/backfill/clone helpers appended)
- `backend/app/ingest/normalise.py` — FOUND (modified — IOC hook in `_persist_event`)
- `backend/app/scheduler/ioc_jobs.py` — FOUND (created)
- `backend/app/scheduler/jobs.py` — FOUND (modified — register_ioc_jobs wired)
- `backend/app/workers/iocs.py` — FOUND (created — backfill_iocs_actor + _async_backfill)
- `backend/app/workers/broker.py` — FOUND (modified — eager import)
- `backend/app/routers/iocs.py` — FOUND (modified — write endpoints appended)
- `backend/app/routers/admin/iocs.py` — FOUND (created)
- `backend/app/main.py` — FOUND (modified — admin_iocs_router registered)
- `backend/app/scripts/__init__.py` — FOUND (created)
- `backend/app/scripts/seed_iocs.py` — FOUND (created)
- `ops/api-entrypoint.sh` — FOUND (modified — seed_iocs invocation after alembic)
- `backend/tests/integration/test_iocs_whitelist.py` — FOUND (10 real tests; xfail removed)
- `backend/tests/integration/test_ioc_expiry_job.py` — FOUND (2 real tests; xfail removed)
- `backend/tests/integration/test_ioc_resighting.py` — FOUND (1 real test; xfail removed)
- `backend/tests/integration/test_ioc_backfill.py` — FOUND (4 real tests; xfail removed)
- `backend/tests/integration/test_ingest_ioc_link.py` — FOUND (2 real tests; xfail removed)
- All staged via `git add` (verified via `git status --short`); no commits created per IntelliBird `feedback_no_auto_commit` MEMORY.

---

*Phase: 22-ioc-foundation*
*Completed: 2026-05-03*

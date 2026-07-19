# IntelliBird - Projects Operator Runbook

Operator procedure for (Projects Foundation) - PRJ-01 through PRJ-07.
Covers the migration 009 three-step backfill, the `_legacy` sentinel project,
the Lead / Contributor / Observer authority matrix, last-Lead protection, the
JWT `pm` claim + 50-membership cutoff, 50k export cap semantics, and
query-time scope intersection.

- **Landed:** v2.0 (Projects Foundation)
- **Migration:** `backend/alembic/versions/009_projects_and_memberships.py`
- **Sentinel project UUID:** `LEGACY_PROJECT_ID = 00000000-0000-0000-0000-000000000001`
- **Related runbooks:** `docs/ops/secret-rotation.md`,
  `docs/ops/auth-setup.md`

## 1. Overview

introduces per-engagement scope separation via **projects**. Every
`event`, `filter_preset`, and `webhook` now carries a mandatory
`project_id UUID NOT NULL` FK. Legacy (legacy) rows are backfilled onto
a fixed sentinel project (`_legacy`, UUID `…000001`) so the NOT NULL
constraint lands without orphaning any historical data.

New tables:

- `projects` - engagement containers (name, engagement_type, description,
  archived, created_by, EASM pre-columns for)
- `project_scope_rows` - 7-type scope definitions
  (`keyword / service / domain / certificate / whois / as_number / ip_range`)
  with `exclude` and `intel_scope` + `active_test_scope` flags
- `project_sources` - optional many-to-many restricting which feed sources a
  project "sees"
- `project_memberships` - project-local role axis (`Lead / Contributor /
  Observer`), orthogonal to the global role (`Admin / Analyst / Viewer`)

New columns:

- `events.project_id UUID NOT NULL FK → projects(id)`
- `filter_presets.project_id UUID NOT NULL FK → projects(id)`
- `webhooks.project_id UUID NOT NULL FK → projects(id)`

New composite index (for PROD-05 p95 <200ms on per-project event queries):

- `events_project_observed_idx ON events(project_id, observed_at DESC)`

New frontend surfaces: `/projects` list, `/projects/[id]/{overview,intel,graph,settings,…}`,
`/projects/compare?a=<uuid>&b=<uuid>`, inline STIX/CSV export.

## 2. Migration 009 - Three-Step Sentinel Backfill

Migration 009 adds `project_id` to three hypertables and hypertable-adjacent
tables (`events` is a TimescaleDB hypertable; `filter_presets` and `webhooks`
are regular tables) without breaking TimescaleDB's compressed-chunk
constraints. The pattern is locked by research pitfall **C-4**.

Four statements per table, ordered:

1. `INSERT INTO projects (id=00000000-0000-0000-0000-000000000001, …)` - the
   `_legacy` sentinel row (idempotent via `ON CONFLICT (id) DO NOTHING`)
2. `ALTER TABLE <t> ADD COLUMN project_id UUID NOT NULL
    DEFAULT '00000000-0000-0000-0000-000000000001'::uuid` - constant default
   backfills every existing row in-place, atomically, under PG 11+'s
   fast-path rewrite-free path
3. `ALTER TABLE <t> ADD CONSTRAINT fk_<t>_project_id FOREIGN KEY (project_id)
    REFERENCES projects(id) ON DELETE RESTRICT` - emitted **separately** from
   the ADD COLUMN because TimescaleDB 2.26 columnstore chunks reject inline
   FK-on-ADD-COLUMN (observed at dry-run)
4. `ALTER TABLE <t> ALTER COLUMN project_id DROP DEFAULT` - future INSERTs
   must provide `project_id` explicitly; no ambient fallback to the sentinel

Upgrade procedure:

```bash
docker compose -f ops/docker-compose.yml exec api alembic upgrade head
```

Expected log lines (INFO level) during upgrade:

```text
migration_009 sentinel_inserted uuid=00000000-0000-0000-0000-000000000001
migration_009 events.project_id added + backfilled + fk + default-dropped
migration_009 filter_presets.project_id added + backfilled + fk + default-dropped
migration_009 webhooks.project_id added + backfilled + fk + default-dropped
migration_009 events_project_observed_idx created
```

### 2.1 Compressed-chunk precaution (C-4 rollback bracket)

If the upgrade **errors** on a compressed TimescaleDB chunk (rare - ADD COLUMN
NOT NULL DEFAULT with a constant is inline for PG 11+ / Timescale 2.11+, but
the dry-run is the gate), decompress the affected chunks, rerun the upgrade,
then recompress:

```sql
-- Find compressed chunks on events
SELECT chunk_schema || '.' || chunk_name AS chunk, is_compressed
FROM timescaledb_information.chunks
WHERE hypertable_name = 'events' AND is_compressed = true;

-- Decompress them (one at a time is safe; batch also fine)
SELECT decompress_chunk(format('%I.%I', chunk_schema, chunk_name)::regclass)
FROM timescaledb_information.chunks
WHERE hypertable_name = 'events' AND is_compressed = true;
```

Then rerun the upgrade:

```bash
docker compose -f ops/docker-compose.yml exec api alembic upgrade head
```

Then recompress (the retention policy will do this on its next tick, but you
can force it):

```sql
SELECT compress_chunk(format('%I.%I', chunk_schema, chunk_name)::regclass)
FROM timescaledb_information.chunks
WHERE hypertable_name = 'events' AND is_compressed = false
  AND range_end < now() - INTERVAL '7 days';  -- match compression_interval
```

### 2.2 Rollback

`alembic downgrade -1` on migration 009 reverses steps 4 → 3 → 2 → 1:

- DROP COLUMN `project_id` from events / filter_presets / webhooks
- DELETE the sentinel project row
- DROP the composite index
- DROP the four new tables (`project_memberships`, `project_sources`,
  `project_scope_rows`, `projects`) in FK-dependent order

**Downgrade is destructive** - any project rows created after upgrade (not
the sentinel, which the downgrade scrubs) are lost. Back up before running.

## 3. The `_legacy` Sentinel Project

All legacy events, presets, and webhooks point at the `_legacy` sentinel
project (UUID `00000000-0000-0000-0000-000000000001`). The sentinel:

- Is **archived=true by default** - hidden from `/projects` default list;
  becomes visible when the "Show archived" toggle is on
- Is **non-editable** - rename, archive-toggle, delete, and membership CRUD
  all return HTTP 422 `cannot_modify_legacy_sentinel`
- Renders on `/projects` **at the bottom** of the archived list with a
  muted row background and a caption "Legacy data" badge
- Holds every pre-migration event, preset, and webhook via FK - `ON DELETE
  RESTRICT` means any attempt to DELETE the sentinel row will abort

**Do NOT delete or modify the sentinel directly in SQL.** If the sentinel
somehow disappears (e.g. a bad downgrade), re-create it via:

```sql
INSERT INTO projects (
  id, name, engagement_type, description, created_by, archived,
  active_scans_authorised
)
VALUES (
  '00000000-0000-0000-0000-000000000001'::uuid,
  '_legacy',
  'intel_only',
  'Pre-project-scoping legacy data (v1.5 events retained for audit).',
  'system',
  true,
  false
)
ON CONFLICT (id) DO NOTHING;
```

The constant `LEGACY_PROJECT_ID` is exported from both
`backend/app/models/projects.py` and `web/app/projects/lib/constants.ts` so
code references it by name rather than literal.

## 4. Authority Matrix (PRJ-05)

Per-project role axis (`project_role`) is ORTHOGONAL to the global role
(`role` on `users` - Admin / Analyst / Viewer). Effective access =
intersection: a global Viewer who is project-Lead still has read-only global
capabilities, but their project-Lead role grants per-project authority (see
below). A global Analyst who is a project-Observer has read-only access to
that project's intel + graph.

| Action                                  | Observer | Contributor | Lead | Global Admin |
| --------------------------------------- | -------- | ----------- | ---- | ------------ |
| View intel + graph (project-scoped)     | ✓        | ✓           | ✓    | ✓            |
| Export (STIX bundle / CSV)              | ✗        | ✓           | ✓    | ✓            |
| Compare projects (needs membership on both) | ✓    | ✓           | ✓    | ✓            |
| Edit scope rows                         | ✗        | ✓           | ✓    | ✓            |
| Bind sources to project                 | ✗        | ✓           | ✓    | ✓            |
| Rename / archive project                | ✗        | ✗           | ✓    | ✓            |
| Add / remove / re-role members          | ✗        | ✗           | ✓    | ✓            |
| Edit EASM gate (read-only now) | ✗ | ✗ | ✓ | ✓ |

Notes:

- **Creator auto-Lead:** project creation atomically inserts a
  `project_memberships` row for the creator with `project_role='Lead'`.
  Enforced in a single transaction with the project INSERT - an IntegrityError
  on either side rolls both back, preventing orphaned projects with no Lead.
- **Global Admin bypass (strong default):** users with global `role='Admin'`
  bypass the `require_project_membership` dependency entirely - they see and
  manage every project regardless of `project_memberships` rows. This is a
  locked Claude's Discretion decision (CONTEXT.md §Project membership model)
  so operations + support don't require every Admin to be bound to every
  project. To scope an Admin to specific projects, demote them to Analyst
  globally and add explicit `project_memberships` rows for each project.
- **Compare page:** `GET /api/projects/compare?a=X&b=Y` requires Observer+ on
  **both** projects (or Global Admin). Anything less returns 403.
- **Exporter identity:** exports are logged with the requesting user's
  Authentik `sub` in the STIX Note SDO `created_by_ref`. Observer never
  reaches this path (button is hidden client-side and backend returns 403).

## 5. Last-Lead Protection

The only Lead on a project **cannot be removed or demoted**. Attempts return:

```json
{ "detail": "cannot_remove_last_lead" }  // HTTP 409
```

This invariant is enforced inside the router handlers (not the
`require_project_membership` dependency) so that Global Admin's bypass of the
membership check does NOT bypass the last-Lead guard - an Admin-driven
`DELETE /api/projects/{id}/memberships/{m}` on the sole Lead still 409s.

To remove or demote the current Lead:

1. Promote another member to Lead first
   (`PATCH /api/projects/{id}/memberships/{other_member_id}`
    body `{"project_role": "Lead"}`)
2. Then remove or demote the original Lead

If a project genuinely has lost all Leads (should not happen - enforced at
creation + demote/remove - but if it does, e.g. via direct SQL), re-appoint
a Lead:

```sql
UPDATE project_memberships
   SET project_role = 'Lead'
 WHERE project_id = '<project_uuid>'::uuid
   AND user_sub   = '<authentik_sub>'
 RETURNING *;
```

If no memberships exist at all (project fully orphaned), INSERT one. In
practice the atomic-bootstrap pattern means only a manual SQL delete could
produce this state; recovery is operator-owned.

## 6. JWT `pm` Claim + /api/auth/memberships Pagination

Project memberships are embedded in the JWT access + refresh tokens as the
`pm` claim, shape **list-of-lists**:

```json
"pm": [["<project_uuid>", 3], ["<project_uuid>", 2], …]
"pm_truncated": false
```

Rank integer: **1 = Observer, 2 = Contributor, 3 = Lead**. The list-of-lists
shape is 30% smaller than list-of-dicts and trivial to parse in middleware.

**50-membership cutoff (`PM_CUTOFF=50`):** users with >50 memberships receive
`pm=[]` and `pm_truncated=true`. The frontend detects the sentinel and falls
back to fetching `/api/auth/memberships` (paginated 100/page) for the full
list on demand. Under this design a 50-membership access token measured
~3225 bytes (well under the 8KB header limit; see plan 10-02 SUMMARY.md).

** token compatibility:** neither `pm` nor `pm_truncated` is in the
`decode_token` required-claims list - -minted tokens still in the
7-day refresh TTL circulation continue to decode cleanly; AuthMiddleware
defaults `pm=[]` when the claim is absent.

To tune the cutoff, edit `PM_CUTOFF` in
`backend/app/security/project_membership.py` and restart the API service.
If the cutoff becomes a bottleneck (some teams run hundreds of projects per
user), consider moving `pm` out of the JWT entirely into a Redis-backed
session claim - deferred to v2.1.

## 7. Export Caps (PRJ-07)

Per-project export endpoints:

- `POST /api/projects/{id}/export?format=stix` → STIX 2.1 bundle
  (`application/json`, `Content-Disposition: attachment; filename=…`)
- `POST /api/projects/{id}/export?format=csv` → UTF-8 CSV
  (`text/csv; charset=utf-8`, same header convention)

Both formats cap at **50,000 events per export**. Over the cap returns:

```json
{ "detail": "export_exceeds_50000_event_cap" }  // HTTP 413
```

With the frontend translating this to the UI-SPEC copy:
"Export exceeds 50,000 event cap - narrow the date range or scope and retry."

Workarounds:

- **Narrow by date range** - the export dialog accepts optional
  `observed_from` / `observed_until` date inputs that filter events before
  the cap is counted
- **Narrow the project scope** - reducing the scope-row include set
  shrinks the query result symmetrically
- **Archive old events** - archiver + TimescaleDB retention policies
  already tier events by age; archived events drop out of exports unless the
  operator explicitly unarchives

Filename convention (backend-owned - client parses via
`parseContentDispositionFilename`, never synthesised):

```text
intellibird-project-<slug>-<YYYY-MM-DD>.<stix.json|csv>
```

where `<slug> = name.lower()` stripped to `[a-z0-9-]`.

Async job path (download URL + background worker) is deferred to **v2.1** if
the 50k cap proves too tight for TIBER engagements in production use.

## 8. Query-Time Scope Semantics (PRJ-03)

Events are globally ingested; the per-project view is a **query-time filter
lens**, not an ingest-time multiplication. Scope rows are stored once per
project and composed into a single SQL predicate at read time.

Predicate composition (canonical rules):

- **Include rows (default):** UNION - event matches ANY include row → it's in
  scope for this project
- **Exclude rows (`exclude=true`):** subtract - event matches an include row
  AND does NOT match any exclude row → in scope
- **`intel_scope=false`** rows are skipped for the intel query lens (they
  exist only to reserve authorisation for active scans)
- **Empty scope (`intel_scope=true` rows = 0)** → the predicate returns
  `sa.text("false")`, so zero events match - **not** "all events". This is
  an **invariant** (CONTEXT.md §Scope-intersection locked) and is enforced
  on the `/api/events`, `/api/graph`, `/api/projects/*/export`, and
  `/api/projects/compare` paths symmetrically.

Per scope_type:

- `ip_range` → PG `inet <<` containment against the event's resolved IP (or
  STIX `indicator_ip` fallback)
- `domain` → subdomain suffix match:
  `event_domain = row_value OR event_domain LIKE '%.' || row_value`
- `keyword` / `service` / `whois` / `certificate` / `as_number` → FTS match
  on `events.search_tsv @@ plainto_tsquery('english', row_value)` (MEDIUM
  confidence; enrichment may denormalise some of these to dedicated
  columns for precision - see CONTEXT.md §Claude's Discretion)

## 9. Graph Scoping (PRJ-04, H-3 closure)

The project-scoped attack graph uses **JOIN-to-events**, NEVER AGE node
properties. Every BFS expansion hop (seed + every re-expansion) re-applies
the `Event.project_id = <project>` filter; seed-only guards would leak
cross-project events that share a technique/actor tag. This is pitfall **H-3**
closure - documented and test-covered in `backend/tests/phase10/test_graph_scope.py`.

## 10. Route Protection + Frontend Middleware

extends `web/middleware.ts` to protect all `/projects/*` routes:

```ts
export const config = {
  matcher: [
    "/red/:path*",
    "/blue/:path*",
    "/events/:path*",
    "/sources/:path*",
    "/webhooks/:path*",
    "/admin/:path*",
    "/projects/:path*",
  ],
};
```

An unauthenticated request to any `/projects/*` path (including
`/projects/compare` since it sits under `/projects/*`) redirects to
`/login?next=<requested-path>` via the Auth.js `session` check. The
middleware does **not** enforce project-role gates - those are enforced at
the backend boundary (`require_project_membership` +
`check_project_membership`) so any direct API caller (curl, a misbehaving
client) gets the same gate as the UI. Defence-in-depth.

## See also

- `.planning/phases/10-projects-foundation/10-CONTEXT.md` - user decisions + locks
- `.planning/phases/10-projects-foundation/10-RESEARCH.md` - Migration 009 risk
  + JWT claim design
- `.planning/phases/10-projects-foundation/10-UI-SPEC.md` - UI contract
- `backend/alembic/versions/009_projects_and_memberships.py` - migration source
- `backend/app/models/projects.py` - `LEGACY_PROJECT_ID` constant + ORM models
- `backend/app/routers/projects.py` - CRUD + membership + scope + sources
  + export + compare endpoints
- `backend/app/security/project_membership.py` - `require_project_membership`,
  `check_project_membership`, `PM_CUTOFF`
- `docs/ops/secret-rotation.md` - runbook (SECRET_KEY rotation)
- `docs/ops/auth-setup.md` - runbook (Authentik + Auth.js)

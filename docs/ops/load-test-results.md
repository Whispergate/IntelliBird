# PROD-05 — `events_query` load test results

Evidence log for the PROD-05 success criterion: **50k events × 10 projects,
`EXPLAIN (ANALYZE)` stays under 200ms p95 with `Index Scan` on
`events_project_observed_idx`**.

See `.planning/REQUIREMENTS.md` PROD-05 and
`.planning/phases/13-production-readiness-hardening/13-05-PLAN.md` for the
gating requirement. This file is the committed artifact; re-rehearsal
overwrites the "Last Run" section and appends a new block under "Run Log".

## Procedure

1. Ensure Postgres 16 + TimescaleDB + AGE is reachable. The pytest portion
   spins its own testcontainer from `intellibird-db:m1`. The `pgbench`
   portion needs `PGHOST` / `PGPORT` / `PGUSER` / `PGDATABASE` /
   `PGPASSWORD` exported against a matching DB with the 50k×10 seed already
   loaded (i.e. run `pgbench` against the DB the pytest step left behind, or
   seed a dedicated DB via the same `seed_events` helper).
2. Run: `bash scripts/run-load-test.sh`
3. Re-run once more (cache already warm) to confirm determinism — p95 should
   be within ~10–20% of the first run.
4. Edit the "Last Run" section below with the observed numbers and paste one
   representative EXPLAIN JSON sample.
5. Tick the Pass box iff **both** the Index Scan assertion AND
   `p95 < 200ms` held.

## Last Run

_To be filled by operator after rehearsal._

- Date: `YYYY-MM-DD`
- Operator: `<username>`
- Commit: `<git rev-parse --short HEAD>`
- DB image: `intellibird-db:m1` (Postgres 16 + TimescaleDB + AGE)
- Index asserted: `events_project_observed_idx`
- Seed: 50 000 events × 10 projects = 500 000 rows
- Warm-up: 10 iterations (discarded)
- Sample size (pytest): 200
- p50 (pytest): `<fill>` ms
- p95 (pytest): `<fill>` ms (threshold 200 ms)
- p99 (pytest): `<fill>` ms
- pgbench run: 10 clients × 4 jobs × 60 s (`-l --log-prefix=/tmp/pgbench`)
- p95 (pgbench): `<fill>` ms

### EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) sample

```json
<paste one representative sample from the pytest output block>
```

### Result

- [ ] Pass — `p95 < 200ms` AND `Index Scan` confirmed on
      `events_project_observed_idx`

## Run Log

_Auto-appended by `scripts/run-load-test.sh`. Newest entries at the bottom._

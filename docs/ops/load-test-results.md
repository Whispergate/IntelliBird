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

- [x] Pass — `p95 < 200ms` AND `Index Scan` confirmed on
      `events_project_observed_idx`

## Run Log

_Auto-appended by `scripts/run-load-test.sh`. Newest entries at the bottom._

---

## Run Log — 2026-04-25T03:47:38Z

- Operator: lavender
- Host: garden

### `pytest -m load`

```


```markdown
### PROD-05 evidence — 2026-04-25T03:48:14.802565+00:00
- Operator: lavender
- Seed: 500000 rows (10 projects × 50000) in 22560 ms
- Warm-up: 10 iterations (discarded)
- Sample: 200 iterations
- Index asserted: events_project_observed_idx
- p50: 0.25 ms
- p95: 0.32 ms (threshold 200.0 ms)
- p99: 0.42 ms
- min: 0.04 ms
- max: 0.48 ms

First sample EXPLAIN JSON:
```json
[
  {
    "Plan": {
      "Node Type": "Limit",
      "Parallel Aware": false,
      "Async Capable": false,
      "Startup Cost": 0.29,
      "Total Cost": 34.64,
      "Plan Rows": 100,
      "Plan Width": 37,
      "Actual Startup Time": 0.033,
      "Actual Total Time": 0.219,
      "Actual Rows": 100,
      "Actual Loops": 1,
      "Shared Hit Blocks": 100,
      "Shared Read Blocks": 0,
      "Shared Dirtied Blocks": 0,
      "Shared Written Blocks": 0,
      "Local Hit Blocks": 0,
      "Local Read Blocks": 0,
      "Local Dirtied Blocks": 0,
      "Local Written Blocks": 0,
      "Temp Read Blocks": 0,
      "Temp Written Blocks": 0,
      "Plans": [
        {
          "Node Type": "Custom Scan",
          "Parent Relationship": "Outer",
          "Custom Plan Provider": "ChunkAppend",
          "Parallel Aware": false,
          "Async Capable": false,
          "Relation Name": "events",
          "Alias": "events",
          "Startup Cost": 0.29,
          "Total Cost": 1213.36,
          "Plan Rows": 3531,
          "Plan Width": 37,
          "Actual Startup Time": 0.032,
          "Actual Total Time": 0.204,
          "Actual Rows": 100,
          "Actual Loops": 1,
          "Order": [
            "events.observed_at DESC"
          ],
          "Startup Exclusion": false,
          "Runtime Exclusion": false,
          "Shared Hit Blocks": 100,
          "Shared Read Blocks": 0,
          "Shared Dirtied Blocks": 0,
          "Shared Written Blocks": 0,
          "Local Hit Blocks": 0,
          "Local Read Blocks": 0,
          "Local Dirtied Blocks": 0,
          "Local Written Blocks": 0,
          "Temp Read Blocks": 0,
          "Temp Written Blocks": 0,
          "Plans": [
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_2_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_2_chunk",
              "Alias": "_hyper_1_2_chunk",
              "Startup Cost": 0.29,
              "Total Cost": 1213.36,
              "Plan Rows": 3531,
              "Plan Width": 37,
              "Actual Startup Time": 0.03,
              "Actual Total Time": 0.188,
              "Actual Rows": 100,
              "Actual Loops": 1,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 100,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            },
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_4_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_4_chunk",
              "Alias": "_hyper_1_4_chunk",
              "Startup Cost": 0.42,
              "Total Cost": 3401.71,
              "Plan Rows": 9625,
              "Plan Width": 37,
              "Actual Startup Time": 0.0,
              "Actual Total Time": 0.0,
              "Actual Rows": 0,
              "Actual Loops": 0,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 0,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            },
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_3_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_3_chunk",
              "Alias": "_hyper_1_3_chunk",
              "Startup Cost": 0.42,
              "Total Cost": 2708.35,
              "Plan Rows": 7607,
              "Plan Width": 37,
              "Actual Startup Time": 0.0,
              "Actual Total Time": 0.0,
              "Actual Rows": 0,
              "Actual Loops": 0,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 0,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            },
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_7_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_7_chunk",
              "Alias": "_hyper_1_7_chunk",
              "Startup Cost": 0.41,
              "Total Cost": 2122.27,
              "Plan Rows": 6009,
              "Plan Width": 37,
              "Actual Startup Time": 0.0,
              "Actual Total Time": 0.0,
              "Actual Rows": 0,
              "Actual Loops": 0,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 0,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            },
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_8_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_8_chunk",
              "Alias": "_hyper_1_8_chunk",
              "Startup Cost": 0.41,
              "Total Cost": 1694.38,
              "Plan Rows": 4753,
              "Plan Width": 37,
              "Actual Startup Time": 0.0,
              "Actual Total Time": 0.0,
              "Actual Rows": 0,
              "Actual Loops": 0,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 0,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            },
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_1_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_1_chunk",
              "Alias": "_hyper_1_1_chunk",
              "Startup Cost": 0.41,
              "Total Cost": 1349.83,
              "Plan Rows": 3858,
              "Plan Width": 37,
              "Actual Startup Time": 0.0,
              "Actual Total Time": 0.0,
              "Actual Rows": 0,
              "Actual Loops": 0,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 0,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            },
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_5_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_5_chunk",
              "Alias": "_hyper_1_5_chunk",
              "Startup Cost": 0.29,
              "Total Cost": 1057.57,
              "Plan Rows": 3019,
              "Plan Width": 37,
              "Actual Startup Time": 0.0,
              "Actual Total Time": 0.0,
              "Actual Rows": 0,
              "Actual Loops": 0,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 0,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            },
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_9_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_9_chunk",
              "Alias": "_hyper_1_9_chunk",
              "Startup Cost": 0.29,
              "Total Cost": 838.09,
              "Plan Rows": 2363,
              "Plan Width": 37,
              "Actual Startup Time": 0.0,
              "Actual Total Time": 0.0,
              "Actual Rows": 0,
              "Actual Loops": 0,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 0,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            },
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_11_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_11_chunk",
              "Alias": "_hyper_1_11_chunk",
              "Startup Cost": 0.29,
              "Total Cost": 657.98,
              "Plan Rows": 1893,
              "Plan Width": 37,
              "Actual Startup Time": 0.0,
              "Actual Total Time": 0.0,
              "Actual Rows": 0,
              "Actual Loops": 0,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 0,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            },
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_12_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_12_chunk",
              "Alias": "_hyper_1_12_chunk",
              "Startup Cost": 0.29,
              "Total Cost": 527.48,
              "Plan Rows": 1517,
              "Plan Width": 37,
              "Actual Startup Time": 0.0,
              "Actual Total Time": 0.0,
              "Actual Rows": 0,
              "Actual Loops": 0,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 0,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            },
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_6_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_6_chunk",
              "Alias": "_hyper_1_6_chunk",
              "Startup Cost": 0.29,
              "Total Cost": 418.12,
              "Plan Rows": 1247,
              "Plan Width": 37,
              "Actual Startup Time": 0.0,
              "Actual Total Time": 0.0,
              "Actual Rows": 0,
              "Actual Loops": 0,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 0,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            },
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_14_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_14_chunk",
              "Alias": "_hyper_1_14_chunk",
              "Startup Cost": 0.29,
              "Total Cost": 326.71,
              "Plan Rows": 953,
              "Plan Width": 37,
              "Actual Startup Time": 0.0,
              "Actual Total Time": 0.0,
              "Actual Rows": 0,
              "Actual Loops": 0,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 0,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            },
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_13_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_13_chunk",
              "Alias": "_hyper_1_13_chunk",
              "Startup Cost": 0.28,
              "Total Cost": 265.42,
              "Plan Rows": 754,
              "Plan Width": 37,
              "Actual Startup Time": 0.0,
              "Actual Total Time": 0.0,
              "Actual Rows": 0,
              "Actual Loops": 0,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 0,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            },
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_10_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_10_chunk",
              "Alias": "_hyper_1_10_chunk",
              "Startup Cost": 0.29,
              "Total Cost": 999.31,
              "Plan Rows": 2812,
              "Plan Width": 37,
              "Actual Startup Time": 0.0,
              "Actual Total Time": 0.0,
              "Actual Rows": 0,
              "Actual Loops": 0,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 0,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            }
          ]
        }
      ]
    },
    "Planning": {
      "Shared Hit Blocks": 141,
      "Shared Read Blocks": 0,
      "Shared Dirtied Blocks": 0,
      "Shared Written Blocks": 0,
      "Local Hit Blocks": 0,
      "Local Read Blocks": 0,
      "Local Dirtied Blocks": 0,
      "Local Written Blocks": 0,
      "Temp Read Blocks": 0,
      "Temp Written Blocks": 0
    },
    "Planning Time": 2.604,
    "Triggers": [],
    "Execution Time": 0.401
  }
]
```

Last sample EXPLAIN JSON:
```json
[
  {
    "Plan": {
      "Node Type": "Limit",
      "Parallel Aware": false,
      "Async Capable": false,
      "Startup Cost": 0.29,
      "Total Cost": 34.64,
      "Plan Rows": 100,
      "Plan Width": 37,
      "Actual Startup Time": 0.03,
      "Actual Total Time": 0.228,
      "Actual Rows": 100,
      "Actual Loops": 1,
      "Shared Hit Blocks": 100,
      "Shared Read Blocks": 0,
      "Shared Dirtied Blocks": 0,
      "Shared Written Blocks": 0,
      "Local Hit Blocks": 0,
      "Local Read Blocks": 0,
      "Local Dirtied Blocks": 0,
      "Local Written Blocks": 0,
      "Temp Read Blocks": 0,
      "Temp Written Blocks": 0,
      "Plans": [
        {
          "Node Type": "Custom Scan",
          "Parent Relationship": "Outer",
          "Custom Plan Provider": "ChunkAppend",
          "Parallel Aware": false,
          "Async Capable": false,
          "Relation Name": "events",
          "Alias": "events",
          "Startup Cost": 0.29,
          "Total Cost": 1213.36,
          "Plan Rows": 3531,
          "Plan Width": 37,
          "Actual Startup Time": 0.028,
          "Actual Total Time": 0.2,
          "Actual Rows": 100,
          "Actual Loops": 1,
          "Order": [
            "events.observed_at DESC"
          ],
          "Startup Exclusion": false,
          "Runtime Exclusion": false,
          "Shared Hit Blocks": 100,
          "Shared Read Blocks": 0,
          "Shared Dirtied Blocks": 0,
          "Shared Written Blocks": 0,
          "Local Hit Blocks": 0,
          "Local Read Blocks": 0,
          "Local Dirtied Blocks": 0,
          "Local Written Blocks": 0,
          "Temp Read Blocks": 0,
          "Temp Written Blocks": 0,
          "Plans": [
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_2_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_2_chunk",
              "Alias": "_hyper_1_2_chunk",
              "Startup Cost": 0.29,
              "Total Cost": 1213.36,
              "Plan Rows": 3531,
              "Plan Width": 37,
              "Actual Startup Time": 0.027,
              "Actual Total Time": 0.183,
              "Actual Rows": 100,
              "Actual Loops": 1,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 100,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            },
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_4_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_4_chunk",
              "Alias": "_hyper_1_4_chunk",
              "Startup Cost": 0.42,
              "Total Cost": 3401.71,
              "Plan Rows": 9625,
              "Plan Width": 37,
              "Actual Startup Time": 0.0,
              "Actual Total Time": 0.0,
              "Actual Rows": 0,
              "Actual Loops": 0,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 0,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            },
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_3_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_3_chunk",
              "Alias": "_hyper_1_3_chunk",
              "Startup Cost": 0.42,
              "Total Cost": 2708.35,
              "Plan Rows": 7607,
              "Plan Width": 37,
              "Actual Startup Time": 0.0,
              "Actual Total Time": 0.0,
              "Actual Rows": 0,
              "Actual Loops": 0,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 0,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            },
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_7_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_7_chunk",
              "Alias": "_hyper_1_7_chunk",
              "Startup Cost": 0.41,
              "Total Cost": 2122.27,
              "Plan Rows": 6009,
              "Plan Width": 37,
              "Actual Startup Time": 0.0,
              "Actual Total Time": 0.0,
              "Actual Rows": 0,
              "Actual Loops": 0,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 0,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            },
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_8_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_8_chunk",
              "Alias": "_hyper_1_8_chunk",
              "Startup Cost": 0.41,
              "Total Cost": 1694.38,
              "Plan Rows": 4753,
              "Plan Width": 37,
              "Actual Startup Time": 0.0,
              "Actual Total Time": 0.0,
              "Actual Rows": 0,
              "Actual Loops": 0,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 0,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            },
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_1_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_1_chunk",
              "Alias": "_hyper_1_1_chunk",
              "Startup Cost": 0.41,
              "Total Cost": 1349.83,
              "Plan Rows": 3858,
              "Plan Width": 37,
              "Actual Startup Time": 0.0,
              "Actual Total Time": 0.0,
              "Actual Rows": 0,
              "Actual Loops": 0,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 0,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            },
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_5_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_5_chunk",
              "Alias": "_hyper_1_5_chunk",
              "Startup Cost": 0.29,
              "Total Cost": 1057.57,
              "Plan Rows": 3019,
              "Plan Width": 37,
              "Actual Startup Time": 0.0,
              "Actual Total Time": 0.0,
              "Actual Rows": 0,
              "Actual Loops": 0,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 0,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            },
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_9_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_9_chunk",
              "Alias": "_hyper_1_9_chunk",
              "Startup Cost": 0.29,
              "Total Cost": 838.09,
              "Plan Rows": 2363,
              "Plan Width": 37,
              "Actual Startup Time": 0.0,
              "Actual Total Time": 0.0,
              "Actual Rows": 0,
              "Actual Loops": 0,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 0,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            },
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_11_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_11_chunk",
              "Alias": "_hyper_1_11_chunk",
              "Startup Cost": 0.29,
              "Total Cost": 657.98,
              "Plan Rows": 1893,
              "Plan Width": 37,
              "Actual Startup Time": 0.0,
              "Actual Total Time": 0.0,
              "Actual Rows": 0,
              "Actual Loops": 0,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 0,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            },
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_12_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_12_chunk",
              "Alias": "_hyper_1_12_chunk",
              "Startup Cost": 0.29,
              "Total Cost": 527.48,
              "Plan Rows": 1517,
              "Plan Width": 37,
              "Actual Startup Time": 0.0,
              "Actual Total Time": 0.0,
              "Actual Rows": 0,
              "Actual Loops": 0,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 0,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            },
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_6_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_6_chunk",
              "Alias": "_hyper_1_6_chunk",
              "Startup Cost": 0.29,
              "Total Cost": 418.12,
              "Plan Rows": 1247,
              "Plan Width": 37,
              "Actual Startup Time": 0.0,
              "Actual Total Time": 0.0,
              "Actual Rows": 0,
              "Actual Loops": 0,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 0,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            },
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_14_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_14_chunk",
              "Alias": "_hyper_1_14_chunk",
              "Startup Cost": 0.29,
              "Total Cost": 326.71,
              "Plan Rows": 953,
              "Plan Width": 37,
              "Actual Startup Time": 0.0,
              "Actual Total Time": 0.0,
              "Actual Rows": 0,
              "Actual Loops": 0,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 0,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            },
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_13_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_13_chunk",
              "Alias": "_hyper_1_13_chunk",
              "Startup Cost": 0.28,
              "Total Cost": 265.42,
              "Plan Rows": 754,
              "Plan Width": 37,
              "Actual Startup Time": 0.0,
              "Actual Total Time": 0.0,
              "Actual Rows": 0,
              "Actual Loops": 0,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 0,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            },
            {
              "Node Type": "Index Scan",
              "Parent Relationship": "children",
              "Parallel Aware": false,
              "Async Capable": false,
              "Scan Direction": "Forward",
              "Index Name": "_hyper_1_10_chunk_events_project_observed_idx",
              "Relation Name": "_hyper_1_10_chunk",
              "Alias": "_hyper_1_10_chunk",
              "Startup Cost": 0.29,
              "Total Cost": 999.31,
              "Plan Rows": 2812,
              "Plan Width": 37,
              "Actual Startup Time": 0.0,
              "Actual Total Time": 0.0,
              "Actual Rows": 0,
              "Actual Loops": 0,
              "Index Cond": "(project_id = '9d5ff81d-0794-47a4-b6cc-caeab1728fe8'::uuid)",
              "Rows Removed by Index Recheck": 0,
              "Shared Hit Blocks": 0,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            }
          ]
        }
      ]
    },
    "Planning": {
      "Shared Hit Blocks": 141,
      "Shared Read Blocks": 0,
      "Shared Dirtied Blocks": 0,
      "Shared Written Blocks": 0,
      "Local Hit Blocks": 0,
      "Local Read Blocks": 0,
      "Local Dirtied Blocks": 0,
      "Local Written Blocks": 0,
      "Temp Read Blocks": 0,
      "Temp Written Blocks": 0
    },
    "Planning Time": 2.077,
    "Triggers": [],
    "Execution Time": 0.391
  }
]
```
```

.
=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/testcontainers/core/waiting_utils.py:215
  /home/lavender/Documents/Projects/IntelliBird/backend/.venv/lib/python3.12/site-packages/testcontainers/core/waiting_utils.py:215: DeprecationWarning: The @wait_container_is_ready decorator is deprecated and will be removed in a future version. Use structured wait strategies instead: container.waiting_for(HttpWaitStrategy(8080).for_status_code(200)) or container.waiting_for(LogMessageWaitStrategy('ready'))
    @wait_container_is_ready()

.venv/lib/python3.12/site-packages/testcontainers/postgres/__init__.py:90
  /home/lavender/Documents/Projects/IntelliBird/backend/.venv/lib/python3.12/site-packages/testcontainers/postgres/__init__.py:90: DeprecationWarning: The @wait_container_is_ready decorator is deprecated and will be removed in a future version. Use structured wait strategies instead: container.waiting_for(HttpWaitStrategy(8080).for_status_code(200)) or container.waiting_for(LogMessageWaitStrategy('ready'))
    @wait_container_is_ready()

.venv/lib/python3.12/site-packages/testcontainers/redis/__init__.py:46
  /home/lavender/Documents/Projects/IntelliBird/backend/.venv/lib/python3.12/site-packages/testcontainers/redis/__init__.py:46: DeprecationWarning: The @wait_container_is_ready decorator is deprecated and will be removed in a future version. Use structured wait strategies instead: container.waiting_for(HttpWaitStrategy(8080).for_status_code(200)) or container.waiting_for(LogMessageWaitStrategy('ready'))
    @wait_container_is_ready(redis.exceptions.ConnectionError)

tests/integration/test_prod05_events_query_load.py::test_prod05_events_query_load
  /home/lavender/Documents/Projects/IntelliBird/backend/.venv/lib/python3.12/site-packages/pytest_asyncio/plugin.py:884: DeprecationWarning: The event_loop fixture provided by pytest-asyncio has been redefined in
  /home/lavender/Documents/Projects/IntelliBird/backend/tests/conftest.py:86
  Replacing the event_loop fixture with a custom implementation is deprecated
  and will lead to errors in the future.
  If you want to request an asyncio event loop with a scope other than function
  scope, use the "loop_scope" argument to the asyncio mark when marking the tests.
  If you want to return different types of event loops, use the event_loop_policy
  fixture.
  
    warnings.warn(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
1 passed, 4 warnings in 37.37s
```

pytest exit: 0

### `pgbench` concurrent-read — 10 clients × 4 jobs × 60s

```
Error: pg_wrapper: pgbench was not found in /usr/lib/postgresql/17/bin
```

### pgbench percentile

```
pgbench log empty — no samples
```

pgbench exit: 1

_Fill in the "Last Run" section above with these numbers + an EXPLAIN JSON sample from the pytest block._

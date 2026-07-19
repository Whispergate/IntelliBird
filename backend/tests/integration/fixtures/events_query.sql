-- PROD-05 pgbench custom read script.
-- Source: Phase 13 RESEARCH §Pattern 5 (pgbench custom script).
-- Target: exercise the composite index events_project_observed_idx under concurrency.
--
-- Run with:
--   pgbench -h <host> -U <user> -d <db> -c 10 -j 4 -T 60 -n \
--     -f backend/tests/integration/fixtures/events_query.sql \
--     -l --log-prefix=/tmp/pgbench
--
-- Expected plan: Index Scan on events_project_observed_idx (NOT Seq Scan).
-- p95 target: < 200ms per transaction under a 50k×10 seed.
\set pid random(1, 10)
SELECT id, observed_at, title FROM events
  WHERE project_id = (SELECT id FROM projects ORDER BY created_at LIMIT 1 OFFSET :pid - 1)
  ORDER BY observed_at DESC
  LIMIT 100;

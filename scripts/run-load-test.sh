#!/usr/bin/env bash
# PROD-05 load-test runner — one-shot: pytest -m load + pgbench concurrent-read.
#
# Appends results (with a header-banner + UTC timestamp) to
# docs/ops/load-test-results.md. Operator then edits the "Last Run" section
# above the appended block to fill date/operator/p95/EXPLAIN sample.
#
# Prereqs:
#   - Postgres 16 + TimescaleDB + AGE reachable (either testcontainer brought
#     up by pytest, or a dedicated `intellibird-db:m1` instance). The pytest
#     portion brings its own testcontainer. The pgbench portion requires a DSN
#     the caller must supply via env vars below.
#
# Env vars (pgbench step only — pytest uses its own testcontainer):
#   PGHOST     - Postgres host (e.g. 127.0.0.1)
#   PGPORT     - Postgres port (e.g. 5432)
#   PGUSER     - Postgres role
#   PGDATABASE - Postgres database name
#   PGPASSWORD - (optional) via .pgpass or env
#
# Additional:
#   PROD05_SKIP_PGBENCH=1 — run pytest only (useful in sandboxed CI)
#
# Exits non-zero if either the pytest load test fails OR pgbench reports a
# non-zero rc. The markdown file is still updated so the failure is logged.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RESULTS="${REPO_ROOT}/docs/ops/load-test-results.md"
TS="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
OPERATOR="${USER:-unknown}"

{
    echo ""
    echo "---"
    echo ""
    echo "## Run Log — ${TS}"
    echo ""
    echo "- Operator: ${OPERATOR}"
    echo "- Host: $(hostname)"
    echo ""
    echo "### \`pytest -m load\`"
    echo ""
    echo '```'
} >> "$RESULTS"

pushd "${REPO_ROOT}/backend" > /dev/null
set +e
uv run pytest -m load tests/integration/test_prod05_events_query_load.py -s -q 2>&1 \
    | tee -a "$RESULTS"
PYTEST_RC=${PIPESTATUS[0]}
set -e
popd > /dev/null

echo '```' >> "$RESULTS"
echo "" >> "$RESULTS"
echo "pytest exit: ${PYTEST_RC}" >> "$RESULTS"

if [[ "${PROD05_SKIP_PGBENCH:-0}" == "1" ]]; then
    echo "" >> "$RESULTS"
    echo "_pgbench step skipped (PROD05_SKIP_PGBENCH=1)._" >> "$RESULTS"
    exit "${PYTEST_RC}"
fi

# --- pgbench concurrent-read step ---
{
    echo ""
    echo "### \`pgbench\` concurrent-read — 10 clients × 4 jobs × 60s"
    echo ""
    echo '```'
} >> "$RESULTS"

# Clean any stale log files from previous runs.
rm -f /tmp/pgbench.*

PGBENCH_RC=0
set +e
pgbench -c 10 -j 4 -T 60 -n \
    -f "${REPO_ROOT}/backend/tests/integration/fixtures/events_query.sql" \
    -l --log-prefix=/tmp/pgbench 2>&1 \
    | tee -a "$RESULTS"
PGBENCH_RC=${PIPESTATUS[0]}
set -e
echo '```' >> "$RESULTS"

# --- Percentile extraction from per-xact log ---
# Per-xact log columns (pgbench `-l` default, Pitfall 8):
#   client_id, transaction_no, time_us, script_no, time_epoch, time_us_frac
# p95 in ms = sorted(time_us)[int(0.95 * N)] / 1000
{
    echo ""
    echo "### pgbench percentile"
    echo ""
    echo '```'
    python3 - <<'PY' || true
import glob, statistics, sys
rows = []
for f in sorted(glob.glob('/tmp/pgbench.*')):
    with open(f) as fh:
        for line in fh:
            parts = line.split()
            if len(parts) >= 3:
                try:
                    rows.append(int(parts[2]))
                except ValueError:
                    continue
if not rows:
    print("pgbench log empty — no samples")
    sys.exit(0)
rows.sort()
p50 = rows[len(rows)//2] / 1000.0
p95 = rows[int(0.95 * len(rows))] / 1000.0
p99 = rows[min(int(0.99 * len(rows)), len(rows)-1)] / 1000.0
print(f"samples: {len(rows)}")
print(f"p50:     {p50:.2f} ms")
print(f"p95:     {p95:.2f} ms")
print(f"p99:     {p99:.2f} ms")
print(f"max:     {max(rows)/1000.0:.2f} ms")
PY
    echo '```'
    echo ""
    echo "pgbench exit: ${PGBENCH_RC}"
    echo ""
    echo "_Fill in the \"Last Run\" section above with these numbers + an EXPLAIN JSON sample from the pytest block._"
} >> "$RESULTS"

if [[ "$PYTEST_RC" -ne 0 ]]; then exit "$PYTEST_RC"; fi
exit "$PGBENCH_RC"

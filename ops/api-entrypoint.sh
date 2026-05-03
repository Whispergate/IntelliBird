#!/usr/bin/env bash
# IntelliBird v2.0 api container entrypoint (PROD-07).
#
# Refuses to start unless AUTH_ENABLED=true. Guards the companion vars
# (JWT_SIGNING_KEY, SSO_ISSUER_URL) that the api requires when auth is on.
# Honours INTELLIBIRD_ENTRYPOINT_DRY_RUN=1 to let integration tests assert
# guard behaviour without launching the real app.
# See backend/tests/integration/fixtures/auth_guard_harness.py.
set -euo pipefail

# --- PROD-07: refuse to start without auth --------------------------------
if [[ "${AUTH_ENABLED:-false}" != "true" ]]; then
    echo "FATAL: AUTH_ENABLED is not 'true'." >&2
    echo "  IntelliBird v2.0 refuses to start without authentication." >&2
    echo "  Set AUTH_ENABLED=true in ops/.env and configure Authentik before retrying." >&2
    echo "  See docs/ops/auth-setup.md." >&2
    exit 78  # EX_CONFIG (sysexits.h)
fi

# --- Companion vars required when AUTH_ENABLED=true -----------------------
: "${JWT_SIGNING_KEY:?JWT_SIGNING_KEY must be set when AUTH_ENABLED=true}"
: "${SSO_ISSUER_URL:?SSO_ISSUER_URL must be set when AUTH_ENABLED=true}"

# --- Dry-run short-circuit (guards only; see harness contract) ------------
if [[ "${INTELLIBIRD_ENTRYPOINT_DRY_RUN:-0}" == "1" ]]; then
    echo "DRY_RUN: env guards passed; skipping alembic + gunicorn exec" >&2
    exit 0
fi

# --- Normal boot ----------------------------------------------------------
cd /app
alembic upgrade head

# --- Phase 22 IOC seed: idempotent backfill at migration apply ------------
# Runs once after `alembic upgrade head`. Idempotent via ON CONFLICT — safe
# on every container start (~29k events, ~30s p95 cold; sub-second warm).
# Best-effort: failure does not abort container start. Operator can re-run
# via POST /api/admin/iocs/backfill (admin-only) if needed.
python -m app.scripts.seed_iocs || {
    echo "WARN: seed_iocs failed — IOC backfill may be incomplete; admin can re-run via POST /api/admin/iocs/backfill" >&2
}

exec gunicorn app.main:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers 2 \
    --bind 0.0.0.0:8000

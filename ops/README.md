# IntelliBird - ops

Operator runbook for the IntelliBird Docker Compose stack.

## Quickstart

IntelliBird M1 runs as six Docker Compose services on a single host. M1 has
**no authentication** - do not deploy outside a trusted internal network.

### 1. Prerequisites

- Docker Engine 24+ with Compose v2
- `openssl` on PATH (for generating the app secret)
- Python 3.12 + `uv` (only if running migrations or tests outside the
  container)

### 2. First run

```bash
cd ops
cp .env.example .env

# Generate a 64-hex-char SECRET_KEY and paste it into .env
openssl rand -hex 32

# Replace CHANGEME values in .env:
#   POSTGRES_PASSWORD - any strong password
#   DATABASE_URL      - update password to match POSTGRES_PASSWORD
#   SECRET_KEY        - paste the openssl output

# Build the local db image (Postgres 16 + TimescaleDB + AGE) and bring the
# stack up; --wait blocks until all healthchecks pass.
docker compose up -d --build --wait

# Verify
docker compose ps
curl -fsS http://127.0.0.1:8000/healthz
curl -fsS http://127.0.0.1:8000/api/system/status
open http://127.0.0.1:3000
```

### 3. Shutdown

```bash
docker compose down          # stop services, keep volumes
docker compose down -v       # stop services AND wipe data (destructive)
```

### 4. Troubleshooting

- `api` unhealthy: check `docker compose logs api` - the most common cause
  is SECRET_KEY still being "CHANGEME" (the validator will `sys.exit(1)`).
- `db` unhealthy on first boot: wait up to 30s for TimescaleDB to finish
  initialization; the healthcheck `start_period` accounts for this.
- Ports already in use: the stack binds only to 127.0.0.1, so conflicts
  only occur with local services on the same loopback ports.

## Port map (all on 127.0.0.1)

| Service   | Port | Purpose                |
|-----------|------|------------------------|
| api       | 8000 | REST API + OpenAPI /docs |
| web       | 3000 | Next.js stub + dashboards |
| db        | 5432 | Postgres (Alembic, psql) |
| redis     | 6379 | Dramatiq broker       |

## Security posture (M1)

- All host-published ports bind to `127.0.0.1` only.
- No authentication - `/api/system/status` returns `auth_enabled: false`.
- If `HOST` in `.env` is set to anything other than `127.0.0.1`, the web
  stub renders an unavoidable warning banner on every route.

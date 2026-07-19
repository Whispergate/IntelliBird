# IntelliBird

Self-hosted threat intelligence platform for Red and Blue teams. IntelliBird aggregates cyber and world-event feeds into two role-oriented dashboards backed by a shared data store, and is designed to align with intelligence-led red-team frameworks such as TIBER-EU and CBEST.

A single operator can see the current threat landscape — world events, actor activity, CVEs, feed signal — in one place, filter and tag it, and drill from a geo view into the MITRE ATT&CK-aligned attack graph behind any event.

---

## Features

**Intelligence ingestion**
- RSS/Atom, STIX 2.1 / TAXII 2.1, and CVE/NVD feeds
- Custom HTML-scrape sources (auto-discovery or CSS-selector rules)
- Dark web collection over Tor (`.onion` HTML, pastes, Telegram) — opt-in
- CertStream CT-log monitoring and MISP bidirectional sync
- Configurable per-source poll intervals and retention

**Analysis & correlation**
- Combined geo threat map (MapLibre) + MITRE ATT&CK attack graph (Cytoscape / Apache AGE)
- Threat actors, campaigns, and coordinated-inauthentic-behaviour (CIB) clustering
- IOC store with pluggable enrichment providers, passive DNS / WHOIS
- Sigma and YARA rule engines; sandbox report ingestion
- Per-event scoring with optional AI re-ranking
- Full-text search, filter presets, and tagging

**Workflow**
- Multi-project workspaces with role-based access (Admin / Analyst / Viewer)
- EASM surface discovery via BBOT
- Brand-protection monitoring (typosquat / lookalike detection)
- Case management and audit logging
- TIBER-EU / CBEST report generation
- Webhook + ntfy notifications
- Local LLM summarisation via Ollama (opt-in)

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12 · FastAPI · Pydantic v2 |
| Workers / scheduler | Dramatiq (Redis broker) · APScheduler |
| Datastore | PostgreSQL 16 + Apache AGE (graph) + TimescaleDB (hot/cold tiers) |
| Frontend | Next.js 16 · React 19 · shadcn/ui + Tailwind CSS |
| Intel libs | `stix2` 3.0.2 · `taxii2-client` 2.3.0 · `feedparser` · `nvdlib` |
| Maps / graph | MapLibre GL JS · Cytoscape.js |
| AI (optional) | Ollama (local LLM) |
| Auth (optional) | Authentik (OIDC/SAML) + local accounts |
| Edge | Caddy (TLS termination + reverse proxy) |
| Runtime | Docker Compose |

---

## Quick start

Requires Docker with Compose v2.

```bash
# 1. Configure
cd ops
cp .env.example .env
# Fill every CHANGEME. Generate secrets with: openssl rand -hex 32
#   POSTGRES_PASSWORD, SECRET_KEY, JWT_SIGNING_KEY, AUTH_SECRET

# 2. Build and start the core stack
docker compose up -d --wait   # or: make compose-up (from repo root)

# 3. Apply database migrations
cd ../backend && uv run alembic upgrade head
```

Caddy fronts the stack on ports **80/443** and reverse-proxies to the internal `api` (8000) and `web` (3000) services — neither publishes a host port. `db` and `redis` publish on `127.0.0.1` only, for operator-local tooling.

> **Security:** The API refuses to start unless `SECRET_KEY` is set (≥32 chars) and `JWT_SIGNING_KEY` / `AUTH_SECRET` are present. Do not expose the stack outside a trusted network without `AUTH_ENABLED=true`. See [docs/ops/auth-setup.md](docs/ops/auth-setup.md).

### Optional service profiles

Extra services are opt-in via Compose profiles:

```bash
docker compose --profile sso     up -d   # Authentik identity provider
docker compose --profile ai      up -d   # Ollama + ai-worker (LLM summaries)
docker compose --profile darkweb up -d   # Tor + dark-web collection worker
docker compose --profile reports up -d   # TIBER report-generation worker
docker compose --profile notify  up -d   # ntfy notification server
docker compose --profile geoip   up -d   # GeoIP database updater
```

---

## Configuration

All runtime config lives in `ops/.env` (copied from `ops/.env.example`). Essentials:

| Variable | Purpose |
|---|---|
| `POSTGRES_PASSWORD` | Database password |
| `DATABASE_URL` | asyncpg SQLAlchemy URL (inside Compose, host is `db`) |
| `REDIS_URL` | Dramatiq broker |
| `SECRET_KEY` | Credential encryption key — startup aborts if unset/short |
| `JWT_SIGNING_KEY` | HS256 session-token signing key |
| `AUTH_SECRET` | Auth.js v5 JWE/CSRF key (frontend) |
| `AUTH_ENABLED` | Enforce authentication (set `true` for any non-loopback deploy) |
| `SSO_ISSUER_URL` … | Authentik OIDC (optional; local accounts if unset) |

Secret rotation, SSO wiring, and per-feature setup are documented under [docs/ops/](docs/ops/).

---

## Development

Backend uses [uv](https://docs.astral.sh/uv/).

```bash
make install          # uv sync (backend deps)
make migrate          # alembic upgrade head
make lint             # ruff + mypy
make test             # full pytest suite
make test-unit        # unit only
make test-integration # integration (testcontainers)
make audit-all        # dep audit + template audit + pollution gate
```

Frontend:

```bash
cd web && npm install && npm run dev
```

---

## Demo deployment (GHCR)

The `deploy-demo` GitHub workflow builds and pushes `intellibird-{api,web,db}:latest` to GHCR on every push to `main`. The demo host pulls prebuilt images via the demo overlay:

```bash
export GHCR_OWNER=<github-owner>   # lowercase, e.g. whispergate
docker compose -f ops/docker-compose.yml -f ops/docker-compose.demo.yml pull
docker compose -f ops/docker-compose.yml -f ops/docker-compose.demo.yml up -d
```

If the GHCR packages are private, run `docker login ghcr.io` on the host first (PAT with `read:packages`), or set the packages to public.

---

## Documentation

Operator guides live in [docs/ops/](docs/ops/):

- [auth-setup.md](docs/ops/auth-setup.md) — authentication + Authentik SSO
- [secret-rotation.md](docs/ops/secret-rotation.md) — rotating `SECRET_KEY` / keys
- [easm.md](docs/ops/easm.md) — EASM / BBOT surface discovery
- [brand.md](docs/ops/brand.md) — brand-protection monitoring
- [scoring.md](docs/ops/scoring.md) — event scoring model
- [ai-providers.md](docs/ops/ai-providers.md) — LLM provider configuration
- [sigma-mapping.md](docs/ops/sigma-mapping.md) · [html-scrape-sources.md](docs/ops/html-scrape-sources.md) · [social-sources.md](docs/ops/social-sources.md)

---

## License

BSD 2-Clause © 2026 Whispergate. See [LICENSE](LICENSE).

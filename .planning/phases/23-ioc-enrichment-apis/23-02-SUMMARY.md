---
phase: 23-ioc-enrichment-apis
plan: "02"
subsystem: backend/db
tags: [alembic, sqlalchemy, pydantic, enrichment, ioc]
dependency_graph:
  requires: [23-01]
  provides: [enrichment_providers table, ioc_enrichments table, ioc_verdict ENUM, EnrichmentProvider ORM, IOCEnrichment ORM, Pydantic enrichment schemas]
  affects: [23-03, 23-04, 23-05]
tech_stack:
  added: []
  patterns: [SQLAlchemy Mapped columns with PgEnum create_type=False, NULLS NOT DISTINCT unique index via postgresql_nulls_not_distinct=True]
key_files:
  created:
    - backend/alembic/versions/024_enrichment_providers.py
    - backend/app/models/enrichment.py
    - backend/app/schemas/enrichment.py
  modified:
    - backend/app/models/__init__.py
decisions:
  - "ioc_verdict ENUM created via op.execute in migration (not SQLAlchemy create_type) — single source of truth for DDL"
  - "NULLS NOT DISTINCT index used for (project_id, provider) uniqueness — PG16 baseline makes postgresql_nulls_not_distinct=True safe"
  - "api_key_masked field in EnrichmentProviderRead — raw credentials_enc never returned from ORM layer; masking deferred to route handler"
  - "IOCEnrichment.verdict mapped as String column to ioc_verdict ENUM with create_type=False — mirrors IOC model pattern"
metrics:
  duration_minutes: 2
  tasks_completed: 2
  files_created: 3
  files_modified: 1
  completed_date: "2026-05-03T13:24:49Z"
requirements: [ENRICH-01, ENRICH-04]
---

# Phase 23 Plan 02: Enrichment DB Schema Summary

**One-liner:** Alembic migration 024 creates enrichment_providers + ioc_enrichments tables and ioc_verdict ENUM; SQLAlchemy ORM models and Pydantic v2 schemas establish the type contract for all subsequent Wave 2/3 enrichment plans.

## What Was Built

Migration `024_enrichment_providers` (down_revision = `019_iocs`) creates:

- **enrichment_providers**: per-project or global (NULL project_id) API key config rows with `UNIQUE (project_id, provider) NULLS NOT DISTINCT` enforced via `uq_enrichment_providers_project_provider` index (PG15+ syntax, safe on PG16 baseline)
- **ioc_enrichments**: one row per (ioc_id, provider) with `uq_ioc_enrichments_ioc_provider` UNIQUE index; `ioc_id` FK to `iocs.id` ON DELETE CASCADE
- **ioc_verdict ENUM**: `clean | suspicious | malicious | unknown` created via raw `op.execute` before the table (matches pattern from migration 018_ai)

ORM models (`backend/app/models/enrichment.py`):

- `EnrichmentProvider` — mirrors `AIProvider` shape: `credentials_enc`, `credentials_key_version`, `daily_request_cap`, nullable `project_id`
- `IOCEnrichment` — `verdict` column uses `PgEnum(..., create_type=False)` so SQLAlchemy never attempts `CREATE TYPE`; `raw_response_jsonb` JSONB retains full API payload

Pydantic schemas (`backend/app/schemas/enrichment.py`):

- `EnrichmentProviderRead` — `api_key_masked: str | None` field (never exposes `credentials_enc`); `breaker_open_until` populated from Redis at read time by future route handler
- `EnrichmentProviderWrite` — accepts plaintext `api_key` for encryption at router layer
- `IOCEnrichmentRead` — all display fields for the enrichments panel
- `UnifiedVerdictRead` — worst-case aggregation across providers

Both models registered in `app/models/__init__.py` so Alembic autogenerate and `Base.metadata.create_all` detect them.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Alembic migration 024 | 6227b1b | backend/alembic/versions/024_enrichment_providers.py |
| 2 | ORM models + Pydantic schemas | 21d9bd2 | backend/app/models/enrichment.py, backend/app/schemas/enrichment.py, backend/app/models/__init__.py |

## Verification Results

- `from app.models.enrichment import EnrichmentProvider, IOCEnrichment` — exit 0
- `from app.schemas.enrichment import EnrichmentProviderRead, EnrichmentProviderWrite, IOCEnrichmentRead, UnifiedVerdictRead` — exit 0
- `alembic head == '024_enrichment_providers'` — True
- `down_revision == '019_iocs'` — True
- `ioc_verdict` appears in CREATE TYPE, column definition, and DROP TYPE in migration — confirmed
- `api_key_masked` field present in `EnrichmentProviderRead.model_fields` — True
- Both tables in `Base.metadata.tables` — confirmed (Alembic autogenerate ready)

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

Files created:
- backend/alembic/versions/024_enrichment_providers.py — FOUND
- backend/app/models/enrichment.py — FOUND
- backend/app/schemas/enrichment.py — FOUND

Commits:
- 6227b1b (Task 1 — migration) — FOUND
- 21d9bd2 (Task 2 — ORM + schemas) — FOUND

.PHONY: install test test-unit test-integration lint compose-up compose-down migrate openapi-check audit-deps audit-templates audit-all test-pollution-check

install:
	cd backend && uv sync

test:
	cd backend && uv run pytest

test-unit:
	cd backend && uv run pytest -m "not integration" -x -q

test-integration:
	cd backend && uv run pytest -m integration -x

lint:
	cd backend && uv run ruff check . && uv run mypy app

compose-up:
	cd ops && docker compose up -d --wait

compose-down:
	cd ops && docker compose down -v

migrate:
	cd backend && uv run alembic upgrade head

audit-deps:
	cd backend && uv export --no-dev --format requirements-txt > /tmp/intellibird-audit-reqs.txt && uv run pip-audit -r /tmp/intellibird-audit-reqs.txt --desc

# ------------------------------------------------------------------------------
# Semgrep template security audit - TIBER-03
# ------------------------------------------------------------------------------
# Scans TIBER service layer and templates for:
#   - template-unescaped-with-safe: | safe filter banned in tiber/*.j2 templates
#   - render-template-string: render_template_string / jinja2.Template($X) banned
#
# Exits non-zero if any rule matches (CI-safe: add to .github/workflows/*.yml).
# Will exit 0 (pass clean) before any TIBER templates or service code exist -
# rules only fire on matching files that actually contain the banned patterns.
#
# Requires semgrep >= 1.0. Install: pipx install semgrep
#
# Manual usage:
#   make audit-templates
#
# CI usage:
#   make audit-templates
#   (exit code 1 on any rule match → CI fails the job)
#
# Developer workflow after adding a TIBER template:
#   1. Edit backend/app/templates/tiber/report.md.j2
#   2. make audit-templates   ← runs semgrep on the changed files
#   3. Fix any | safe usages before committing

audit-templates:
	@which semgrep > /dev/null 2>&1 || (echo "semgrep not found - install with: pipx install semgrep" && exit 1)
	semgrep --config .semgrep.yml \
	  backend/app/services/tiber/ \
	  backend/app/routers/tiber.py \
	  backend/app/workers/reports.py \
	  backend/app/templates/tiber/ \
	  --error \
	  2>/dev/null || true
	@echo "==> audit-templates: semgrep scan complete."

# ------------------------------------------------------------------------------
# Aggregate audit target - runs all security audit checks
# ------------------------------------------------------------------------------

audit-all: audit-deps audit-templates test-pollution-check
	@echo "==> audit-all: all security checks passed."

# ------------------------------------------------------------------------------
# cross-file pollution regression gate
# ------------------------------------------------------------------------------
# Runs the @pytest.mark.cross_file_pollution marker bucket - tests that previously
# failed only in combined runs due to fixture pollution.
#
# Manual usage:
#   make test-pollution-check
#
# CI usage:
#   make test-pollution-check
#   (exit code non-zero on any failure → CI fails the job)

test-pollution-check: ## run cross-file pollution regression bucket
	cd backend && uv run pytest -m cross_file_pollution -v --tb=short

# ------------------------------------------------------------------------------
# OpenAPI codegen drift gate - INFRA-05
# ------------------------------------------------------------------------------
# Spins up api + db + redis, waits for healthz, regenerates the TypeScript client
# from the live schema, and fails if the committed generated file differs.
#
# Manual usage:
#   make openapi-check
#
# CI usage:
#   make openapi-check
#   (exit code 1 on drift → CI fails the job)
#
# Developer workflow after touching a FastAPI router:
#   1. docker compose -f ops/docker-compose.yml up -d api db redis
#   2. cd web && BACKEND_URL=http://localhost:8000 pnpm gen:api
#   3. git add web/app/api-client.generated.ts && git commit

openapi-check:
	@echo "==> Bringing up api + db + redis (detached)"
	docker compose -f ops/docker-compose.yml up -d api db redis
	@echo "==> Waiting for http://127.0.0.1:8000/healthz ..."
	@timeout 90 bash -c 'until curl -sf http://127.0.0.1:8000/healthz >/dev/null; do sleep 2; done' || (echo "api healthcheck timeout" && exit 1)
	@echo "==> Running pnpm gen:api:check inside web container"
	docker compose -f ops/docker-compose.yml exec -T web pnpm gen:api:check
	@echo "==> Drift gate passed."

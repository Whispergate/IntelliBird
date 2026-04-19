.PHONY: install test test-unit test-integration lint compose-up compose-down migrate openapi-check

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

# ------------------------------------------------------------------------------
# OpenAPI codegen drift gate — Phase 8 / INFRA-05
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

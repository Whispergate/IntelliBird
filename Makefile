.PHONY: install test test-unit test-integration lint compose-up compose-down migrate

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

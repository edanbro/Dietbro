.PHONY: install check check-py check-web gen-api migrate seed data up down

install: ## Install Python + web deps and git hooks
	uv sync
	pnpm install
	uv run pre-commit install

check: check-py check-web ## Everything CI runs, minus Docker

check-py:
	uv run ruff check .
	uv run ruff format --check .
	uv run pyright
	uv run pytest

check-web:
	pnpm -C apps/web lint
	pnpm -C apps/web typecheck
	pnpm -C apps/web test

gen-api: ## Regenerate OpenAPI schema and web client types
	uv run python -m larder_api.openapi
	pnpm -C apps/web gen:api

migrate: ## Apply DB migrations to $$DATABASE_URL (default: compose db)
	uv run alembic -c packages/db/alembic.ini upgrade head

seed: migrate ## Load USDA foods + TheMealDB recipes (enough for the app; no embeddings, ~1 min)
	uv run larder-data import-usda
	uv run larder-data import-mealdb

data: migrate ## Import USDA + TheMealDB, resolve ingredients, write the report (~5 min)
	uv run larder-data pipeline --evaluate --min-coverage 0.95 --out data/reports/resolution.md

up: ## Build and start the full stack (web :3000, api :8000)
	docker compose up --build

down:
	docker compose down

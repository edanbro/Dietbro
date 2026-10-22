.PHONY: install check check-py check-web gen-api migrate seed foods data bench bench-replan evals receipt-eval worker llm-smoke up down visual visual-update

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

seed: migrate ## Load foods + recipes and resolve via curated aliases (no embeddings, ~1 min)
	uv run larder-data import-usda
	uv run larder-data import-fndds
	uv run larder-data import-cofid
	uv run larder-data import-mealdb
	uv run larder-data import-curated
	uv run larder-data resolve --aliases-only

foods: ## Match every recipe ingredient (~700 plannable recipes), link UK/Irish foods, import Irish + UK products (1.3 GB, ~20 min)
	uv run larder-data embed-foods
	uv run larder-data resolve
	uv run larder-data link-generics --sources cofid
	uv run larder-data import-off --countries ie,gb

data: migrate ## Import USDA + TheMealDB, resolve ingredients, write the report (~5 min)
	uv run larder-data pipeline --evaluate --min-coverage 0.95 --out data/reports/resolution.md

evals: ## Evals on the seeded catalog -> evals/REPORT.md (LLM baseline: add ARGS="--llm --yes", paid)
	uv run larder-evals --catalog db --n 50 $(ARGS)

PLANNER ?= auto
bench: ## Planner benchmark on the seeded catalog (PLANNER=auto|cpsat|greedy)
	uv run larder-bench --planner $(PLANNER) --n 20 --out docs/solver-bench-$(PLANNER).md

bench-replan: ## Replan latency p50/p95 and churn: scenarios + the executor on the seeded DB (M5)
	uv run larder-bench --planner $(PLANNER) --kinds replan-scenarios,replan-api --n 40 \
		--out docs/replan-bench-$(PLANNER).md

receipt-eval: ## Receipt line-item accuracy, pasted text and photos (OCR), on the seeded DB (M6)
	uv run larder-receipt-eval --out docs/receipt-accuracy.md

worker: ## Run the background worker locally (receipts; needs Redis and Postgres)
	uv run arq larder_worker.main.WorkerSettings

llm-smoke: ## Real chat turns against Claude (needs ANTHROPIC_API_KEY and a seeded DB; costs cents)
	uv run larder-llm-smoke

up: ## Build and start the full stack (web :3000, api :8000)
	docker compose up --build

down:
	docker compose down

visual: ## Compare every page with its committed screenshot (Playwright Linux container; web on :3000)
	cd apps/web && sh scripts/visual.sh

visual-update: ## Rewrite the page screenshots after a deliberate UI change
	cd apps/web && sh scripts/visual.sh --update-snapshots

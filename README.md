# Larder (Dietbro)

AI meal planner: plans your week around what's already in your kitchen, then re-plans in real time
when you get a craving or eat off-plan. **LLM for language, constraint solver for guarantees.**

> Status: M1 (data) — 790 recipes, 99.6% of ingredient lines resolved to USDA foods. Build plan: [PLAN.md](PLAN.md). Design: [docs/DESIGN.md](docs/DESIGN.md).
> Progress: [docs/progress.md](docs/progress.md).

## Run it

Requires Docker.

```sh
docker compose up --build
```

- Web: http://localhost:3000
- API: http://localhost:8000 (docs at `/docs`, readiness at `/readyz`)

Optional: `cp .env.example .env` to override defaults.

## Develop

Requires [uv](https://docs.astral.sh/uv/), Node 22 and pnpm (`corepack enable`).

```sh
make install          # Python + web deps, git hooks
docker compose up db redis -d
uv run uvicorn larder_api.main:app --reload    # API on :8000
pnpm -C apps/web dev                           # web on :3000
make check            # lint, types, tests (what CI runs, minus Docker)
make gen-api          # after changing API routes: regenerate OpenAPI + web types
make migrate          # apply DB migrations
make data             # import USDA + TheMealDB, resolve ingredients, write report (~4 min)
```

## Layout

```
apps/api        FastAPI app
apps/web        Next.js app
packages/core   units, measure parsing, nutrition math (pure)
packages/db     SQLAlchemy models + Alembic migrations
packages/data   importers, ingredient normaliser, embeddings (CLI: larder-data)
docs/           DESIGN.md, ADRs, progress notes
```

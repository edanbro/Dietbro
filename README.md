# Larder (Dietbro)

AI meal planner: plans your week around what's already in your kitchen, then re-plans in real time
when you get a craving or eat off-plan. **LLM for language, constraint solver for guarantees.**

> Status: M2 — sign up, set up goals/allergies/preferences and a pantry on your phone. Build plan: [PLAN.md](PLAN.md). Design: [docs/DESIGN.md](docs/DESIGN.md).
> Progress: [docs/progress.md](docs/progress.md).

## Run it

Requires Docker and a free [Clerk](https://clerk.com) development instance (for sign-in).

1. In the Clerk dashboard, create an application and copy its **Publishable key** and
   **Secret key**.
2. `cp .env.example .env` and paste them into `CLERK_PUBLISHABLE_KEY` / `CLERK_SECRET_KEY`.
3. Start everything (migrations run automatically), then load foods and recipes:

```sh
docker compose up --build
make seed            # needs uv; ~1 minute
```

- Web: http://localhost:3000 (works on a phone on the same network via your machine's IP if you
  add it to `CORS_ORIGINS` and rebuild with that `NEXT_PUBLIC_API_URL`)
- API: http://localhost:8000 (docs at `/docs`, readiness at `/readyz`)

To run the end-to-end test in CI, add the same two keys as repository secrets
`CLERK_PUBLISHABLE_KEY` and `CLERK_SECRET_KEY`.

## Develop

Requires [uv](https://docs.astral.sh/uv/), Node 22 and pnpm (`corepack enable`).

```sh
make install          # Python + web deps, git hooks
docker compose up db redis -d && make seed
uv run uvicorn larder_api.main:app --reload    # API on :8000 (reads .env)
pnpm -C apps/web dev                           # web on :3000; put NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
                                               # and CLERK_SECRET_KEY in apps/web/.env.local
pnpm -C apps/web e2e                           # Playwright, needs CLERK_* keys exported
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

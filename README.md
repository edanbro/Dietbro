# Mealwright

> Formerly "Larder". The product name lives in `apps/web/src/lib/brand.ts` and
> `packages/core/src/larder_core/brand.py`; internal identifiers (`larder_*` packages, commands,
> Docker and database names) keep the old name so existing setups and data keep working.

AI meal planner: plans your week around what's already in your kitchen, then re-plans in real time
when you get a craving or eat off-plan. **LLM for language, constraint solver for guarantees.**

> Status: M6 — add groceries from a receipt: photograph it or paste the text, review what was
> read (offline OCR and matching, no API key), confirm into the pantry, and see what expires
> soon. Before that (M5): re-plan in real time from the plan screen or the chat (Claude for
> language, the planner and an independent validator for every change; works offline; replans
> p95 well under 1 s). The CP-SAT planner is being written (a greedy baseline stands in,
> checked by the same validator). Build plan: [PLAN.md](PLAN.md). Design: [docs/DESIGN.md](docs/DESIGN.md).
> Progress: [docs/progress.md](docs/progress.md).

## Run it

Requires Docker and a free [Clerk](https://clerk.com) development instance (for sign-in).

1. In the Clerk dashboard, create an application and copy its **Publishable key** and
   **Secret key**.
2. `cp .env.example .env` and paste them into `CLERK_PUBLISHABLE_KEY` / `CLERK_SECRET_KEY`.
   Optionally add `ANTHROPIC_API_KEY` for the AI chat; without it the chat still changes your
   plan from plain requests ("skip dinner tonight", "had pizza for lunch").
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
make data             # import USDA + TheMealDB + curated recipes, resolve, write report (~4 min)
make bench            # planner benchmark on the seeded catalog (PLANNER=auto|cpsat|greedy)
make llm-smoke        # four real chat turns against Claude (needs ANTHROPIC_API_KEY; ~5 cents)
uv run pytest packages/solver/tests/test_solve.py   # the spec the CP-SAT solve() must pass
```

## Layout

```
apps/api        FastAPI app
apps/web        Next.js app
packages/core   units, measure parsing, nutrition math, allergen/diet tags, prices (pure)
packages/db     SQLAlchemy models + Alembic migrations
packages/data   importers, ingredient normaliser, embeddings, curated recipes (CLI: larder-data)
packages/llm    Claude clients, typed plan changes and tools, agent loop, offline rule parser
packages/solver planning contract, validator, prefilter, greedy baseline, CP-SAT solve() (pure)
                — modelling guide: packages/solver/README.md
docs/           DESIGN.md, ADRs, progress notes
```

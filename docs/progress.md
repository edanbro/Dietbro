# Progress

One short demo note per milestone: what works, how to see it.

## M0 — Foundations

**What works**
- Monorepo: uv workspace (`apps/api`, `packages/core`) + pnpm workspace (`apps/web`).
- `docker compose up` → Postgres 17 + pgvector, Redis, FastAPI on :8000, Next.js on :3000.
- API: `GET /healthz` (liveness), `GET /readyz` (Postgres + Redis checks, 503 when degraded).
- Web: home page shows live API status, fetched server-side with a client typed from the API's
  OpenAPI schema.
- CI on every PR: Python (ruff, pyright strict, pytest), web (eslint, tsc, vitest, build),
  API contract drift check, pre-commit (incl. gitleaks), Docker build + compose smoke test.

**See it**
```sh
docker compose up --build
curl localhost:8000/readyz   # {"status":"ok","checks":{"database":"ok","redis":"ok"}}
open http://localhost:3000   # "API: ok"
```

**Docs**: [DESIGN.md](DESIGN.md) skeleton; ADRs [0001](adr/0001-record-architecture-decisions.md),
[0002](adr/0002-hybrid-llm-constraint-solver.md), [0003](adr/0003-monorepo-tooling.md).

**Next (M1)**: schema + Alembic, USDA importer, recipe seed, unit conversion, ingredient normaliser.

## M1 — Data

**What works**
- Schema + Alembic migrations (`packages/db`): foods, portions, recipes, ingredient lines, tags,
  pgvector embeddings, match cache. A test fails if models and migrations drift.
- `uv run larder-data pipeline` (or `make data`), ~4 min from an empty database:
  USDA Foundation + SR Legacy import (8,262 foods, 14.6k portion weights) → local embeddings →
  TheMealDB import (790 recipes, 8,152 ingredient lines) → resolve every line to food + grams →
  recipe embeddings → report.
- Units: measure parser + conversions in `packages/core`, with Hypothesis property tests.
- Recipe nutrition per serving; recipes with every line resolved are flagged plannable.

**Numbers** ([full report](data-report.md))

| | |
|---|---|
| Lines resolved to a USDA food | **99.6%** (target ≥ 95%) |
| …via the curated alias table / automatic matcher | 94.6% / 5.0% |
| Lines with grams | 98.4% |
| Plannable recipes (complete nutrition) | 667 / 790 |
| Matcher alone vs curated names: equivalent precision at threshold | 87% |

**See it**
```sh
docker compose up -d db
make data            # migrate + pipeline + report (fails below 95%)
```
CI: the `Data pipeline` workflow runs the same thing weekly and on PRs touching data code, and
posts the report to the job summary.

**Docs**: DESIGN §5–6; ADRs [0004](adr/0004-shared-schema-package.md),
[0005](adr/0005-local-embeddings.md), [0006](adr/0006-ingredient-matching.md).

**Known gaps**: canned vs dried pulses are not distinguished; servings are estimated from energy
(TheMealDB has none); 123 recipes still have an unresolved line. LLM tiebreak lands in M4.

**Next (M2)**: auth, user scoping, pantry/goals/preferences/allergies CRUD + mobile UI.

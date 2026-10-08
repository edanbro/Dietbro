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

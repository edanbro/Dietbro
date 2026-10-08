# Larder — Design

Living design doc. Update it in the same PR as the change it describes. Decisions between real
alternatives get an ADR in [`adr/`](adr/); this doc links to them rather than repeating them.

Status: **M0 (foundations)**. Sections marked _TBD (Mn)_ are filled in at that milestone.

## 1. Problem

People waste food and money because the plan for the week ignores what's already in the kitchen,
and any plan breaks the moment life happens ("had pizza for lunch"). Larder plans a week of meals
from the user's pantry, goals (kcal/macros, budget), preferences and allergies, then re-plans the
rest of the week in real time when they report cravings or off-plan meals — changing as little as
possible and explaining why.

## 2. Core idea: LLM for language, solver for guarantees

See [ADR-0002](adr/0002-hybrid-llm-constraint-solver.md).

- The LLM never emits the plan. It parses intent, ranks or drafts recipes, and explains changes.
- A CP-SAT model builds the plan, so allergies, nutrition bands and pantry limits hold by
  construction.
- A validator, independent of the solver, checks every plan. Evals score hybrid vs an LLM-only
  baseline with that same validator.

## 3. Architecture

```
 phone / browser
       │
  apps/web  (Next.js, server components call the API)
       │  HTTP (types generated from OpenAPI)
  apps/api  (FastAPI) ──── Postgres + pgvector
       │            └───── Redis (cache, arq queue)
       │
  packages/core    domain models, units, nutrition math (pure)
  packages/solver  CP-SAT model + validator (pure)          — M3
  packages/llm     Claude client, tools, schemas            — M4
  packages/data    USDA + recipe importers, normaliser      — M1
  apps/worker      arq jobs (receipts, plan gen, embeddings) — when first needed
```

Rules:
- `packages/*` do no network or DB I/O except `data` importers; `solver` and `core` stay pure so
  they're trivially testable and reusable by evals.
- The web app only talks to the API. Its client types are generated from the API's OpenAPI
  schema; CI fails if the committed schema or types drift from the code.

## 4. Runtime and local dev (M0)

- `docker compose up` runs `db` (Postgres 17 + pgvector), `redis`, `api` (:8000), `web` (:3000).
- `GET /healthz` = liveness. `GET /readyz` = Postgres `SELECT 1` + Redis `PING`, 503 if any fail.
  Compose waits on health checks, so `web` starts only after `api` is healthy.
- Tooling: uv workspace (Python 3.12) + pnpm workspace (Node 22). See
  [ADR-0003](adr/0003-monorepo-tooling.md).
- Quality gates (CI + pre-commit): ruff, pyright strict, pytest; eslint, tsc, vitest, next build;
  OpenAPI/type drift check; gitleaks; Docker build + compose smoke test.

## 5. Data model

_TBD (M1)._ Initial table list in PLAN.md §5. All quantities in grams / ml. Plans are versioned:
every replan writes a new version.

## 6. Units and ingredient normalisation

_TBD (M1)._ Rule-based parse → pgvector nearest neighbours → Haiku tiebreak only when ambiguous.

## 7. Solver

_TBD (M3)._ Pure `solve(problem, previous, time_limit_ms) -> PlanResult`. Variables, hard
constraints, weighted objective, replan via churn penalty + hints: PLAN.md §6.

## 8. LLM layer

_TBD (M4)._ Agent loop with tools, Pydantic-validated outputs, deterministic fallback, cost logging.

## 9. Safety and privacy

- Allergies are hard constraints, shown prominently. Calorie floor and max daily deficit are
  enforced; extreme targets are refused. "Not medical advice" note.
- User content (receipts, recipe text, chat) is data, never instructions. Tools are user-scoped.
- No secrets in the repo: `.env.example` only; gitleaks in pre-commit and CI.
- GDPR basics (export, deletion): _TBD (M2)._

## 10. Observability and performance

_TBD (M8)._ OTel traces, Prometheus metrics, JSON logs, LLM token/cost per request; k6 numbers.

## 11. Open questions

- Recipe dataset license (RecipeNLG is non-commercial) — decide before M1 import.
- Auth provider: Clerk vs Auth0 — decide at M2 (ADR).

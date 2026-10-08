# Larder — Design

Living design doc. Update it in the same PR as the change it describes. Decisions between real
alternatives get an ADR in [`adr/`](adr/); this doc links to them rather than repeating them.

Status: **M1 (data)**. Sections marked _TBD (Mn)_ are filled in at that milestone.

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
  packages/core    units, measure parsing, nutrition math (pure)
  packages/db      SQLAlchemy models + Alembic migrations
  packages/data    USDA + recipe importers, normaliser, embeddings (CLI: larder-data)
  packages/solver  CP-SAT model + validator (pure)          — M3
  packages/llm     Claude client, tools, schemas            — M4
  apps/worker      arq jobs (receipts, plan gen, embeddings) — when first needed
```

Rules:
- `core` and `solver` stay pure (no network or DB I/O) so they're trivially testable and reusable
  by evals. `db` owns the schema; `data` is the only package that downloads anything.
- One async stack: SQLAlchemy 2.0 async + asyncpg everywhere, schema changes only via Alembic
  ([ADR-0004](adr/0004-shared-schema-package.md)).
- The web app only talks to the API. Its client types are generated from the API's OpenAPI
  schema; CI fails if the committed schema or types drift from the code.

## 4. Runtime and local dev

- `docker compose up` runs `db` (Postgres 17 + pgvector), `redis`, `api` (:8000), `web` (:3000).
- `GET /healthz` = liveness. `GET /readyz` = Postgres `SELECT 1` + Redis `PING`, 503 if any fail.
  Compose waits on health checks, so `web` starts only after `api` is healthy.
- Tooling: uv workspace (Python 3.12) + pnpm workspace (Node 22). See
  [ADR-0003](adr/0003-monorepo-tooling.md).
- Quality gates (CI + pre-commit): ruff, pyright strict, pytest (with a Postgres service);
  eslint, tsc, vitest, next build; OpenAPI/type drift check; gitleaks; Docker build + compose
  smoke test. The data pipeline runs as its own workflow (weekly + PRs touching data code).
- Migrations: `make migrate` (Alembic, `packages/db`). DB tests use `$TEST_DATABASE_URL` and
  skip when Postgres is unreachable (CI sets `LARDER_REQUIRE_DB=1` so they can't skip there).

## 5. Data model

Tables exist for what M1 uses; users, pantry, plans and LLM-call tables arrive with M2–M4.

| Table | Holds |
|---|---|
| `foods` | USDA FoodData Central foods (Foundation + SR Legacy, 8.3k). PK = FDC id. Eight macro columns per 100 g (kcal, protein, fat, carbs, fiber, sugars, sat fat, sodium) |
| `food_portions` | "`amount` `unit` weighs `grams`" per food: `1 clove = 3 g`, `1 cup chopped = 160 g`, `1 large = 150 g` |
| `food_embeddings` | 384-d vector per food (bge-small, HNSW cosine index) |
| `recipes` | Imported recipes; per-serving macros, `servings`, `nutrition_complete` |
| `recipe_ingredients` | Each line verbatim (`raw_name`, `raw_measure`) + resolution (`food_id`, `grams`, `match_method`, `match_score`); unresolved lines keep nulls |
| `recipe_tags`, `recipe_embeddings` | Tags; recipe vectors for candidate search (M3) and craving similarity (M4) |
| `ingredient_matches` | Cache: normalised name → food (or "tried, no confident match") |

Conventions: quantities are grams (liquids too: ml × density); food nutrients per 100 g, recipe
nutrients per serving. Only recipes with `nutrition_complete` (every line has a food and grams)
are plannable. Plans will be versioned: every replan writes a new version.

## 6. Units and ingredient normalisation

Data flow (`uv run larder-data pipeline`, ~4 min; `make data`):

```
USDA CSV zips ──► foods + portions ──► food embeddings (fastembed, local)
TheMealDB API ──► recipes + raw lines
raw line ──► measure parser ─────────────────────────────┐
         └─► name normaliser ─► alias table ─► hybrid retrieval ─► rerank ─► threshold
                                    │ hit                                    │ pass / fail
                                    ▼                                        ▼
                                 food_id ◄──────────────────────── food_id / unresolved
food_id + measure + portions ──► grams ──► recipe nutrition per serving
```

**Measures** (`larder_core.units`): fractions, unicode fractions, ranges (midpoint), containers
(`2 x 400g tins` → 800 g), `juice of 1`, size words, and vague phrases with fixed equivalents
(pinch = 1/16 tsp, to taste = 1/4 tsp, knob = 15 g, handful = 30 g). Conventions: metric spoons
(5/15 ml), 240 ml cup, imperial pint (seed recipes are mostly British). Hypothesis property tests
cover conversion round-trips, linearity, monotonicity and "never raises on any input".

**Grams** (`larder_data.quantities`): mass converts directly; volume × the food's density (median
g/ml over its USDA volume portions, else a per-category default, else 1.0); counts use the
matching USDA portion (`clove`, `large`, else medium, else an unsized "each"), then small tables
for containers (400 g tin) and pieces USDA weighs only by volume (bay leaf 0.2 g). If nothing
applies the line stays unresolved — never silently zero.

**Names → foods** (`larder_data.text`, `larder_data.matching`,
[ADR-0006](adr/0006-ingredient-matching.md)):
1. Normalise: lowercase, strip accents and prep/size words, singularise ("Freshly Chopped
   Parsley" → "parsley").
2. Curated alias table (`resources/aliases.csv`, 567 hand-reviewed names). Some rows are marked
   `approximation` (nearest nutritional stand-in, e.g. garam masala → curry powder).
3. Otherwise rewrite British → USDA vocabulary (aubergine → eggplant), then retrieve candidates
   two ways — pgvector nearest neighbours and a lexical "all words present" match — and rerank:
   embedding similarity + word coverage + head-noun bonus − penalties for processing states
   (dried, canned) and derived products (flour, oil, juice) the name didn't ask for, branded
   items, and foods missing macros.
4. Accept if the score ≥ 0.88, else unresolved. An LLM (Haiku) tiebreak plugs in here in M4.

**Servings**: TheMealDB gives none, so `servings = round(total kcal / typical portion)`, with the
portion by category (dessert 350, side 250, starter 300, breakfast 450, otherwise 650 kcal),
clamped 1–12 and flagged `servings_estimated`.

**Results** (full snapshot: [data-report.md](data-report.md); regenerated weekly by the
`Data pipeline` workflow, which fails below 95%):

| Metric | Value |
|---|---|
| Ingredient lines resolved to a USDA food | 99.6% (target ≥ 95%) — 94.6% alias, 5.0% matcher |
| Lines with a gram weight | 98.4% |
| Recipes with complete nutrition (plannable) | 667 / 790 (84%) |
| Matcher alone, scored against the curated names | 54% exact top-1; 74% exact-or-equivalent (same USDA category, energy within 25%); 87% equivalent precision at the 0.88 threshold |

Caveat: the curated table carries most of the coverage. The matcher matters for ingredients not
yet seen (user-entered, LLM-generated recipes); improving it (and the M4 LLM tiebreak) is
measured with `larder-data report --evaluate`.

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

- TheMealDB's free key is for development; a public deployment (M8) needs a supporter key or a
  different source ([ADR-0006](adr/0006-ingredient-matching.md)).
- Canned vs dried pulses: names alone don't say which; the alias table picks dried. Measures
  mentioning tins could switch the food (M3 if plans look off).
- Auth provider: Clerk vs Auth0 — decide at M2 (ADR).

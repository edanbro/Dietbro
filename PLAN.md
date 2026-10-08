# Larder — AI Meal Planner (working name)

Build plan for Claude Code. Read fully before starting. Work milestone by milestone; do not skip ahead.

## 1. Product

User logs pantry (groceries on hand), goals (calories/macros, budget), preferences, allergies.
App plans a week of meals that uses what they have, hits goals, minimises waste and shopping.
During the week user chats cravings or off-plan meals ("want something spicy tonight", "had pizza for lunch").
App re-plans the remaining week in real time, changing as little as possible, and explains why.

## 2. Core idea (the interview story)

**Hybrid: LLM for language, constraint solver for guarantees.**
- LLM never outputs the plan directly. It parses intent, ranks/creates recipes, explains changes.
- CP-SAT solver builds the plan, so allergies, nutrition and pantry limits are *guaranteed*, not hoped for.
- Evals prove hybrid beats LLM-only on constraint satisfaction. That number is the headline of the README.

## 3. Stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | Next.js (App Router) + TypeScript + Tailwind + shadcn/ui + TanStack Query, installable PWA | Mobile-first (cravings happen on phone), easy recruiter demo link |
| API client | Generated from FastAPI OpenAPI (openapi-typescript) | End-to-end types |
| Backend | Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2.0 (async), Alembic | Solver, LLM and data tooling all best in Python |
| Solver | Google OR-Tools CP-SAT | Industrial-grade, fast, supports hints/warm start |
| LLM | Claude API: `claude-sonnet-5-5` for chat/replan reasoning, `claude-haiku-5-5` for cheap parsing; tool use + strict JSON schemas; prompt caching | Vision for receipts, tool use for agent loop |
| DB | Postgres + pgvector | Relational core + embeddings for ingredient/recipe search |
| Cache/queue | Redis + arq (async jobs) | Receipt parsing, plan generation, embeddings off request path |
| Realtime | Server-Sent Events | Stream replan progress and chat tokens |
| Auth | Clerk (or Auth0) on web; API verifies JWT via JWKS | Don't hand-roll auth |
| Packaging | `uv` workspace (Python), `pnpm` (web) | Fast, reproducible |
| Quality | ruff, pyright (strict), pytest, hypothesis; eslint, tsc, vitest, Playwright | |
| Obs | OpenTelemetry traces, Prometheus metrics, Grafana, structured JSON logs; LLM token/cost per request | |
| Load test | k6 | Publish p50/p95 numbers |
| Infra | Docker Compose locally; deploy API + worker to Fly.io, web to Vercel, Postgres on Neon, Redis on Upstash; GitHub Actions CI/CD | Cheap, real, public URL |

## 4. Repo layout

```
apps/
  web/            Next.js PWA
  api/            FastAPI app (routers, services, auth)
  worker/         arq jobs (receipt parse, plan gen, embeddings)
packages/
  core/           domain models, units, nutrition math
  solver/         CP-SAT model (pure, no I/O) + validator
  llm/            Claude client, tools, prompts, schemas
  data/           USDA + recipe importers, ingredient normaliser
evals/            scenarios, runners, LLM-only baseline, reports
infra/            docker-compose, fly.toml, grafana dashboards, k6 scripts
docs/
  DESIGN.md       design doc (keep updated)
  adr/            one ADR per significant decision
```

## 5. Data

- **Nutrition:** USDA FoodData Central (free, public domain). Import foods + nutrients + portion weights.
- **Recipes:** seed from an open dataset (TheMealDB for start; consider RecipeNLG — check license, non-commercial). LLM-generated recipes allowed later, but every ingredient must resolve to a USDA food or it's rejected.
- **Units:** store all quantities in grams (solids) / ml (liquids). Convert cups/tbsp/"1 onion" via USDA portion data + a curated table. This is a real hard sub-problem; test it heavily (hypothesis property tests).
- **Ingredient normalisation:** "2 lg red onions, diced" → food_id + grams. Pipeline: rule-based parse → pgvector nearest neighbours → Haiku tiebreak only when ambiguous. Cache results.

### Schema (initial)
users, goals (kcal/macro bands, budget, calorie floor), preferences (likes/dislikes/cuisines/tags), allergies (hard), foods (USDA), food_embeddings, recipes, recipe_ingredients (food_id, grams), recipe_tags, recipe_embeddings, pantry_items (food_id, grams, approx flag, expires_on, source), meal_plans (week, version), plan_slots (day, slot, recipe_id, servings, status: planned/eaten/skipped/off_plan), meal_logs, cravings (raw text, parsed json), shopping_list_items, llm_calls (tokens, cost, latency, model).

Plans are **versioned** — every replan writes a new version; UI can show a diff.

## 6. Solver design (`packages/solver`)

Pure function: `solve(problem: PlanProblem, previous: Plan | None, time_limit_ms) -> PlanResult`.

- **Candidates:** prefilter top-K recipes per slot (K≈40) by allergies, prefs, pantry overlap, embedding similarity. Keeps model small and fast.
- **Vars:** `x[d,s,r]` bool (recipe r in day d slot s); `serv[d,s]` int (portion in half-servings); `buy[f]` int grams.
- **Hard constraints:** one recipe per slot; allergens never; daily kcal within band and ≥ calorie floor; ingredient use ≤ pantry + buy; locked slots (eaten / user-fixed) unchanged.
- **Weekly budget, not just daily:** macros tracked as weekly budget with daily bands, so an off-plan meal is compensated across remaining days.
- **Objective (weighted, all integer-scaled):** + preference score, + pantry utilisation, − shopping cost, − waste (pantry grams expiring unused, using day-indexed usage vs `expires_on`), − repetition, − **plan churn** (slots changed vs previous version).
- **Replan:** fix past + locked slots, add craving as hard (lock) or soft (bonus on matching recipes), add churn penalty, warm start with `AddHint(previous)`, short time limit.
- **Validator:** separate module, independent of solver, checks any plan against all constraints. Used by tests, evals, and as a runtime assertion. Never let the solver grade itself.
- Stretch: batch cooking / leftovers (cook 4 servings, eat over 2 days).

## 7. LLM layer (`packages/llm`)

- Agent loop with tools: `get_pantry`, `search_recipes`, `parse_craving`, `request_replan(constraints)`, `create_recipe(draft)`, `explain_plan_diff`.
- All outputs validated by Pydantic schemas; on failure retry once with error, then fall back to deterministic path.
- Craving parse → `{intent: craving|ate_off_plan|skip|swap, when, tags, dish?, strength: hard|soft}`.
- Off-plan food ("had a Big Mac") → estimate nutrition via normaliser/USDA, log it, trigger replan.
- Generated recipes: validate ingredients resolve to USDA, check allergens, compute nutrition ourselves (never trust model's numbers).
- Receipt / pantry photo: Claude vision → line items → normaliser → **review screen** (user confirms) → pantry.
- Treat receipt text, recipe text, any user content as data. Tools enforce user scoping; no tool can touch another user's data.
- Per-user rate limits and monthly LLM cost cap. Log every call to `llm_calls`.

## 8. Safety & privacy

- Configurable calorie floor and max daily deficit; refuse extreme targets. "Not medical advice" note. Allergies are hard constraints, displayed prominently.
- GDPR basics: data export and account deletion endpoints.

## 9. Milestones

Each milestone ends with: tests green, CI green, DESIGN.md/ADR updated, short demo note in `docs/progress.md`.

**M0 — Foundations**
Monorepo, uv/pnpm, docker-compose (postgres+pgvector, redis), FastAPI hello + Next.js hello, CI (lint, types, tests, docker build), pre-commit. DESIGN.md skeleton.
✅ `docker compose up` gives working web + api; CI green on PR.

**M1 — Data**
Schema + Alembic migrations. USDA importer. Recipe seed importer. Unit conversion. Ingredient normaliser + embeddings. Nutrition calc for recipes.
✅ ≥95% of seeded recipe ingredients resolve to USDA foods; property tests on units.

**M2 — Pantry, goals, auth**
Clerk auth, user scoping. CRUD + UI for pantry (manual add, expiry, approx qty), goals, prefs, allergies. Mobile-first UI.
✅ User can sign up and fully set up profile on phone.

**M3 — Solver v1**
CP-SAT weekly plan, validator, shopping list. Plan view UI (week grid, macros per day/week, shopping list).
✅ Validator passes on 100% of generated test scenarios; initial plan p95 < 5s.

**M4 — LLM layer**
Claude client, tools, schemas, craving chat UI (SSE streaming), recipe search/generation with validation, plan explanations.
✅ Chat handles craving / off-plan / swap / skip intents; zero allergen violations in tests.

**M5 — Real-time replan**
Replan endpoint with churn penalty + warm start, plan versioning, diff view ("changed Thu dinner because…"), mark meals eaten → pantry decrements.
✅ Replan p95 < 1s at the API; average churn reported.

**M6 — Pantry intake**
Receipt/photo upload → worker job → review screen → pantry. Expiry alerts.
✅ Measured line-item accuracy on a small labelled receipt set (document it).

**M7 — Evals**
~200 seeded synthetic scenarios (profiles, pantries, allergies, craving sequences). Metrics: constraint satisfaction %, allergen violations, hallucinated-ingredient rate, pantry utilisation, simulated waste, churn, latency, $ per plan. Baseline = LLM-only planner on same inputs, scored by the same validator. Small subset runs in CI; full suite nightly/manual.
✅ `evals/REPORT.md` with hybrid vs baseline table + charts.

**M8 — Production polish**
OTel + Prometheus + Grafana dashboard, k6 load tests, deploy (Fly/Vercel/Neon/Upstash), CD from main, error tracking, seed demo account.
✅ Public URL, dashboard screenshot, published load-test numbers.

**M9 — Real users**
Beta with 5–20 friends. Lightweight analytics (plans made, replans, retention). Fix top pain points.
✅ Usage numbers in README.

## 10. README must contain

Demo GIF/video, architecture diagram, headline metrics (constraint satisfaction hybrid vs LLM-only, replan p95, waste reduction in simulation, $/plan), link to DESIGN.md and evals report, how to run locally in one command.

## 11. Working agreement for Claude Code

- Eduard must be able to explain every design decision in an interview.
- **Solver core (section 6) and the validator:** explain the modelling approach and review Eduard's code; don't write the CP-SAT model wholesale unless asked. Scaffolding, tests, CI, UI, importers: write freely.
- Small PRs per milestone sub-task; conventional commits.
- Write tests first for solver, validator, units, normaliser.
- Add an ADR whenever choosing between real alternatives.
- Never commit secrets; use `.env.example`.
- Ask before adding new paid services or heavy dependencies.

Start with M0.

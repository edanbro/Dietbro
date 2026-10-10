# ADR-0009: An integer planning contract, an independent validator, soft macros

- Status: Accepted
- Date: 2026-10-09

## Context

M3 adds the weekly planner (PLAN §6). Several parties touch a plan: the API builds the problem,
the CP-SAT model (Eduard's) solves it, a baseline planner stands in until then, an independent
validator checks every plan, and the evals (M7) score plans from any planner, including an
LLM-only one. They need one definition of "a valid plan" and "a better plan". A design review
(prototype CP-SAT model on the real catalogue) also measured three things that shaped the
decisions below:

- With 40 candidates × 4 slots × 7 days, CP-SAT finds a first plan in 0.4–1 s (≥ 2 workers) but
  practically never proves optimality: it runs to the time limit with a 0.5–4% gap.
- With protein/fat/carbs as hard bands, realistic vegetarian, vegan and budget profiles often
  ended UNKNOWN (no plan within the limit, no proof of infeasibility).
- About a quarter of recipe ingredient lines are under 1 g per portion (a pinch of saffron).
  Rounding them up to 1 g inflated cost up to 200× for expensive spices.

Options for the contract: floats with tolerances in each consumer, or integers fixed once.
For macros: hard bands, or soft bands with a penalty.

## Decision

- **Integers everywhere** (`larder_solver.problem`). Meal size is in *portions* (half
  servings). Nutrition is per portion and rounded once when the problem is built. Ingredient
  grams per portion are rounded up, except store-cupboard staples (water, salt, pepper, dried
  spices, raising agents) and sub-gram lines, which are 0 g: tagged for allergens, never costed
  or bought. Money is in minor units and prices are per kg, so `grams × price_per_kg` is exact
  ("millipence"). The solver and the validator do the same arithmetic, so a plan can't pass one
  and fail the other by rounding.
- **Hard rules**: one meal per required slot, eligibility, per-slot portion ranges, allergens,
  diet, avoided foods, locks, per-slot repeat caps, daily kcal band, calorie floor, budget.
  **Soft**: protein, fat and carbs bands, penalised per gram outside the band. A plan then
  exists whenever the hard rules allow one, and CP-SAT finds a first solution easily.
- **One objective** (`Weights`, `metrics.score`), every term priced in millipence ("what would
  the user pay to get or avoid this?"): preference, pantry use, shopping cost, waste of
  expiring pantry food, repeats, snacks, macro misses, churn (replans). The shopping list and
  waste come from a deterministic earliest-deadline-first allocation, which is optimal for a
  fixed plan. A solver's reported objective must satisfy `objective ≤ score(plan) ≤ bound`,
  with equality at OPTIMAL. That is an exact cross-check of the model.
- **Independent validator** (`larder_solver.validate`). It re-implements the hard filters rather
  than sharing the prefilter's code (a test checks they agree). It is used by tests, evals and
  the API as a runtime assertion. Plans with a safety violation (allergen, diet, avoided food,
  unverifiable ingredients, calorie floor) or a structural one are never saved, whatever the
  planner. A CP-SAT plan with any hard violation is a bug (500). The baseline's misses on the
  kcal band or budget are saved and shown.
- **Planner selection**: `PLANNER=auto` uses `solve()` and falls back to the greedy baseline when
  it isn't implemented yet or finds no plan in time (UNKNOWN). The baseline enumerates each day's
  meal combinations, treats the floor as hard and is never trusted: the same validator gates it.
- **Synchronous planning** in the API, in a worker thread behind a process-wide limiter, with a
  3.5 s solver budget, leaving ~1.5 s of the 5 s p95 target for inputs, prefilter, validation
  and saving. `make bench` measures p95 end to end. A job queue (arq) waits until load tests
  (M8) show it's needed.
- **Snapshots**: a saved plan stores per-meal macros and a typed stats blob (targets, cost,
  waste, score terms, violations, exclusions). Old plans never drift when recipes, goals or
  prices change.

## Consequences

- Eduard implements `solve()` against a fixed contract and a failing spec
  (`packages/solver/tests/test_solve.py`). The M3 criterion "validator passes on 100%" means no
  hard violations on generated scenarios.
- Macro targets are goals, not guarantees. The plan view shows misses as information. If users
  need a hard protein floor, it becomes a per-user flag.
- Rounding rules are part of the contract: changing them changes plans and needs a migration
  note.
- Open for M5: `locked` mixes eaten meals (facts) and pinned future meals (choices). Today both
  still pass the allergen/diet filters. M5 adds an explicit "eaten" marker that skips them.

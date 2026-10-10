# larder-solver

Weekly meal planning, pure Python with no I/O: the planning contract, the CP-SAT planner
(`solve`, to be written), a greedy baseline, an independent validator, plan metrics, the
shopping list and an infeasibility diagnosis. The rationale is in
[ADR-0009](../../docs/adr/0009-planning-contract.md) and [DESIGN §8](../../docs/DESIGN.md#8-planning).

| Module | What it is |
| --- | --- |
| `problem.py` | The contract: `Problem`, `Plan`, `Meal`, `PlanResult`, `Status`, `Weights`, `check_problem` |
| `metrics.py` | Day/week totals, EDF pantry allocation, cost, waste, `score` (the objective) |
| `validate.py` | `validate(problem, plan)`: every rule a plan breaks, one `Code` per rule |
| `candidates.py` | The prefilter: `allowed` (hard filters) and `select` (top k per slot) |
| `shopping.py` | `shopping_list(problem, plan)` |
| `baseline.py` | `greedy(problem, previous, time_limit_ms)`: day-by-day baseline planner |
| `diagnose.py` | `diagnose(problem)`: why no plan exists, in the user's words |
| `scenarios.py` | Seeded test problems: `planted`, `infeasible`, `realistic`, `synthetic_catalog` |
| `solve.py` | `solve(problem, previous, time_limit_ms, *, workers)`: **the CP-SAT model** |

The rest of this file is the modelling guide for `solve()`. It explains the choices and the
traps; it deliberately doesn't contain the model. The specification is
[`tests/test_solve.py`](tests/test_solve.py): every test xfails today and must pass once
`solve()` exists.

## 1. The contract in one page

`solve(problem, previous=None, time_limit_ms=3500, *, workers=8) -> PlanResult`

- **Input**: a `Problem` (days, slot specs with candidate recipe ids, recipes, foods, targets,
  profile, pantry lots, budget, locks, off-plan intake, weights). It is already prefiltered
  (`candidates.select`, about 40 candidates per slot), but **don't trust the candidates**: a
  candidate can still break a hard filter (the planted scenarios add such decoys on purpose).
- **Output**: `PlanResult(status, plan, planner="cpsat", wall_ms, objective, bound, notes)`.
  A plan exactly when the status is OPTIMAL or FEASIBLE. `wall_ms` from entry to return.
- **Validity**: `hard(validate(problem, plan)) == []` for every plan returned. The API
  asserts it at runtime; a violation from CP-SAT is a 500, i.e. a bug in the model.
- **Optimality**: maximise `metrics.score(problem, plan, previous).total`, and report
  `objective <= score <= bound`, with `objective == score` at OPTIMAL (section 6).

### Integer conventions

Everything is an integer, fixed once when the problem is built, so the model and the
validator do exactly the same arithmetic:

- **Portions** are half servings. A meal is 1, 2, 3 or 4 portions; each slot has its own range,
  `problem.portion_range(slot)` (planted and API problems: breakfast 1-3, lunch 1-4, dinner
  2-4, snack 1-2).
- **Nutrition** is per portion (`recipe.per_portion`: kcal and grams of protein, fat, carbs):
  a meal's macros are `per_portion × portions`, linear in the portion count.
- **Ingredient grams** are per portion. `grams == 0` marks a store-cupboard staple: tagged
  for allergens and diet, never used, bought or costed.
- **Money**: prices are minor units (pence) per kg, so `grams × price_per_kg` is the cost in
  *millipence* (1/1000 p), exactly. The budget is in minor units: compare `cost_millipence <=
  budget × 1000`.
- **Weights** (`problem.weights`) are in millipence-equivalents, so every objective term is an
  integer in one unit.
- **Days** are indices `0..days-1` from `problem.start`; lot expiry is a day index too
  (inclusive; `None` = keeps; `< 0` = ignore the lot).

## 2. Decision variables

Only create variables for `d in range(days)`, `s` in `problem.slots`, unlocked cells, and
recipes that are candidates of `s`, eligible (`s in recipe.meal_types`) and allowed
(`candidates.allowed(recipe, problem.foods, problem.profile)`). Everything else is a constant.

Two reasonable encodings; try both on the perf test:

- **A. choice + portions**: `x[d,s,r]` boolean and `q[d,s,r]` integer in `{0} ∪ [lo, hi]`,
  linked so that `q = 0` when `x = 0` and `lo ≤ q ≤ hi` when `x = 1`:

  ```python
  q = model.new_int_var(0, hi, f"q_{d}_{s}_{r}")
  model.add(q >= lo * x)
  model.add(q <= hi * x)
  ```

- **B. one boolean per portion count**: `y[d,s,r,p]` for `p in [lo, hi]`; the meal is
  `Σ_p y` and its portions `Σ_p p·y`. More booleans (≈ 7 × 4 × 40 × 3 ≈ 3,400), but an exact
  linear relaxation, which CP-SAT's LP usually likes.

Per cell: `add_exactly_one` (required slot) or `add_at_most_one` (optional slot) over the
cell's choice booleans.

Everything else (day kcal, macros, food usage, cost) is then a *linear expression* in `q` (or
`p·y`): `Σ per_portion.kcal × q`. No multiplications between variables are needed anywhere.

## 3. Constraints, one per validator code

`validate.Code` lists every rule. Each must be enforced by construction or by a constraint:

| Code | Enforced by |
| --- | --- |
| `day_range` | Variables only for days `0..days-1` |
| `unknown_slot` | Variables only for slots in `problem.slots` |
| `duplicate` | At most one choice per (day, slot) |
| `missing` | Exactly one choice per unlocked (day, required slot) |
| `unknown_recipe` | Variables only for ids in `problem.recipes` |
| `not_eligible` | Variables only for recipes with the slot in `meal_types` |
| `portions` | Portion domain `problem.portion_range(slot)` |
| `allergen`, `unverified`, `avoided`, `diet`, `unknown_food` | Variables only for `candidates.allowed` recipes; a **locked** meal that isn't allowed makes the problem INFEASIBLE (check before building) |
| `locked` | Locked cells get no variables: a locked `Meal` is a constant that the returned plan must contain exactly (recipe and portions as given, even outside the slot's range or eligibility); a lock to `None` is an empty cell, even in a required slot |
| `repeats` | Per recipe: `Σ unlocked uses ≤ max(0, problem.repeat_cap(recipe) − locked uses)` (the validator counts locked meals, and only flags a recipe with an unlocked use) |
| `calorie_floor` | Per day: `kcal_d ≥ targets.calorie_floor` |
| `daily_band` (kcal) | Per day: `kcal_d` inside `targets.daily[KCAL]` |
| `weekly_band` (kcal) | `Σ_d kcal_d` inside `targets.weekly[KCAL]` |
| `budget` | `Σ_f price_f × bought_f ≤ budget × 1000` |
| `daily_band`, `weekly_band` (protein, fat, carbs) | Soft: objective term `macro` (section 4) |

`kcal_d` is `extra[d].kcal + Σ locked meals that day + Σ per_portion.kcal × q[d,·,·]`.
`problem.extra` (food eaten off-plan) counts toward every daily and weekly total, never
toward slots: a logged lunch is also locked to `None`.

`problem.repeat_cap(recipe)` is the tightest cap among the planned slots the recipe fits (a
pot that is both a breakfast and a snack takes the smaller), else `problem.max_repeats`. One
cap per recipe, across all slots. There is **no** "a recipe at most once a day" rule (lunch and
dinner may share leftovers); don't add one.

## 4. The objective, term by term

Maximise exactly `metrics.score` (read it; it's 30 lines). With `w = problem.weights`:

| Term | In the model |
| --- | --- |
| `preference` | `w.preference × Σ recipe.preference × choice` (+ locked meals: constant) |
| `pantry` | `w.pantry × grams drawn from lots` (section 5) |
| `cost` | `−w.cost × Σ price × grams bought` (section 5) |
| `waste` | `−w.waste × price × grams left` in lots with `0 ≤ expires < days` (section 5) |
| `repeat` | `−w.repeat × Σ_r rep_r` with `rep_r ≥ uses_r − 1`, `rep_r ≥ 0` (uses include locked meals) |
| `optional` | `−w.optional_meal ×` meals in slots that aren't required (locked ones included) |
| `macro` | `−w.macro ×` grams outside each protein/fat/carbs band: every day's daily bands plus the weekly bands |
| `churn` | `−w.churn × changed_slots(previous, plan)` (below) |

**Soft macro bands.** For a band `[lo, hi]` on a linear total `t`: `short ≥ lo − t`,
`excess ≥ t − hi`, both `≥ 0`, penalise `short + excess`. `Band.distance` is exactly this at
the optimum. Skip a side that is `None`.

**Auxiliaries must be tight at the optimum.** `rep_r`, `short`, `excess` and the pantry
variables are only bounded on one side; the objective pushes them to their true value. That
is what makes the objective equal the score at OPTIMAL, and why a FEASIBLE solution may report
`objective < score` (a slack auxiliary): the contract allows it.

**Constants belong in the objective.** Locked meals' preference, repeats among locked meals,
locked snacks, the macro contribution of `extra`, locked meals' ingredient use, churn on
locked cells, and previous meals outside this problem's cells all count in `score`. Add them
as a constant offset: CP-SAT keeps it (`model.maximize(expr + constant)`; `objective_value`
and `best_objective_bound` include it).

**Churn** (`metrics.changed_slots`) compares (day, slot) cells by recipe, ignoring portions;
a cell counts if the recipe differs or one side has no meal. For each cell with a previous
recipe `r0`: `1 − x[d,s,r0]` (just `1` if `r0` has no variable there). For each cell without
one: the cell's "has a meal" sum. Previous meals at cells that aren't open (other days,
locked cells) are constants. Only the first previous meal per cell counts, like `Plan.at`.

## 5. Pantry, shopping and cost

`metrics.allocate` turns a plan into what is drawn from the pantry, bought and wasted: per
food, days in order, from the usable lots soonest-expiry first (earliest-deadline-first, EDF).
For a fixed plan EDF uses the most pantry, buys the least and wastes the least, so the model
may choose *any* allocation: at the optimum it is worth exactly as much as EDF's.

- **Foods not in the pantry** need no variables: their cost is linear in the portions.
  Precompute per recipe `cost_per_portion = Σ grams × price_per_kg` over its non-pantry foods
  and add `−w.cost × cost_per_portion × q`.
- **Pantry foods**: one variable per (lot, day) where the lot is usable (`expires is None or
  0 ≤ d ≤ expires`, lots with `expires < 0` ignored), grams drawn that day, `Σ_d ≤ lot.grams`.
  Per (food, day): drawn + bought = usage, where usage is `Σ grams × q` over the day's meals
  (locked ones as constants) and bought ≥ 0. A food's grams are only usage when
  `ingredient.grams > 0` and the food is in `problem.foods`.
- **Waste**: only lots with `0 ≤ expires < days`; `waste = lot.grams − Σ drawn` (constant minus
  variables).
- The **budget** constraint uses bought grams. A FEASIBLE solution that buys more than EDF
  would is still safe: EDF's cost is lower, so the validator's budget check passes too.

## 6. objective, bound, status

- `objective = round(solver.objective_value)`, `bound = round(solver.best_objective_bound)`.
  Both are doubles; they are exact while magnitudes stay below 2^53 (they do: a week's
  shopping is around 10^7 millipence). Assert it rather than assume it.
- The tests check `objective ≤ score(problem, plan, previous).total ≤ bound` on every call, and
  `objective == score` at OPTIMAL. This is an exact cross-check of the model: if it fails,
  compare `score(...).terms` with your own per-term values on the solution.
- Status mapping: `OPTIMAL → Status.OPTIMAL`, `FEASIBLE → FEASIBLE`, `INFEASIBLE →
  INFEASIBLE`, `UNKNOWN → UNKNOWN`, `MODEL_INVALID → INVALID`. Infeasibility you can see
  before building (an unsafe lock, a required slot with no allowed candidate) → INFEASIBLE
  without solving. `diagnose(problem)` explains INFEASIBLE to the user; the API calls it.
- **Don't expect OPTIMAL at full size within 3.5 s.** Report the gap in `notes`, e.g.
  `("feasible at the time limit, gap 1.8%",)`.
- `PLANNER=auto` in the API falls back to `greedy` when `solve()` raises NotImplementedError
  or returns UNKNOWN. INFEASIBLE is final.

## 7. Making it fast

- **Tight domains.** Give every variable the smallest domain you can compute (a day's usage
  of a food is at most `Σ grams × hi` over that day's candidates). CP-SAT rejects a model
  (MODEL_INVALID) when a linear expression's bounds could overflow int64, and wide domains get
  there quickly: weights reach 2×10^5 and prices 10^6 per kg. Tight domains also make
  propagation and the LP relaxation much stronger.
- **No day-symmetry breaking.** Days look interchangeable, but locks, `extra`, lot expiry and
  churn make them differ, and in the prototype lexicographic ordering of days made the first
  solution slower and the final gap worse.
- **Hints.** `model.add_hint(var, value)` from the greedy plan (`baseline.greedy`, ~25 ms), or
  from `previous` when replanning, usually gives CP-SAT a good first solution immediately. A
  hint is a speed-up, never a guarantee: it may break a hard rule the greedy plan missed (kcal
  band, budget), and CP-SAT then repairs or ignores it.
- **Parameters.**

  ```python
  solver.parameters.max_time_in_seconds = remaining_ms / 1000  # time_limit_ms minus build time
  solver.parameters.num_workers = min(workers, os.cpu_count() or 1)
  ```

  The wall budget includes building the model (test 12: wall ≤ `time_limit_ms` + 500 ms).
  `solver.parameters.log_search_progress = True` while developing.
- Multi-worker search isn't deterministic run to run; the tests only rely on determinism at
  OPTIMAL.

**Prototype numbers** (design review; real catalogue, 40 candidates × 4 slots × 7 days):
first solution in 0.4–1 s with ≥ 2 workers; practically always FEASIBLE at the 3.5 s limit
with a 0.5–4% gap, rarely OPTIMAL. With protein/fat/carbs as hard bands, vegetarian, vegan and
budget profiles often ended UNKNOWN, which is why they are soft. Day-symmetry breaking hurt.

## 8. Running the specification

```sh
uv run pytest packages/solver/tests/test_solve.py   # the spec: 62 tests, xfail until solve() exists
uv run pytest -m perf packages/solver               # realistic size: 20 seeds, p95 < 4 s
uv run pytest packages/solver                       # everything else (validator, greedy, ...)
make bench                                          # end to end through the API (bench added with the API work)
```

Functional tests use `time_limit_ms=2000, workers=4` on planted problems (k=10) and small
hand-built ones (10 s, where OPTIMAL is expected). Once `solve()` is implemented, delete the
module-level `pytestmark` in `test_solve.py` so passing tests count as passes; M3 is done when
the spec passes and a `make bench --planner cpsat` result is recorded in `docs/progress.md`.

Useful while developing:

- `scenarios.planted(seed, k=10)` has a known valid plan (`scenario.witness`) and decoys
  (`scenario.decoys`); `validate(problem, plan)` says in plain English what is wrong.
- `score(problem, plan, previous).terms` gives each objective term; compare with the model.
- `greedy(problem)` is a baseline to beat: `score(...).total` of its plan.

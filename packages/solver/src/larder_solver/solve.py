"""CP-SAT weekly planner: `solve(problem, previous, time_limit_ms) -> PlanResult`.

The modelling guide is packages/solver/README.md (overview in docs/DESIGN.md §8) and the
specification is packages/solver/tests/test_solve.py. In short:

- One boolean per (day, slot, recipe, portions) in every open cell (encoding B: an exact linear
  relaxation). Locked cells are constants; a chosen cell draws on its choice instead of the
  slot's candidates. Only eligible, allowed recipes get variables, so the hard filters hold by
  construction; an unsafe lock or a cell that must be filled from nothing is INFEASIBLE before
  any search.
- kcal (each day's rule and the weekly band) and the budget are hard linear constraints;
  protein, fat and carbs bands are soft, with shortfall and excess auxiliaries.
- Pantry: grams drawn per (lot, day) for foods in stock, any allocation (at the optimum it is
  worth as much as `metrics.allocate`'s EDF); foods not in stock cost their price per gram.
- The objective is `metrics.score` term by term, constants included, so `objective <= score
  <= bound` holds for every plan and `objective == score` at OPTIMAL.
- Hints come from `previous` when replanning (keep what can be kept), else the greedy plan.

The default time limit leaves ~1.5 s of the 5 s p95 budget for loading inputs, the prefilter,
validation and saving. Use at most `workers` search threads, capped at the CPU count.
"""

import math
import os
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from time import perf_counter

from ortools.sat.python import cp_model

from larder_solver.baseline import greedy
from larder_solver.candidates import allowed
from larder_solver.metrics import _deadline  # pyright: ignore[reportPrivateUsage]
from larder_solver.problem import (
    HARD_NUTRIENTS,
    SLOT_ORDER,
    Band,
    Macros,
    Meal,
    Nutrient,
    Plan,
    PlanResult,
    Problem,
    Recipe,
    Slot,
    Status,
)

PLANNER = "cpsat"
MIN_SEARCH_S = 0.05  # always give the search a moment, however long building took
EXACT = 2**53  # objective and bound are doubles: exact below this

_STATUS = {
    cp_model.OPTIMAL: Status.OPTIMAL,
    cp_model.FEASIBLE: Status.FEASIBLE,
    cp_model.INFEASIBLE: Status.INFEASIBLE,
    cp_model.UNKNOWN: Status.UNKNOWN,
    cp_model.MODEL_INVALID: Status.INVALID,
}

type _Cell = tuple[int, Slot]
type _Key = tuple[int, Slot, int, int]  # day, slot, recipe id, portions


def solve(
    problem: Problem,
    previous: Plan | None = None,
    time_limit_ms: int = 3_500,
    *,
    workers: int = 8,
) -> PlanResult:
    started = perf_counter()
    model = _Model(problem, previous)
    if model.infeasible:
        return _result(started, Status.INFEASIBLE, notes=(model.infeasible,))
    model.build()
    model.hint(previous, greedy(problem, previous).plan)

    solver = cp_model.CpSolver()
    left_s = time_limit_ms / 1000 - (perf_counter() - started)
    solver.parameters.max_time_in_seconds = max(left_s, MIN_SEARCH_S)
    solver.parameters.num_workers = max(1, min(workers, os.cpu_count() or 1))
    # Light presolve: at full size the default presolve (probing, big linear overlaps) takes
    # most of the time limit, and the search finds far better plans in that time.
    solver.parameters.max_presolve_iterations = 1
    solver.parameters.cp_model_probing_level = 0
    solver.parameters.find_big_linear_overlap = False
    status = _STATUS[solver.solve(model.cp)]
    if status not in (Status.OPTIMAL, Status.FEASIBLE):
        return _result(started, status)

    plan = model.plan(solver)
    objective, bound = solver.objective_value, solver.best_objective_bound
    assert abs(objective) < EXACT, objective
    assert abs(bound) < EXACT, bound
    # No note for the gap: notes reach the user, and objective and bound already carry it.
    return _result(started, status, plan, round(objective), round(bound))


def _result(
    started: float,
    status: Status,
    plan: Plan | None = None,
    objective: int | None = None,
    bound: int | None = None,
    notes: tuple[str, ...] = (),
) -> PlanResult:
    wall_ms = math.ceil((perf_counter() - started) * 1000)
    return PlanResult(status, plan, PLANNER, wall_ms, objective, bound, notes)


@dataclass
class _Linear:
    """A linear expression kept as a constant plus (variable, coefficient) terms, with the
    bounds it can reach (every variable here is >= 0)."""

    const: int = 0
    terms: list[tuple[cp_model.IntVar, int]] = field(
        default_factory=list[tuple[cp_model.IntVar, int]]
    )
    hi: int = 0  # most the terms can add (for domains)

    def add(self, var: cp_model.IntVar, coef: int) -> None:
        if coef:
            self.terms.append((var, coef))

    def expr(self) -> cp_model.LinearExpr:
        variables = [v for v, _ in self.terms]
        coefs = [c for _, c in self.terms]
        total = cp_model.LinearExpr.weighted_sum(variables, coefs)  # pyright: ignore[reportUnknownMemberType]
        return total + self.const


class _Model:
    def __init__(self, problem: Problem, previous: Plan | None) -> None:
        self.p = problem
        self.previous = previous
        self.cp = cp_model.CpModel()
        self.infeasible = ""
        self.y: dict[_Key, cp_model.IntVar] = {}
        self.cells: dict[_Cell, list[_Key]] = {}
        self.must: set[_Cell] = set()  # cells that need a meal: required slots, choices
        self.room: dict[int, int] = {}  # unlocked uses each recipe has left
        # Auxiliaries, kept so a hint can set them too: slacks are max(0, sign * (total - at)),
        # draws[(lot index, day)] grams taken from a lot, usage[(food, day)] grams eaten.
        self.slacks: list[tuple[cp_model.IntVar, _Linear, int, int]] = []
        self.draws: dict[tuple[int, int], cp_model.IntVar] = {}
        self.usage: dict[tuple[int, int], _Linear] = {}
        self.locked = [m for m in problem.locked.values() if m is not None]
        self._open_cells()

    # --- which cells and recipes get variables ---------------------------------------------

    def _open_cells(self) -> None:
        p = self.p
        for meal in self.locked:
            if not allowed(p.recipes[meal.recipe_id], p.foods, p.profile):
                self.infeasible = f"the meal locked on day {meal.day} {meal.slot} isn't safe"
                return
        locked_uses = Counter(m.recipe_id for m in self.locked)
        room = self.room
        room.update(
            (rid, max(0, p.repeat_cap(r) - locked_uses[rid])) for rid, r in p.recipes.items()
        )
        ok: dict[tuple[int, Slot], bool] = {}

        def usable(rid: int, slot: Slot) -> bool:
            if (rid, slot) not in ok:
                r = p.recipes.get(rid)
                ok[rid, slot] = bool(
                    r is not None
                    and slot in r.meal_types
                    and room[rid] > 0
                    and allowed(r, p.foods, p.profile)
                )
            return ok[rid, slot]

        for day in range(p.days):
            for spec in p.slots:
                cell = (day, spec.slot)
                if cell in p.locked:
                    continue
                chosen = p.choices.get(cell)
                ids = dict.fromkeys(chosen if chosen is not None else spec.candidates)
                rids = [rid for rid in ids if usable(rid, spec.slot)]
                must = chosen is not None or spec.required
                if must and not rids:
                    what = "chosen" if chosen is not None else "required"
                    self.infeasible = f"nothing fits the {what} {spec.slot} on day {day}"
                    return
                lo, hi = p.portion_range(spec.slot)
                keys = [(day, spec.slot, rid, q) for rid in rids for q in range(lo, hi + 1)]
                self.cells[cell] = keys
                if must:
                    self.must.add(cell)

    # --- constraints and objective ---------------------------------------------------------

    def build(self) -> None:
        p, cp, w = self.p, self.cp, self.p.weights
        for cell, keys in self.cells.items():
            for k in keys:
                self.y[k] = cp.new_bool_var(f"y_{k[0]}_{k[1]}_{k[2]}_{k[3]}")
            choice = [self.y[k] for k in keys]
            if cell in self.must:
                cp.add_exactly_one(choice)
            elif choice:
                cp.add_at_most_one(choice)

        objective = _Linear()
        self._nutrition(objective)
        self._repeats(objective)
        self._food(objective)

        required = {s.slot for s in p.slots if s.required}
        for meal in self.locked:
            objective.const += w.preference * p.recipes[meal.recipe_id].preference
            objective.const -= w.optional_meal * (meal.slot not in required)
        for (_, slot, rid, _), var in self.y.items():
            value = w.preference * p.recipes[rid].preference
            value -= w.optional_meal * (slot not in required)
            objective.add(var, value)
        self._churn(objective)
        cp.maximize(objective.expr())

    def _total(self, day: int | None, nutrient: Nutrient) -> _Linear:
        """A day's total of `nutrient` (or the week's, day None): extra, locked, planned."""
        p = self.p
        days = range(p.days) if day is None else (day,)
        t = _Linear()
        for d in days:
            t.const += p.extra.get(d, Macros()).get(nutrient)
        for meal in self.locked:
            if meal.day in days:
                t.const += p.recipes[meal.recipe_id].per_portion.get(nutrient) * meal.portions
        for (cday, _), keys in self.cells.items():
            if cday not in days:
                continue
            most = 0
            for k in keys:
                value = p.recipes[k[2]].per_portion.get(nutrient) * k[3]
                t.add(self.y[k], value)
                most = max(most, value)
            t.hi += most
        return t

    def _nutrition(self, objective: _Linear) -> None:
        p, cp = self.p, self.cp
        targets = p.targets
        kcal = targets.daily.get(Nutrient.KCAL, Band())
        for day in range(p.days):
            band = p.day_kcal.get(day)
            if band is None:  # the usual rule: the daily band and the floor
                floor = targets.calorie_floor
                band = Band(floor if kcal.min is None else max(floor, kcal.min), kcal.max)
            self._hard(self._total(day, Nutrient.KCAL), band)
        week = targets.weekly.get(Nutrient.KCAL)
        if week is not None:
            self._hard(self._total(None, Nutrient.KCAL), week)

        soft = [(d, n, b) for d in range(p.days) for n, b in targets.daily.items()]
        soft += [(None, n, b) for n, b in targets.weekly.items()]
        for day, nutrient, band in soft:
            if nutrient in HARD_NUTRIENTS:
                continue
            t = self._total(day, nutrient)
            # shortfall >= min - total, excess >= total - max; tight at the optimum
            if band.min is not None and band.min > t.const:
                short = cp.new_int_var(0, band.min - t.const, f"short_{day}_{nutrient}")
                cp.add(t.expr() + short >= band.min)
                self.slacks.append((short, t, -1, band.min))
                objective.add(short, -p.weights.macro)
            if band.max is not None and t.const + t.hi > band.max:
                excess = cp.new_int_var(0, t.const + t.hi - band.max, f"excess_{day}_{nutrient}")
                cp.add(t.expr() - excess <= band.max)
                self.slacks.append((excess, t, 1, band.max))
                objective.add(excess, -p.weights.macro)

    def _hard(self, total: _Linear, band: Band) -> None:
        if band.min is not None:
            self.cp.add(total.expr() >= band.min)
        if band.max is not None:
            self.cp.add(total.expr() <= band.max)

    def _repeats(self, objective: _Linear) -> None:
        p, cp = self.p, self.cp
        uses: dict[int, list[cp_model.IntVar]] = {}
        for (_, _, rid, _), var in self.y.items():
            uses.setdefault(rid, []).append(var)
        locked = Counter(m.recipe_id for m in self.locked)
        for rid, n in locked.items():
            if rid not in uses:
                objective.const -= p.weights.repeat * (n - 1)
        for rid, variables in uses.items():
            cap = self.room[rid]
            if len(variables) > cap:
                cp.add(sum(variables) <= cap)
            most = min(cap, len(variables)) + locked[rid]
            if most <= 1:
                continue
            rep = cp.new_int_var(0, most - 1, f"rep_{rid}")
            cp.add(rep >= sum(variables) + locked[rid] - 1)
            self.slacks.append((rep, _Linear(locked[rid] - 1, [(v, 1) for v in variables]), 1, 0))
            objective.add(rep, -p.weights.repeat)

    def _food(self, objective: _Linear) -> None:
        """Usage per (food, day) from the planned and locked meals, the pantry draws, cost,
        waste and the budget."""
        p, cp, w = self.p, self.cp, self.p.weights
        usage = self.usage

        def use(day: int, recipe: Recipe) -> Iterable[tuple[_Linear, int]]:
            for ing in recipe.ingredients:
                if ing.grams > 0 and ing.food_id in p.foods:
                    yield usage.setdefault((ing.food_id, day), _Linear()), ing.grams

        for meal in self.locked:
            for u, grams in use(meal.day, p.recipes[meal.recipe_id]):
                u.const += grams * meal.portions
        for (day, _), keys in self.cells.items():
            most: dict[int, int] = {}
            for k in keys:
                for u, grams in use(day, p.recipes[k[2]]):
                    u.add(self.y[k], grams * k[3])
                    most[id(u)] = max(most.get(id(u), 0), grams * k[3])
            for u in usage.values():
                u.hi += most.get(id(u), 0)

        lots: dict[int, list[int]] = {}
        for i, lot in enumerate(p.pantry):
            if lot.grams > 0 and (lot.expires is None or lot.expires >= 0):
                lots.setdefault(lot.food_id, []).append(i)
        drawn: dict[int, list[cp_model.IntVar]] = {}
        spend = _Linear()
        for (food_id, day), u in usage.items():
            price = p.foods[food_id].price_per_kg
            draws: list[cp_model.IntVar] = []
            for i in lots.get(food_id, ()):
                lot = p.pantry[i]
                if lot.expires is not None and lot.expires < day:
                    continue
                cap = min(lot.grams, u.const + u.hi)
                if cap <= 0:
                    continue
                var = cp.new_int_var(0, cap, f"draw_{i}_{day}")
                self.draws[i, day] = var
                draws.append(var)
                drawn.setdefault(i, []).append(var)
                objective.add(var, w.pantry + w.cost * price)
            # bought = usage - draws >= 0, costed at the price per gram
            if draws:
                cp.add(sum(draws) <= u.expr())
            objective.const -= w.cost * price * u.const
            for var, coef in u.terms:
                objective.add(var, -w.cost * price * coef)
            spend.const += price * u.const
            for var, coef in u.terms:
                spend.add(var, price * coef)
            for var in draws:
                spend.add(var, -price)
        for i, variables in drawn.items():
            if len(variables) > 1:  # a single draw's domain already stops at the lot's grams
                cp.add(sum(variables) <= p.pantry[i].grams)
        for i, lot in enumerate(p.pantry):
            if lot.grams > 0 and lot.expires is not None and 0 <= lot.expires < p.days:
                price = p.foods[lot.food_id].price_per_kg
                objective.const -= w.waste * price * lot.grams
                for var in drawn.get(i, ()):
                    objective.add(var, w.waste * price)
        if p.budget is not None:
            cp.add(spend.expr() <= p.budget * 1000)

    def _churn(self, objective: _Linear) -> None:
        """-w.churn per (day, slot) whose recipe differs from `previous` (Plan.at semantics)."""
        if self.previous is None:
            return
        weight = self.p.weights.churn
        before: dict[_Cell, int] = {}
        for meal in self.previous.meals:
            before.setdefault((meal.day, meal.slot), meal.recipe_id)
        locked = {cell: m.recipe_id for cell, m in self.p.locked.items() if m is not None}
        for cell in before.keys() | locked.keys():  # constants: cells nobody plans
            if cell not in self.cells and before.get(cell) != locked.get(cell):
                objective.const -= weight
        for cell, keys in self.cells.items():
            r0 = before.get(cell)
            if r0 is None:  # any meal here is a change
                for k in keys:
                    objective.add(self.y[k], -weight)
            else:  # 1 - [the previous recipe is kept]
                objective.const -= weight
                for k in keys:
                    if k[2] == r0:
                        objective.add(self.y[k], weight)

    # --- hints and the answer --------------------------------------------------------------

    def hint(self, *plans: Plan | None) -> None:
        """A complete hint: each open cell from the first plan that can keep its meal there
        (`previous` first, so a replan starts from no churn), then every auxiliary at its
        value for those meals. A hint that breaks a hard rule only costs CP-SAT a repair."""
        picks: dict[_Cell, Meal | None] = {}
        for plan in plans:
            if plan is None:
                continue
            at: dict[_Cell, Meal] = {}
            for meal in plan.meals:
                at.setdefault((meal.day, meal.slot), meal)
            for cell in self.cells.keys() - picks.keys():
                meal = at.get(cell)
                if meal is None or (*cell, meal.recipe_id, meal.portions) in self.y:
                    picks[cell] = meal
        if not picks:
            return
        value: dict[int, int] = {}  # variable index -> hinted value
        for cell, keys in self.cells.items():
            meal = picks.get(cell)
            kept = None if meal is None else (*cell, meal.recipe_id, meal.portions)
            for k in keys:
                value[self.y[k].index] = int(k == kept)

        def total(t: _Linear) -> int:
            return t.const + sum(c * value.get(v.index, 0) for v, c in t.terms)

        # pantry draws: earliest deadline first, like metrics.allocate
        left = {i: lot.grams for i, lot in enumerate(self.p.pantry)}
        order = sorted({i for i, _ in self.draws}, key=lambda i: _deadline(self.p.pantry[i], i))
        for (food_id, day), u in sorted(self.usage.items(), key=lambda fu: fu[0][1]):
            need = total(u)
            for i in order:
                var = self.draws.get((i, day))
                if var is None or self.p.pantry[i].food_id != food_id:
                    continue
                take = min(need, left[i])
                left[i] -= take
                need -= take
                value[var.index] = take
        for var, t, sign, bound in self.slacks:
            value[var.index] = max(0, sign * (total(t) - bound))
        for var in [*self.y.values(), *self.draws.values(), *(v for v, *_ in self.slacks)]:
            self.cp.add_hint(var, value[var.index])

    def plan(self, solver: cp_model.CpSolver) -> Plan:
        meals = list(self.locked)
        meals += [Meal(*k) for k, var in self.y.items() if solver.boolean_value(var)]
        rank = {slot: i for i, slot in enumerate(SLOT_ORDER)}
        return Plan(tuple(sorted(meals, key=lambda m: (m.day, rank[m.slot]))))

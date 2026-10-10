"""Greedy baseline planner: `greedy(problem, previous, time_limit_ms) -> PlanResult`.

It makes the app usable before the CP-SAT model exists and is the baseline the evals compare
against. It plans one day at a time, in order, and never goes back:

1. Locked meals and food eaten off-plan are fixed. A locked meal that breaks a hard filter means
   no plan (locks never skip the filters).
2. Options per open slot: the top 8 candidates (4 for an optional slot, which may also stay
   empty) that pass the hard filters (`candidates.allowed`), fit the slot and are still under
   their repeat cap, ranked by preference, then protein per kcal, then id; plus the previous
   plan's recipe for that slot when it qualifies. Each comes in every allowed portion count. A
   recipe appears at most once a day.
3. Day score, in `Weights` units: preference; minus the shopping cost at full price (the pantry
   is left to the shopping list); minus a repeat for a recipe already planned; minus a snack;
   plus a kept slot when replanning (churn); plus half the macro weight per gram of protein, up
   to the day's share of the protein target (the daily minimum, or what the weekly minimum still
   needs spread over the days left). The cost term is what keeps most plans within budget.
4. Search: the day's open slots are split into two halves, keeping slots that share recipes
   (lunch and dinner) together. Each half's combinations are enumerated; the second half's are
   sorted by kcal, so for each first-half combination a bisect finds the ones that land the day
   in the kcal window, and a sparse table gives the best of those in O(1). The protein cap makes
   the score non-separable, so the best is judged among the window's top entry by score with
   protein and its top entry without: exact when the protein target is out of reach or already
   met, a close heuristic in between.
5. Window: the daily kcal band and floor narrowed to the day's share of the weekly kcal band;
   if nothing fits, the daily band and floor; if still nothing, the combination closest to the
   band that meets the floor. If no combination meets the floor, there is no plan.
6. Repeat caps stay satisfiable: after each day, every group of required slots must still be
   fillable within the caps on the days left (Hall's condition, as in `diagnose`). If a day's
   choice breaks it, the recipes that took the group's capacity from outside the group are
   dropped from that day's options and the day is planned again.

So, by construction, its plans pass every hard filter, fill every required slot, honour locks,
eligibility, portion ranges and repeat caps, and meet the calorie floor. The kcal bands, the
budget and the soft macro bands may be missed; the API saves such plans and shows the misses. It
never consults the validator, which checks it like any other planner.

Result: FEASIBLE with a plan (`objective` = `metrics.score(problem, plan, previous).total`, so
objective == score, and `bound` None: the baseline proves nothing), or INFEASIBLE with no plan
and a note saying why. For this planner INFEASIBLE means "the baseline found no plan", not a
proof; `diagnose` gives the user-facing reasons. Deterministic; a few tens of milliseconds for 40
candidates x 4 slots x 7 days.
"""

import math
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from fractions import Fraction
from itertools import combinations, product
from time import perf_counter

from larder_solver.candidates import allowed
from larder_solver.metrics import score
from larder_solver.problem import (
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
    SlotSpec,
    Status,
)

PLANNER = "greedy"
TOP = 8  # options per required slot and day
TOP_OPTIONAL = 4  # options per optional slot and day (besides leaving it empty)
RETRIES = 4  # re-plans of one day to keep the repeat caps satisfiable
_FAR = 10**15  # stands in for a missing band side

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def greedy(
    problem: Problem, previous: Plan | None = None, time_limit_ms: int = 3_500
) -> PlanResult:
    """Plan day by day (see the module docstring). `time_limit_ms` is accepted for parity with
    `solve()`; the baseline always finishes far sooner."""
    started = perf_counter()
    planner = _Greedy(problem, previous)
    plan = planner.run()
    notes = tuple(planner.notes)
    if plan is None:
        return PlanResult(Status.INFEASIBLE, None, PLANNER, _ms(started), notes=notes)
    objective = score(problem, plan, previous).total
    return PlanResult(Status.FEASIBLE, plan, PLANNER, _ms(started), objective, None, notes)


def _ms(started: float) -> int:
    return math.ceil((perf_counter() - started) * 1000)


@dataclass(frozen=True, slots=True)
class _Item:
    """One way to fill one slot: a recipe at some portions, or nothing (optional slots)."""

    slot: Slot
    recipe_id: int | None
    portions: int
    kcal: int
    protein: int
    value: int  # day score apart from protein


@dataclass(frozen=True, slots=True)
class _Combo:
    """One way to fill a set of slots."""

    items: tuple[_Item, ...]
    recipes: frozenset[int]
    kcal: int
    protein: int
    value: int


def _combos(options: Sequence[Sequence[_Item]]) -> list[_Combo]:
    out: list[_Combo] = []
    for items in product(*options):
        ids = [i.recipe_id for i in items if i.recipe_id is not None]
        recipes = frozenset(ids)
        if len(recipes) == len(ids):  # a recipe at most once a day
            kcal = sum(i.kcal for i in items)
            protein = sum(i.protein for i in items)
            out.append(_Combo(items, recipes, kcal, protein, sum(i.value for i in items)))
    return out


class _ArgMax:
    """Sparse table: index of the largest value in any range in O(1) (ties: lowest index)."""

    def __init__(self, values: list[int]) -> None:
        self.values = values
        self.rows = [list(range(len(values)))]
        width = 1
        while 2 * width <= len(values):
            prev = self.rows[-1]
            self.rows.append(
                [
                    a if values[a] >= values[b] else b
                    for a, b in zip(prev, prev[width:], strict=False)
                ]
            )
            width *= 2

    def best(self, start: int, stop: int) -> int:
        """Argmax over values[start:stop]; needs start < stop."""
        level = (stop - start).bit_length() - 1
        row = self.rows[level]
        a, b = row[start], row[stop - (1 << level)]
        va, vb = self.values[a], self.values[b]
        return a if va > vb or (va == vb and a <= b) else b


class _Side:
    """The second half's combinations sorted by kcal, with range-best lookups."""

    def __init__(self, combos: list[_Combo], protein_weight: int) -> None:
        self.combos = sorted(combos, key=lambda c: c.kcal)  # stable: ties keep product order
        self.kcal = [c.kcal for c in self.combos]
        self.by_value = _ArgMax([c.value for c in self.combos])
        self.by_protein = _ArgMax([c.value + protein_weight * c.protein for c in self.combos])


@dataclass(frozen=True, slots=True)
class _Day:
    """What a day's search needs besides the options."""

    fixed: Macros  # off-plan intake plus locked meals
    protein_target: int


class _Greedy:
    def __init__(self, problem: Problem, previous: Plan | None) -> None:
        self.p = problem
        w = problem.weights
        self.protein_weight = w.macro // 2
        self.specs = sorted(problem.slots, key=lambda s: SLOT_ORDER.index(s.slot))
        self.previous: dict[tuple[int, Slot], int] | None = None
        if previous is not None:
            self.previous = {}
            for meal in previous.meals:
                self.previous.setdefault((meal.day, meal.slot), meal.recipe_id)
        self.ok: dict[int, bool] = {}
        self.pool: dict[Slot, list[Recipe]] = {}  # allowed candidates fitting the slot, ranked
        for spec in self.specs:
            recipes = (problem.recipes.get(r) for r in dict.fromkeys(spec.candidates))
            fit = [r for r in recipes if r and spec.slot in r.meal_types and self.safe(r)]
            self.pool[spec.slot] = sorted(fit, key=_rank)
        self.caps = {r.id: problem.repeat_cap(r) for rs in self.pool.values() for r in rs}
        self.locks = {
            at: meal
            for at, meal in problem.locked.items()
            if meal is not None and 0 <= at[0] < problem.days
        }
        self.uses: Counter[int] = Counter(m.recipe_id for m in self.locks.values())
        self.required = [s.slot for s in self.specs if s.required]
        self.groups = [
            (frozenset(g), {r.id for s in g for r in self.pool[s]})
            for n in range(1, len(self.required) + 1)
            for g in combinations(self.required, n)
        ]
        self.meals: list[Meal] = list(self.locks.values())
        self.totals: list[Macros] = []
        self.notes: list[str] = []

    def safe(self, recipe: Recipe) -> bool:
        if recipe.id not in self.ok:
            self.ok[recipe.id] = allowed(recipe, self.p.foods, self.p.profile)
        return self.ok[recipe.id]

    def day_name(self, day: int) -> str:
        return _WEEKDAYS[(self.p.start + timedelta(days=day)).weekday()]

    # --- the week --------------------------------------------------------------------------------

    def run(self) -> Plan | None:
        for (day, slot), meal in sorted(self.locks.items(), key=lambda kv: _at(kv[0])):
            recipe = self.p.recipes.get(meal.recipe_id)
            if recipe is None or not self.safe(recipe):
                self.notes.append(f"{self.day_name(day)} {slot}: the fixed meal isn't allowed")
                return None
        if self.hall(-1, Counter()) is not None:
            self.notes.append("not enough recipes within the repeat limits")
            return None
        for day in range(self.p.days):
            chosen = self.plan_day(day)
            if chosen is None:
                return None
            for item in chosen:
                if item.recipe_id is not None:
                    self.meals.append(Meal(day, item.slot, item.recipe_id, item.portions))
                    self.uses[item.recipe_id] += 1
        return Plan(tuple(sorted(self.meals, key=lambda m: _at((m.day, m.slot)))))

    def plan_day(self, day: int) -> tuple[_Item, ...] | None:
        excluded: set[tuple[Slot, int]] = set()
        chosen, note = self.choose(day, excluded)
        for _ in range(RETRIES):
            if chosen is None:
                break
            used = Counter(i.recipe_id for i in chosen if i.recipe_id is not None)
            group = self.hall(day, used)
            if group is None:
                break
            slots, pool = group
            culprits = {
                (i.slot, i.recipe_id)
                for i in chosen
                if i.recipe_id is not None and i.recipe_id in pool and i.slot not in slots
            }
            if culprits <= excluded:
                break
            excluded |= culprits
            retry, retry_note = self.choose(day, excluded)
            if retry is None:
                break  # keep the previous choice
            chosen, note = retry, retry_note
        if note is not None:
            self.notes.append(note)
        if chosen is not None:
            self.totals.append(self.fixed(day) + _macros(self.p, chosen))
        return chosen

    def hall(self, day: int, used: Counter[int]) -> tuple[frozenset[Slot], set[int]] | None:
        """The first group of required slots whose candidates can no longer fill its open meals
        after `day` within the repeat caps, counting `used` on top of the plan so far."""
        for slots, pool in self.groups:
            need = sum(
                (d, s) not in self.p.locked for s in slots for d in range(day + 1, self.p.days)
            )
            if need and sum(max(0, self.caps[r] - self.uses[r] - used[r]) for r in pool) < need:
                return slots, pool
        return None

    # --- one day ---------------------------------------------------------------------------------

    def fixed(self, day: int) -> Macros:
        total = self.p.extra.get(day, Macros())
        for (d, _), meal in self.locks.items():
            if d == day and meal.recipe_id in self.p.recipes:
                total += self.p.recipes[meal.recipe_id].per_portion.times(meal.portions)
        return total

    def choose(
        self, day: int, excluded: set[tuple[Slot, int]]
    ) -> tuple[tuple[_Item, ...] | None, str | None]:
        """The day's meals (None: none possible) and a note on any miss."""
        name = self.day_name(day)
        options: list[list[_Item]] = []
        for spec in self.specs:
            if (day, spec.slot) in self.p.locked:
                continue
            items = self.options(spec, day, excluded)
            if spec.required and not items:
                return None, f"{name}: no {spec.slot} left within the repeat limits"
            options.append(items)
        fixed = self.fixed(day)
        today = _Day(fixed, self.protein_target(day))
        left_ix, right_ix = _split(options)
        left = _combos([options[i] for i in left_ix])
        right = _combos([options[i] for i in right_ix])
        sides = _Sides(right, self.protein_weight)

        band = self.p.targets.daily.get(Nutrient.KCAL, Band())
        floor = self.p.targets.calorie_floor
        low = max(floor, band.min if band.min is not None else floor)
        high = band.max if band.max is not None else _FAR
        windows: list[tuple[int, int]] = []
        week = self.week_window(day)
        if week is not None and max(low, week[0]) <= min(high, week[1]):
            windows.append((max(low, week[0]), min(high, week[1])))
        if low <= high:
            windows.append((low, high))
        for lo, hi in windows:
            best = self.best(today, left, sides, lo, hi)
            if best is not None:
                return best, None
        best = self.closest(today, left, sides, low, high, floor)
        if best is None:
            return None, f"{name}: no meals that fit reach the {floor:,} kcal floor"
        total = fixed.kcal + sum(i.kcal for i in best)
        return best, f"{name}: the kcal band was out of reach ({total:,} kcal)"

    def options(self, spec: SlotSpec, day: int, excluded: set[tuple[Slot, int]]) -> list[_Item]:
        w = self.p.weights
        before = None if self.previous is None else self.previous.get((day, spec.slot))
        limit = TOP if spec.required else TOP_OPTIONAL
        picked: list[Recipe] = []
        for r in self.pool[spec.slot]:
            if (spec.slot, r.id) in excluded or self.uses[r.id] >= self.caps[r.id]:
                continue
            if len(picked) < limit or r.id == before:
                picked.append(r)
        lo, hi = self.p.portion_range(spec.slot)
        items: list[_Item] = []
        if not spec.required:
            kept = self.previous is not None and before is None
            items.append(_Item(spec.slot, None, 0, 0, 0, w.churn if kept else 0))
        for r in picked:
            value = w.preference * r.preference
            value -= w.repeat if self.uses[r.id] else 0
            value -= 0 if spec.required else w.optional_meal
            value += w.churn if r.id == before else 0
            cost = w.cost * self.cost(r)
            for n in range(lo, hi + 1):
                kcal, protein = r.per_portion.kcal * n, r.per_portion.protein_g * n
                items.append(_Item(spec.slot, r.id, n, kcal, protein, value - cost * n))
        return items

    def cost(self, recipe: Recipe) -> int:
        """Millipence per portion with every weighed ingredient bought."""
        return sum(
            i.grams * self.p.foods[i.food_id].price_per_kg
            for i in recipe.ingredients
            if i.food_id in self.p.foods
        )

    def protein_target(self, day: int) -> int:
        """Grams of protein worth rewarding today: the daily minimum, or the weekly minimum's
        remainder spread over the days left, whichever is more."""
        daily = self.p.targets.daily.get(Nutrient.PROTEIN)
        weekly = self.p.targets.weekly.get(Nutrient.PROTEIN)
        target = daily.min if daily is not None and daily.min is not None else 0
        if weekly is not None and weekly.min is not None:
            left = weekly.min - sum(t.protein_g for t in self.totals)
            target = max(target, -(-left // (self.p.days - day)))
        return max(target, 0)

    def week_window(self, day: int) -> tuple[int, int] | None:
        """Today's even share of what the weekly kcal band still allows."""
        week = self.p.targets.weekly.get(Nutrient.KCAL)
        if week is None:
            return None
        so_far = sum(t.kcal for t in self.totals)
        days_left = self.p.days - day
        lo = -_FAR if week.min is None else -(-(week.min - so_far) // days_left)
        hi = _FAR if week.max is None else (week.max - so_far) // days_left
        return lo, hi

    def score(self, today: _Day, left: _Combo, right: _Combo) -> int:
        protein = today.fixed.protein_g + left.protein + right.protein
        capped = min(protein, today.protein_target)
        return left.value + right.value + self.protein_weight * capped

    def best(
        self, today: _Day, left: list[_Combo], sides: "_Sides", lo: int, hi: int
    ) -> tuple[_Item, ...] | None:
        """The best combination whose day total lands in [lo, hi]."""
        best: tuple[int, _Combo, _Combo] | None = None
        for combo in left:
            side = sides.without(combo.recipes)
            base = today.fixed.kcal + combo.kcal
            start, stop = bisect_left(side.kcal, lo - base), bisect_right(side.kcal, hi - base)
            if start >= stop:
                continue
            for e in sorted({side.by_protein.best(start, stop), side.by_value.best(start, stop)}):
                other = side.combos[e]
                s = self.score(today, combo, other)
                if best is None or s > best[0]:  # ties: the first found
                    best = (s, combo, other)
        return None if best is None else best[1].items + best[2].items

    def closest(
        self,
        today: _Day,
        left: list[_Combo],
        sides: "_Sides",
        low: int,
        high: int,
        floor: int,
    ) -> tuple[_Item, ...] | None:
        """The combination nearest the band [low, high] that still meets the floor."""
        best: tuple[int, int, _Combo, _Combo] | None = None
        for combo in left:
            side = sides.without(combo.recipes)
            base = today.fixed.kcal + combo.kcal
            enough = bisect_left(side.kcal, floor - base)  # first entry meeting the floor
            below = bisect_left(side.kcal, low - base) - 1  # last entry under the band
            above = max(bisect_right(side.kcal, high - base), enough)
            for e in (below, above):
                if not enough <= e < len(side.kcal):
                    continue
                other = side.combos[e]
                total = base + other.kcal
                miss = max(0, low - total, total - high)
                s = self.score(today, combo, other)
                if best is None or (miss, -s) < (best[0], -best[1]):
                    best = (miss, s, combo, other)
        return None if best is None else best[2].items + best[3].items


class _Sides:
    """The second half, and copies without the recipes a first-half combination already uses
    (built on demand: with lunch and dinner on one side they are rare)."""

    def __init__(self, combos: list[_Combo], protein_weight: int) -> None:
        self.combos = combos
        self.weight = protein_weight
        self.recipes = frozenset[int]().union(*(c.recipes for c in combos))
        self.full = _Side(combos, protein_weight)
        self.cache: dict[frozenset[int], _Side] = {}

    def without(self, recipes: frozenset[int]) -> _Side:
        clash = recipes & self.recipes
        if not clash:
            return self.full
        if clash not in self.cache:
            kept = [c for c in self.combos if not c.recipes & clash]
            self.cache[clash] = _Side(kept, self.weight)
        return self.cache[clash]


def _split(options: Sequence[Sequence[_Item]]) -> tuple[list[int], list[int]]:
    """Indices of the first and second half: fewest recipes shared across the halves, then the
    smaller larger half, then the first such split."""
    n = len(options)
    if n <= 1:
        return [], list(range(n))
    ids = [{i.recipe_id for i in items if i.recipe_id is not None} for items in options]
    best: tuple[tuple[int, int], list[int], list[int]] | None = None
    for mask in range(1, 2 ** (n - 1)):  # the last slot always goes second
        left = [i for i in range(n) if mask >> i & 1]
        right = [i for i in range(n) if not mask >> i & 1]
        shared = set[int]().union(*(ids[i] for i in left)) & set[int]().union(
            *(ids[i] for i in right)
        )
        size = max(
            math.prod(len(options[i]) for i in left), math.prod(len(options[i]) for i in right)
        )
        key = (len(shared), size)
        if best is None or key < best[0]:
            best = (key, left, right)
    assert best is not None
    return best[1], best[2]


def _rank(recipe: Recipe) -> tuple[int, Fraction, int]:
    density = Fraction(recipe.per_portion.protein_g, max(recipe.per_portion.kcal, 1))
    return -recipe.preference, -density, recipe.id


def _at(at: tuple[int, Slot]) -> tuple[int, int]:
    day, slot = at
    return day, SLOT_ORDER.index(slot) if slot in SLOT_ORDER else len(SLOT_ORDER)


def _macros(problem: Problem, items: Sequence[_Item]) -> Macros:
    total = Macros()
    for i in items:
        if i.recipe_id is not None:
            total += problem.recipes[i.recipe_id].per_portion.times(i.portions)
    return total

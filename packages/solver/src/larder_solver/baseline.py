"""Greedy baseline planner: `greedy(problem, previous, time_limit_ms) -> PlanResult`.

It makes the app usable before the CP-SAT model exists and is the baseline the evals compare
against. It plans one day at a time, in order, and never goes back:

1. Locked meals and food eaten off-plan are fixed. A locked meal that breaks a hard filter means
   no plan (locks never skip the filters). So does a chosen cell (`Problem.choices`) none of
   whose recipes passes the hard filters and fits the slot.
2. Options per open slot: the top 8 candidates (4 for an optional slot, which may also stay empty)
   that pass the hard filters (`candidates.allowed`), fit the slot and are still under their repeat
   cap, ranked by preference, then protein per kcal, then id; plus the previous plan's recipe for
   that slot when it qualifies, and on a day with a `Problem.day_kcal` band the lightest and the
   heaviest that qualify (that band is clipped to what they reach). A chosen cell draws on its
   choice instead of the slot's candidates, the same way (top 8 of those that pass and fit), and is
   never empty, even in an optional slot. Each comes in every allowed portion count. A recipe
   appears at most once a day, except in several chosen cells (leftovers) while its repeat cap has
   room for all of them.
3. Day score, in `Weights` units: preference; minus the shopping cost at full price (the pantry
   is left to the shopping list); minus a repeat for a recipe already planned; minus a snack;
   minus an unusual meal (those also rank last for the top 8); minus each kcal a meal is outside
   its slot's size (recipes that can reach it rank first among equally liked ones); plus a kept
   slot when replanning (churn); plus half the macro weight per gram of protein, up
   to the day's share of the protein target (the daily minimum, or what the weekly minimum still
   needs spread over the days left). The cost term is what keeps most plans within budget.
4. Search: the day's open slots are split into two halves, keeping slots that share recipes
   (lunch and dinner) together. Each half's combinations are enumerated; the second half's are
   sorted by kcal, so for each first-half combination a bisect finds the ones that land the day
   in the kcal window, and a sparse table gives the best of those in O(1). The protein cap makes
   the score non-separable, so the best is judged among the window's top entry by score with
   protein and its top entry without: exact when the protein target is out of reach or already
   met, a close heuristic in between.
5. Window: the day's kcal rule is the daily kcal band and the floor, or on a day with a
   `Problem.day_kcal` band, that band alone, its min acting as the day's floor (an open min:
   no floor). The rule narrowed to the day's share of the weekly kcal band; if nothing fits,
   the rule itself; if still nothing, the combination closest to the band that meets the
   floor. If no combination meets the floor, there is no plan.
6. Repeat caps stay satisfiable: after each day, the open cells left (each required slot's free
   cells, and the chosen cells grouped by their choice) must still be fillable within the caps,
   checked exactly as a max-flow from cells to recipes. If a day's choice breaks it, the
   recipes the flow can't spare (those reachable in the residual graph, i.e. the neighbourhood
   of a set of cells violating Hall's condition) are dropped from that day's options in the
   slots that could use something else, and the day is planned again.

So, by construction, its plans pass every hard filter, fill every required slot and chosen
cell, honour locks, choices, eligibility, portion ranges and repeat caps, and meet the calorie
floor (on a `day_kcal` day: that band's min). The kcal bands (a `day_kcal` band's max), the
budget and the soft macro bands may be missed; the API saves such plans and shows the misses.
It never consults the validator, which checks it like any other planner.

Result: FEASIBLE with a plan (`objective` = `metrics.score(problem, plan, previous).total`, so
objective == score, and `bound` None: the baseline proves nothing), or INFEASIBLE with no plan
and a note saying why. For this planner INFEASIBLE means "the baseline found no plan", not a
proof; `diagnose` gives the user-facing reasons. Deterministic; a few tens of milliseconds for 40
candidates x 4 slots x 7 days.
"""

import math
from bisect import bisect_left, bisect_right
from collections import Counter, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from fractions import Fraction
from itertools import product
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

# What an open cell that must hold a meal draws on: a required slot's candidates (its free
# cells), or a choice (chosen cells, by the recipe ids they may hold).
type _Kind = Slot | frozenset[int]


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
    shared: bool = False  # may repeat another shared item's recipe today (see `shareable`)


@dataclass(frozen=True, slots=True)
class _Combo:
    """One way to fill a set of slots."""

    items: tuple[_Item, ...]
    recipes: frozenset[int]
    free: frozenset[int]  # the recipes of items that aren't shared
    kcal: int
    protein: int
    value: int


def _combos(options: Sequence[Sequence[_Item]]) -> list[_Combo]:
    """Every way to fill the slots, a recipe at most once a day unless only shared items hold
    it (two cells chosen as the same dish: leftovers)."""
    out: list[_Combo] = []
    for items in product(*options):
        ids = [i.recipe_id for i in items if i.recipe_id is not None]
        free = [i.recipe_id for i in items if i.recipe_id is not None and not i.shared]
        recipes = frozenset(ids)
        if len(free) == len(set(free)) and not (len(ids) > len(recipes) and _clash(items)):
            kcal = sum(i.kcal for i in items)
            protein = sum(i.protein for i in items)
            value = sum(i.value for i in items)
            out.append(_Combo(items, recipes, frozenset(free), kcal, protein, value))
    return out


def _clash(items: Sequence[_Item]) -> bool:
    """Whether an item that isn't shared has the recipe of a shared one."""
    shared = {i.recipe_id for i in items if i.shared}
    return any(i.recipe_id in shared for i in items if not i.shared)


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
            # Stable: within the familiar and the unusual, the `fitting` order stands.
            self.pool[spec.slot] = sorted(
                self.fitting(spec.slot, spec.candidates), key=lambda r: r.id in spec.unusual
            )
        self.ids = {slot: frozenset(r.id for r in rs) for slot, rs in self.pool.items()}
        # Chosen open cells -> the allowed recipes of the choice that fit the slot, ranked.
        self.chosen = {
            at: self.fitting(at[1], ids)
            for at, ids in sorted(problem.choices.items(), key=lambda kv: _at(kv[0]))
            if 0 <= at[0] < problem.days and problem.spec(at[1]) and at not in problem.locked
        }
        self.caps = {
            r.id: problem.repeat_cap(r)
            for rs in (*self.pool.values(), *self.chosen.values())
            for r in rs
        }
        self.locks = {
            at: meal
            for at, meal in problem.locked.items()
            if meal is not None and 0 <= at[0] < problem.days
        }
        self.uses: Counter[int] = Counter(m.recipe_id for m in self.locks.values())
        # Open cells that must hold a meal, by kind: a required slot's free cells, or chosen
        # cells with the same choice (its recipe ids).
        self.cells = [
            (day, kind)
            for day in range(problem.days)
            for spec in self.specs
            if (day, spec.slot) not in problem.locked
            and (kind := self.kind(day, spec.slot)) is not None
        ]
        self.meals: list[Meal] = list(self.locks.values())
        self.totals: list[Macros] = []
        self.notes: list[str] = []

    def safe(self, recipe: Recipe) -> bool:
        if recipe.id not in self.ok:
            self.ok[recipe.id] = allowed(recipe, self.p.foods, self.p.profile)
        return self.ok[recipe.id]

    def fitting(self, slot: Slot, ids: Sequence[int]) -> list[Recipe]:
        """The recipes among `ids` that pass the hard filters and fit `slot`, ranked."""
        recipes = (self.p.recipes.get(r) for r in dict.fromkeys(ids))
        return sorted(
            (r for r in recipes if r and slot in r.meal_types and self.safe(r)), key=_rank
        )

    def holds(self, day: int, slot: Slot) -> frozenset[int]:
        """The recipe ids an open cell may hold."""
        chosen = self.chosen.get((day, slot))
        return self.ids[slot] if chosen is None else frozenset(r.id for r in chosen)

    def kind(self, day: int, slot: Slot) -> _Kind | None:
        """What an open cell that must hold a meal draws on (None: an optional slot, which
        may stay empty)."""
        if (day, slot) in self.chosen:
            return self.holds(day, slot)
        spec = self.p.spec(slot)
        return slot if spec is not None and spec.required else None

    def day_name(self, day: int) -> str:
        return _WEEKDAYS[(self.p.start + timedelta(days=day)).weekday()]

    # --- the week --------------------------------------------------------------------------------

    def run(self) -> Plan | None:
        for (day, slot), meal in sorted(self.locks.items(), key=lambda kv: _at(kv[0])):
            recipe = self.p.recipes.get(meal.recipe_id)
            if recipe is None or not self.safe(recipe):
                self.notes.append(f"{self.day_name(day)} {slot}: the fixed meal isn't allowed")
                return None
        for (day, slot), fit in self.chosen.items():
            if not fit:
                ids = self.p.choices[(day, slot)]
                eligible = any(slot in r.meal_types for i in ids if (r := self.p.recipes.get(i)))
                why = "is allowed" if eligible else f"is a {slot} recipe"
                self.notes.append(f"{self.day_name(day)} {slot}: none of the chosen recipes {why}")
                return None
        if self.hall(-1, Counter()) is not None:
            self.notes.append("too few allowed recipes to fill every meal within the repeat limits")
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
            short = self.hall(day, used)
            if short is None:
                break
            # Meals using up `short` in cells that could have held something else.
            culprits = {
                (i.slot, i.recipe_id)
                for i in chosen
                if i.recipe_id in short and not self.holds(day, i.slot) <= short
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

    def hall(self, day: int, used: Counter[int]) -> frozenset[int] | None:
        """None if the open cells after `day` can still all be filled within the repeat caps,
        counting `used` on top of the plan so far; else the recipes they are short of."""
        need = Counter(kind for d, kind in self.cells if d > day)
        demand = [(n, self.ids[k] if isinstance(k, Slot) else k) for k, n in need.items()]
        room = {r: max(0, cap - self.uses[r] - used[r]) for r, cap in self.caps.items()}
        return _shortfall(demand, room)

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
        shareable = self.shareable(day)
        for spec in self.specs:
            if (day, spec.slot) in self.p.locked:
                continue
            items = self.options(spec, day, excluded, shareable)
            if not items:
                what = "chosen recipe" if (day, spec.slot) in self.chosen else spec.slot
                return None, f"{name}: no {what} left within the repeat limits"
            options.append(items)
        fixed = self.fixed(day)
        today = _Day(fixed, self.protein_target(day))
        left_ix, right_ix = _split(options)
        left = _combos([options[i] for i in left_ix])
        right = _combos([options[i] for i in right_ix])
        sides = _Sides(right, self.protein_weight)

        band, floor = self.kcal_rule(day)
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
            if floor <= -_FAR:  # nothing to reach: no combination at all
                return None, f"{name}: no combination of the meals left fits the day"
            what = "minimum for the day" if day in self.p.day_kcal else "floor"
            return None, f"{name}: no meals that fit reach the {floor:,} kcal {what}"
        total = fixed.kcal + sum(i.kcal for i in best)
        return best, f"{name}: the kcal band was out of reach ({total:,} kcal)"

    def kcal_rule(self, day: int) -> tuple[Band, int]:
        """The day's kcal band and floor: the targets', or a `day_kcal` band whose min is
        also the floor (an open min: none)."""
        override = self.p.day_kcal.get(day)
        if override is None:
            return self.p.targets.daily.get(Nutrient.KCAL, Band()), self.p.targets.calorie_floor
        return override, -_FAR if override.min is None else override.min

    def shareable(self, day: int) -> frozenset[int]:
        """Recipes that may fill several chosen cells today (leftovers): those whose repeat
        cap still has room for every chosen cell today that may hold them."""
        cells = Counter(r.id for (d, _), rs in self.chosen.items() if d == day for r in rs)
        return frozenset(r for r, n in cells.items() if self.caps[r] - self.uses[r] >= n)

    def options(
        self,
        spec: SlotSpec,
        day: int,
        excluded: set[tuple[Slot, int]],
        shareable: frozenset[int] = frozenset(),
    ) -> list[_Item]:
        """Ways to fill (day, spec.slot); [] if a meal is needed and none is left."""
        w = self.p.weights
        before = None if self.previous is None else self.previous.get((day, spec.slot))
        choice = self.chosen.get((day, spec.slot))
        required = spec.required or choice is not None
        limit = TOP if required else TOP_OPTIONAL
        lo, hi = self.p.portion_range(spec.slot)
        band = spec.kcal

        def too_far(r: Recipe) -> bool:
            kcal = r.per_portion.kcal
            return band is not None and all(not band.contains(kcal * n) for n in range(lo, hi + 1))

        # Among equally liked recipes, those that can make a meal the right size get the places:
        # the rest could only be chosen at a cost. Stable, so the ranking otherwise stands.
        eligible = sorted(
            (
                r
                for r in (self.pool[spec.slot] if choice is None else choice)
                if (spec.slot, r.id) not in excluded and self.uses[r.id] < self.caps[r.id]
            ),
            key=lambda r: (r.id in spec.unusual, -r.preference, too_far(r)),
        )
        # A day with its own kcal band (a replan) may need the lightest or heaviest meal to
        # land in it: that band is clipped to what they reach, which the top few may not.
        edges: set[int] = set()
        if day in self.p.day_kcal and eligible:
            kcal = [r.per_portion.kcal for r in eligible]
            edges = {eligible[kcal.index(min(kcal))].id, eligible[kcal.index(max(kcal))].id}
        picked: list[Recipe] = []
        for r in eligible:
            if len(picked) < limit or r.id == before or r.id in edges:
                picked.append(r)
        items: list[_Item] = []
        if not required:
            kept = self.previous is not None and before is None
            items.append(_Item(spec.slot, None, 0, 0, 0, w.churn if kept else 0))
        for r in picked:
            value = w.preference * r.preference
            value -= w.repeat if self.uses[r.id] else 0
            value -= 0 if spec.required else w.optional_meal
            value -= w.unusual if r.id in spec.unusual else 0
            value += w.churn if r.id == before else 0
            cost = w.cost * self.cost(r)
            for n in range(lo, hi + 1):
                kcal, protein = r.per_portion.kcal * n, r.per_portion.protein_g * n
                shared = choice is not None and r.id in shareable
                off = w.balance * band.distance(kcal) if band is not None else 0
                items.append(
                    _Item(spec.slot, r.id, n, kcal, protein, value - cost * n - off, shared)
                )
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
            side = sides.without(combo)
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
            side = sides.without(combo)
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
    (built on demand: with lunch and dinner on one side they are rare). Only shared items may
    have the same recipe across the halves."""

    def __init__(self, combos: list[_Combo], protein_weight: int) -> None:
        self.combos = combos
        self.weight = protein_weight
        self.recipes = frozenset[int]().union(*(c.recipes for c in combos))
        self.full = _Side(combos, protein_weight)
        self.cache: dict[tuple[frozenset[int], frozenset[int]], _Side] = {}

    def without(self, first: _Combo) -> _Side:
        key = (first.recipes & self.recipes, first.free & self.recipes)
        if not key[0]:
            return self.full
        if key not in self.cache:
            used, free = key
            kept = [c for c in self.combos if not (c.recipes & free or c.free & used)]
            self.cache[key] = _Side(kept, self.weight)
        return self.cache[key]


def _shortfall(
    demand: Sequence[tuple[int, frozenset[int]]], room: Mapping[int, int]
) -> frozenset[int] | None:
    """Whether `demand` (cells needed, the recipes each may hold) fits in `room` (meals left per
    recipe): None if it does, else the recipes reachable in the residual graph of a maximum
    flow. Those are the neighbourhood of a set of cells that violates Hall's condition: every
    such recipe is used up, and only a cell that could hold something else can free one.

    Unit augmenting paths, breadth first from every cell kind still short: at most one search
    per needed meal (a few dozen), each over a few hundred edges."""
    pools = [sorted(pool) for _, pool in demand]
    supplied = [0] * len(demand)
    flow: dict[int, Counter[int]] = {}  # recipe -> units per kind
    while True:
        short = [k for k, (n, _) in enumerate(demand) if supplied[k] < n]
        if not short:
            return None
        via: dict[int, int] = {}  # recipe -> the kind it was reached from
        back: dict[int, int] = {}  # kind -> the recipe whose flow it gives up (path interior)
        queue, seen, end = deque(short), set(short), None
        while queue and end is None:
            kind = queue.popleft()
            for r in pools[kind]:
                if r in via:
                    continue
                via[r] = kind
                if sum(flow.get(r, Counter()).values()) < room.get(r, 0):
                    end = r
                    break
                for other in flow.get(r, Counter()):
                    if other not in seen and flow[r][other] > 0:
                        seen.add(other)
                        back[other] = r
                        queue.append(other)
        if end is None:
            return frozenset(via)
        kind = via[end]
        flow.setdefault(end, Counter())[kind] += 1
        while kind in back:
            given = back[kind]
            flow[given][kind] -= 1
            kind = via[given]
            flow[given][kind] += 1
        supplied[kind] += 1


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

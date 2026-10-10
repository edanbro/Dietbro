"""Why there is no plan, in the user's words: `diagnose(problem) -> list[str]`.

The API shows these messages when a planner finds no plan (INFEASIBLE), or refuses one below the
calorie floor. Every check is a *sound necessary condition*: if `diagnose` reports something, no
plan made of the problem's candidates meets the hard rules, whichever planner looks for it. The
converse doesn't hold: [] doesn't prove that a plan exists, because each check looks at one rule
on its own (kcal ignores repeat caps, the budget ignores the daily kcal maximum, and so on).

Only what a planner may use counts: per slot, the candidates that pass the hard filters
(`candidates.allowed`) and fit the slot, plus locked meals and food eaten off-plan. Checks:

1. a locked meal that breaks a hard filter (locks never skip them);
2. a required slot with no candidate left;
3. repeat capacity, per group of required slots (each slot alone, and slots that share recipes,
   such as lunch and dinner, pooled): the meals the group's candidates can still provide within
   their repeat caps, after locked meals, against the group's open meals. By Hall's theorem
   these groups are exactly what decides whether the caps alone allow a plan;
4. per day, the kcal reach (off-plan intake, locked meals, each open required slot between its
   lightest candidate at the fewest portions and its heaviest at the most, optional slots from
   nothing up to their heaviest) against the daily kcal band and the calorie floor;
5. the weekly kcal band against the sum of the days' reach, each day already clipped to its band;
6. a lower bound on shopping cost against the budget: per day, the cheapest way for the open
   slots to supply the kcal the day still needs, where a slot costs at least its cheapest meal
   and at least its cheapest cost per kcal times the kcal it supplies (a fractional knapsack);
   over the week, at least the weekly kcal minimum at the cheapest kcal; plus locked meals,
   minus everything in the pantry.

It imports the prefilter's `allowed`, never the validator (which re-implements the hard filters
on purpose) or a planner.
"""

import math
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import timedelta
from fractions import Fraction
from itertools import combinations

from larder_solver.candidates import allowed
from larder_solver.metrics import to_minor
from larder_solver.problem import (
    SLOT_ORDER,
    Band,
    Macros,
    Meal,
    Nutrient,
    Problem,
    Recipe,
    Slot,
)

_SINGULAR = {
    Slot.BREAKFAST: "breakfast",
    Slot.LUNCH: "lunch",
    Slot.DINNER: "dinner",
    Slot.SNACK: "snack",
}
_PLURAL = {
    Slot.BREAKFAST: "breakfasts",
    Slot.LUNCH: "lunches",
    Slot.DINNER: "dinners",
    Slot.SNACK: "snacks",
}
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def diagnose(problem: Problem) -> list[str]:
    """Reasons no plan can meet the hard rules ([] = none found; see the module docstring)."""
    return list(_Diagnosis(problem).run())


@dataclass(frozen=True, slots=True)
class _Reach:
    """A day's kcal: fixed (off-plan + locked) and the reachable total range."""

    fixed: int
    low: int
    high: int
    extra: int
    locked: bool


class _Diagnosis:
    def __init__(self, problem: Problem) -> None:
        self.p = problem
        self.specs = sorted(problem.slots, key=lambda s: SLOT_ORDER.index(s.slot))
        self.ok: dict[int, bool] = {}
        self.costs: dict[int, int] = {}
        # slot -> allowed candidates that fit it, each recipe once, in candidate order
        self.pool: dict[Slot, list[Recipe]] = {}
        for spec in self.specs:
            recipes = (problem.recipes.get(rid) for rid in dict.fromkeys(spec.candidates))
            self.pool[spec.slot] = [
                r for r in recipes if r is not None and spec.slot in r.meal_types and self.safe(r)
            ]
        self.locks = [
            m
            for (day, _), m in sorted(problem.locked.items(), key=lambda kv: _key(kv[0]))
            if m is not None and 0 <= day < problem.days
        ]
        self.locked_uses = Counter(m.recipe_id for m in self.locks)
        self.empty = [
            s.slot
            for s in self.specs
            if s.required and self.open_days(s.slot) and not self.pool[s.slot]
        ]

    def safe(self, recipe: Recipe) -> bool:
        if recipe.id not in self.ok:
            self.ok[recipe.id] = allowed(recipe, self.p.foods, self.p.profile)
        return self.ok[recipe.id]

    def open_days(self, slot: Slot) -> list[int]:
        return [d for d in range(self.p.days) if (d, slot) not in self.p.locked]

    def run(self) -> Iterator[str]:
        yield from self.unsafe_locks()
        yield from self.no_candidates()
        yield from self.capacity()
        if self.empty:
            return  # the kcal and cost checks need a candidate in every open required slot
        band = self.p.targets.daily.get(Nutrient.KCAL, Band())
        floor = self.p.targets.calorie_floor
        if band.max is not None and band.max < floor:
            yield f"Your daily maximum of {band.max:,} kcal is below your {floor:,} kcal floor"
            return
        reach = [self.reach(day) for day in range(self.p.days)]
        daily = self.daily_kcal(reach, band)
        yield from daily
        if not daily:  # the weekly and cost checks assume every day can meet its band
            yield from self.weekly_kcal(reach, band)
            yield from self.budget(reach, band)

    # --- 1, 2: locks and empty slots -------------------------------------------------------------

    def unsafe_locks(self) -> Iterator[str]:
        for meal in self.locks:
            recipe = self.p.recipes.get(meal.recipe_id)
            if recipe is None or self.safe(recipe):
                continue
            what = f"Your fixed {self.day_name(meal.day)} {meal.slot}, {recipe.name},"
            if any(i.food_id not in self.p.foods for i in recipe.ingredients):
                yield f"{what} uses an ingredient we have no data for"
            else:
                yield f"{what} doesn't fit your {self.restrictions()}"

    def no_candidates(self) -> Iterator[str]:
        for slot in self.empty:
            if self.p.profile.restricted:
                yield f"No {_SINGULAR[slot]} fits your {self.restrictions()}"
            else:
                yield f"No {_SINGULAR[slot]} recipe is available"

    # --- 3: repeat capacity ----------------------------------------------------------------------

    def capacity(self) -> Iterator[str]:
        required = [s.slot for s in self.specs if s.required and self.open_days(s.slot)]
        failed: list[frozenset[Slot]] = [frozenset({s}) for s in self.empty]
        for size in range(1, len(required) + 1):
            for group in map(frozenset, combinations(required, size)):
                if any(f <= group for f in failed):
                    continue  # already explained by a smaller group
                message = self.group_capacity(group)
                if message is not None:
                    failed.append(group)
                    yield message

    def group_capacity(self, group: frozenset[Slot]) -> str | None:
        slots = [s for s in SLOT_ORDER if s in group]
        pool = {r.id: r for s in slots for r in self.pool[s]}
        caps = {rid: self.p.repeat_cap(r) for rid, r in pool.items()}
        room = sum(max(0, caps[rid] - self.locked_uses[rid]) for rid in pool)
        need = sum(len(self.open_days(s)) for s in slots)
        if room >= need:
            return None
        n = len(pool)
        head = f"Only {n} {_meals(slots, n)} {self.fit(n)}"
        low, top = min(caps.values()), max(caps.values())
        times = _times(low, top)
        locks = any(self.locked_uses[rid] for rid in pool) or any(
            (d, s) in self.p.locked for d in range(self.p.days) for s in slots
        )
        if locks or low != top:
            left = "left to plan" if locks else "to plan"
            return f"{head}, enough for {room} of the {need} {_meals(slots, need)} {left} ({times})"
        if self.p.days == 1:
            period = "a day needs"
        elif self.p.days == 7:
            period = "a week needs"
        else:
            period = f"{self.p.days} days need"
        return f"{head}; {period} at least {-(-need // top)} ({times})"

    # --- 4, 5: kcal ------------------------------------------------------------------------------

    def reach(self, day: int) -> _Reach:
        extra = self.p.extra.get(day, Macros()).kcal
        today = [m for m in self.locks if m.day == day]
        fixed = extra + sum(_kcal(self.p, m) for m in today)
        low = high = 0
        for spec in self.specs:
            if (day, spec.slot) in self.p.locked:
                continue
            kcal = [r.per_portion.kcal for r in self.pool[spec.slot]]
            if not kcal:
                continue  # an empty optional slot (empty required ones stop earlier)
            lo, hi = self.p.portion_range(spec.slot)
            if spec.required:
                low += min(kcal) * lo
            high += max(kcal) * hi
        return _Reach(fixed, fixed + low, fixed + high, extra, bool(today))

    def daily_kcal(self, reach: list[_Reach], band: Band) -> list[str]:
        floor = self.p.targets.calorie_floor
        least, word = (
            (floor, "floor") if band.min is None or band.min <= floor else (band.min, "minimum")
        )
        tails: dict[str, list[int]] = {}
        for day, r in enumerate(reach):
            if r.high < least:
                tail = f"even the largest meals that fit reach only {r.high:,} kcal{_with(r)}"
                tail += f", below your {least:,} kcal {word}"
            elif band.max is not None and r.low > band.max:
                tail = f"even the smallest meals that fit come to {r.low:,} kcal{_with(r)}"
                tail += f", above your {band.max:,} kcal maximum"
            else:
                continue
            tails.setdefault(tail, []).append(day)
        return [f"{self.days_label(days)}: {tail}" for tail, days in tails.items()]

    def weekly_kcal(self, reach: list[_Reach], band: Band) -> Iterator[str]:
        week = self.p.targets.weekly.get(Nutrient.KCAL)
        if week is None:
            return
        least = max(self.p.targets.calorie_floor, band.min or 0)
        most = sum(r.high if band.max is None else min(r.high, band.max) for r in reach)
        fewest = sum(max(r.low, least) for r in reach)
        label = "This week" if self.p.days == 7 else "Over the whole plan"
        if week.min is not None and most < week.min:
            yield (
                f"{label}: even the largest meals that fit reach only {most:,} kcal, "
                f"below your {week.min:,} kcal weekly minimum"
            )
        elif week.max is not None and fewest > week.max:
            yield (
                f"{label}: even the smallest meals that fit come to {fewest:,} kcal, "
                f"above your {week.max:,} kcal weekly maximum"
            )

    # --- 6: budget -------------------------------------------------------------------------------

    def budget(self, reach: list[_Reach], band: Band) -> Iterator[str]:
        if self.p.budget is None:
            return
        least = max(self.p.targets.calorie_floor, band.min or 0)
        open_meals = sum(
            (self.day_cost(day, max(0, least - r.fixed)) for day, r in enumerate(reach)),
            Fraction(0),
        )
        # The week's open meals must also supply what the weekly minimum still needs, at no
        # less than the cheapest kcal any candidate offers.
        week = self.p.targets.weekly.get(Nutrient.KCAL)
        ratios = [ratio for spec in self.specs if (ratio := self.ratio(spec.slot)) is not None]
        if ratios and week is not None and week.min is not None:
            needed = max(0, week.min - sum(r.fixed for r in reach))
            open_meals = max(open_meals, min(ratios) * needed)
        locked = sum(
            self.cost(self.p.recipes[m.recipe_id]) * m.portions
            for m in self.locks
            if m.recipe_id in self.p.recipes
        )
        pantry = sum(
            lot.grams * self.p.foods[lot.food_id].price_per_kg
            for lot in self.p.pantry
            if lot.food_id in self.p.foods
            and (lot.expires is None or lot.expires >= 0)
            and lot.grams > 0
        )
        least_cost = math.ceil(open_meals) + locked - pantry
        if least_cost > self.p.budget * 1000:
            after = " after using your pantry" if pantry else ""
            yield (
                f"Even the cheapest meals that fit would cost at least "
                f"{_money(to_minor(least_cost))}{after}, over your {_money(self.p.budget)} budget"
            )

    def day_cost(self, day: int, kcal: int) -> Fraction:
        """A lower bound on what a day's open slots cost (every ingredient bought) when they
        must supply at least `kcal`.

        A meal in slot s that supplies k kcal costs at least g_s(k) = max(m_s, rho_s * k), where
        m_s is the slot's cheapest meal at its fewest portions (0 for an optional slot, which may
        stay empty) and rho_s its cheapest cost per kcal; k lies between the slot's lightest and
        heaviest meal. Each g_s is convex and nondecreasing, so the cheapest way to supply `kcal`
        is: every slot at its lightest, then the remaining kcal from the cheapest increments
        (a fractional knapsack)."""
        base = Fraction(0)
        supplied = 0
        increments: list[tuple[Fraction, Fraction]] = []  # (cost per kcal, kcal available)
        for spec in self.specs:
            pool = self.pool[spec.slot]
            if (day, spec.slot) in self.p.locked or not pool:
                continue
            lo, hi = self.p.portion_range(spec.slot)
            fixed = min(self.cost(r) for r in pool) * lo if spec.required else 0
            first = min(r.per_portion.kcal for r in pool) * lo if spec.required else 0
            most = max(r.per_portion.kcal for r in pool) * hi
            rho = self.ratio(spec.slot)
            if rho is None:  # no candidate supplies kcal
                base += fixed
                continue
            base += max(Fraction(fixed), rho * first)
            supplied += first
            free_up_to = Fraction(most) if rho == 0 else min(Fraction(most), fixed / rho)
            increments.append((Fraction(0), max(Fraction(0), free_up_to - first)))
            increments.append((rho, max(Fraction(0), most - max(Fraction(first), free_up_to))))
        missing = Fraction(max(0, kcal - supplied))
        for rho, available in sorted(increments):
            take = min(missing, available)
            base += rho * take
            missing -= take
        return base

    def ratio(self, slot: Slot) -> Fraction | None:
        """The cheapest cost per kcal among the slot's candidates (None: none supplies kcal)."""
        return min(
            (
                Fraction(self.cost(r), r.per_portion.kcal)
                for r in self.pool[slot]
                if r.per_portion.kcal > 0
            ),
            default=None,
        )

    def cost(self, recipe: Recipe) -> int:
        """Millipence per portion, every weighed ingredient bought."""
        if recipe.id not in self.costs:
            self.costs[recipe.id] = sum(
                i.grams * self.p.foods[i.food_id].price_per_kg
                for i in recipe.ingredients
                if i.food_id in self.p.foods
            )
        return self.costs[recipe.id]

    # --- wording ---------------------------------------------------------------------------------

    def restrictions(self) -> str:
        p = self.p.profile
        parts = [
            word
            for word, on in (
                ("allergies", p.allergens),
                ("diet", p.diet),
                ("avoided foods", p.avoid_food_ids),
            )
            if on
        ]
        return _join(parts) if parts else "settings"

    def fit(self, n: int) -> str:
        if self.p.profile.restricted:
            return f"{'fits' if n == 1 else 'fit'} your {self.restrictions()}"
        return "is available" if n == 1 else "are available"

    def day_name(self, day: int) -> str:
        d = self.p.start + timedelta(days=day)
        name = _WEEKDAYS[d.weekday()]
        return name if self.p.days <= 7 else f"{name} {d.day} {_MONTHS[d.month - 1]}"

    def days_label(self, days: list[int]) -> str:
        if len(days) == self.p.days > 1:
            return "Every day"
        return _join([self.day_name(d) for d in days])


def _key(at: tuple[int, Slot]) -> tuple[int, int]:
    day, slot = at
    return day, SLOT_ORDER.index(slot) if slot in SLOT_ORDER else len(SLOT_ORDER)


def _kcal(problem: Problem, meal: Meal) -> int:
    if meal.recipe_id not in problem.recipes:
        return 0
    return problem.recipes[meal.recipe_id].per_portion.kcal * meal.portions


def _with(reach: _Reach) -> str:
    parts = ["your fixed meals"] if reach.locked else []
    if reach.extra:
        parts.append(f"{reach.extra:,} kcal eaten off-plan")
    return f" (with {_join(parts)})" if parts else ""


def _times(low: int, high: int) -> str:
    def word(n: int) -> str:
        return {1: "once", 2: "twice"}.get(n, f"{n} times")

    if low == high:
        return f"each at most {word(high)}"
    return f"each at most {low} to {high} times"


def _join(words: Iterable[str], conjunction: str = "and") -> str:
    items = list(words)
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} {conjunction} {items[-1]}"


def _meals(slots: Sequence[Slot], n: int) -> str:
    """'breakfast' or 'breakfasts'; 'lunch or dinner' or 'lunches and dinners'."""
    if n == 1:
        return _join((_SINGULAR[s] for s in slots), "or")
    return _join(_PLURAL[s] for s in slots)


def _money(minor: int) -> str:
    return f"{minor // 100:,}.{minor % 100:02d}"

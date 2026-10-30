"""Why there is no plan, in the user's words: `diagnose(problem) -> list[str]`.

The API shows these messages when a planner finds no plan (INFEASIBLE), or refuses one below the
calorie floor. Every check is a *sound necessary condition*: if `diagnose` reports something, no
plan made of the problem's candidates meets the hard rules, whichever planner looks for it. The
converse doesn't hold: [] doesn't prove that a plan exists, because each check looks at one rule
on its own (kcal ignores repeat caps, the budget ignores the daily kcal maximum, and so on).

Only what a planner may use counts: per slot, the candidates that pass the hard filters
(`candidates.allowed`) and fit the slot, plus locked meals and food eaten off-plan. A chosen cell
(`Problem.choices`) draws on its choice instead (the recipes in it that pass and fit, candidates
of the slot or not) and must hold a meal even in an optional slot. A day's kcal rule is the daily
kcal band and the floor, or on a day with a `Problem.day_kcal` band, that band alone. Checks:

1. a locked meal that breaks a hard filter (locks never skip them);
2. a required slot with no candidate left, and a chosen cell none of whose recipes is allowed
   and fits the slot;
3. repeat capacity, per group of required slots (each slot alone, and slots that share recipes,
   such as lunch and dinner, pooled): the meals the group's candidates can still provide within
   their repeat caps, after locked meals, against the group's open meals (their free cells, and
   their chosen cells that can only use the group's candidates). By Hall's theorem these groups
   are exactly what decides whether the caps alone allow a plan without choices. Then the same
   per choice: the chosen cells that can only use its recipes against what they can provide;
4. per day, the kcal reach (off-plan intake, locked meals, each open required or chosen cell
   between its lightest option at the fewest portions and its heaviest at the most, optional
   slots from nothing up to their heaviest) against the day's kcal rule;
5. the weekly kcal band against the sum of the days' reach, each day already clipped to its rule;
6. a lower bound on shopping cost against the budget: per day, the cheapest way for the open
   cells to supply the kcal the day still needs, where a cell costs at least its cheapest meal
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
    SlotSpec,
)

_SINGULAR = {
    Slot.BREAKFAST: "breakfast",
    Slot.LUNCH: "lunch",
    Slot.DINNER: "dinner",
    Slot.MORNING_SNACK: "morning snack",
    Slot.SNACK: "snack",
    Slot.EVENING_SNACK: "evening snack",
}
_PLURAL = {
    Slot.BREAKFAST: "breakfasts",
    Slot.LUNCH: "lunches",
    Slot.DINNER: "dinners",
    Slot.MORNING_SNACK: "morning snacks",
    Slot.SNACK: "snacks",
    Slot.EVENING_SNACK: "evening snacks",
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


@dataclass(frozen=True, slots=True)
class _Rule:
    """A day's kcal rule: at least `least` and at most `most` (None: no bound), and how the
    messages name the two bounds."""

    least: int | None
    most: int | None
    below: str  # "your 1,200 kcal floor"
    above: str  # "your 2,500 kcal maximum"


class _Diagnosis:
    def __init__(self, problem: Problem) -> None:
        self.p = problem
        self.specs = sorted(problem.slots, key=lambda s: SLOT_ORDER.index(s.slot))
        self.ok: dict[int, bool] = {}
        self.costs: dict[int, int] = {}
        # slot -> allowed candidates that fit it, each recipe once, in candidate order
        self.pool = {spec.slot: self.fitting(spec.slot, spec.candidates) for spec in self.specs}
        # open chosen cell -> the allowed recipes of its choice that fit the slot, in order
        self.chosen = {
            at: self.fitting(at[1], ids)
            for at, ids in sorted(problem.choices.items(), key=lambda kv: _key(kv[0]))
            if 0 <= at[0] < problem.days and problem.spec(at[1]) and at not in problem.locked
        }
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
        self.unusable = [at for at, pool in self.chosen.items() if not pool]

    def safe(self, recipe: Recipe) -> bool:
        if recipe.id not in self.ok:
            self.ok[recipe.id] = allowed(recipe, self.p.foods, self.p.profile)
        return self.ok[recipe.id]

    def fitting(self, slot: Slot, ids: Iterable[int]) -> list[Recipe]:
        recipes = (self.p.recipes.get(rid) for rid in dict.fromkeys(ids))
        return [r for r in recipes if r is not None and slot in r.meal_types and self.safe(r)]

    def open_days(self, slot: Slot) -> list[int]:
        """Days whose `slot` draws on the slot's candidates: not locked, not chosen."""
        return [
            d
            for d in range(self.p.days)
            if (d, slot) not in self.p.locked and (d, slot) not in self.chosen
        ]

    def cell(self, day: int, spec: SlotSpec) -> tuple[list[Recipe], bool] | None:
        """What an open cell may hold and whether it must hold something (None: locked)."""
        if (day, spec.slot) in self.p.locked:
            return None
        if (day, spec.slot) in self.chosen:
            return self.chosen[(day, spec.slot)], True
        return self.pool[spec.slot], spec.required

    def rule(self, day: int) -> _Rule:
        override = self.p.day_kcal.get(day)
        if override is not None:
            low, high = override.min, override.max
            return _Rule(
                low,
                high,
                f"the {low or 0:,} kcal minimum for that day",
                f"the {high or 0:,} kcal maximum for that day",
            )
        band = self.p.targets.daily.get(Nutrient.KCAL, Band())
        floor = self.p.targets.calorie_floor
        least, word = (
            (floor, "floor") if band.min is None or band.min <= floor else (band.min, "minimum")
        )
        return _Rule(
            least, band.max, f"your {least:,} kcal {word}", f"your {band.max or 0:,} kcal maximum"
        )

    def run(self) -> Iterator[str]:
        yield from self.unsafe_locks()
        yield from self.no_candidates()
        yield from self.unusable_choices()
        yield from self.capacity()
        yield from self.choice_capacity()
        if self.empty or self.unusable:
            return  # the kcal and cost checks need an option in every cell that needs a meal
        band = self.p.targets.daily.get(Nutrient.KCAL, Band())
        floor = self.p.targets.calorie_floor
        usual = any(d not in self.p.day_kcal for d in range(self.p.days))
        if usual and band.max is not None and band.max < floor:
            yield f"Your daily maximum of {band.max:,} kcal is below your {floor:,} kcal floor"
            return
        reach = [self.reach(day) for day in range(self.p.days)]
        rules = [self.rule(day) for day in range(self.p.days)]
        daily = self.daily_kcal(reach, rules)
        yield from daily
        if not daily:  # the weekly and cost checks assume every day can meet its rule
            yield from self.weekly_kcal(reach, rules)
            yield from self.budget(reach, rules)

    # --- 1, 2: locks, empty slots and unusable choices -------------------------------------------

    def unsafe_locks(self) -> Iterator[str]:
        for meal in self.locks:
            recipe = self.p.recipes.get(meal.recipe_id)
            if recipe is None or self.safe(recipe):
                continue
            what = f"Your fixed {self.day_name(meal.day)} {meal.slot}, {recipe.name},"
            yield f"{what} {self.unsafe(recipe)}"

    def no_candidates(self) -> Iterator[str]:
        for slot in self.empty:
            if self.p.profile.restricted:
                yield f"No {_SINGULAR[slot]} fits your {self.restrictions()}"
            else:
                yield f"No {_SINGULAR[slot]} recipe is available"

    def unusable_choices(self) -> Iterator[str]:
        for day, slot in self.unusable:
            where = f"{self.day_name(day)} {_SINGULAR[slot]}"
            ids = dict.fromkeys(self.p.choices[(day, slot)])
            recipes = [r for rid in ids if (r := self.p.recipes.get(rid)) is not None]
            if len(recipes) == 1:
                recipe = recipes[0]
                if slot not in recipe.meal_types:
                    why = f"isn't a {_SINGULAR[slot]} recipe"
                else:
                    why = self.unsafe(recipe)
                yield f"Your choice for {where}, {recipe.name}, {why}"
                continue
            eligible = sum(slot in r.meal_types for r in recipes)
            kind, fits = f"is a {_SINGULAR[slot]} recipe", f"fits your {self.restrictions()}"
            if not eligible:
                why = kind
            elif eligible == len(recipes):
                why = fits
            else:
                why = f"{kind} that {fits}"
            yield f"None of your choices for {where} {why}"

    def unsafe(self, recipe: Recipe) -> str:
        """Why an eligible recipe isn't allowed, as the end of a sentence."""
        if any(i.food_id not in self.p.foods for i in recipe.ingredients):
            return "uses an ingredient we have no data for"
        return f"doesn't fit your {self.restrictions()}"

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
        # Chosen cells of the group's slots that can only use its candidates need them too.
        chosen = sum(
            at[1] in group and bool(rs) and all(r.id in pool for r in rs)
            for at, rs in self.chosen.items()
        )
        need = sum(len(self.open_days(s)) for s in slots) + chosen
        if room >= need:
            return None
        n = len(pool)
        head = f"Only {n} {_meals(slots, n)} {self.fit(n)}"
        low, top = min(caps.values()), max(caps.values())
        times = _times(low, top)
        locks = any(self.locked_uses[rid] for rid in pool) or any(
            (d, s) in self.p.locked or (d, s) in self.chosen
            for d in range(self.p.days)
            for s in slots
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

    def choice_capacity(self) -> Iterator[str]:
        """Per choice (smallest first): the chosen cells that can only use its recipes."""
        pools = sorted(
            {frozenset(r.id for r in rs) for rs in self.chosen.values() if rs},
            key=lambda p: (len(p), sorted(p)),
        )
        failed: list[frozenset[int]] = []
        for pool in pools:
            if any(f <= pool for f in failed):
                continue
            cells = [at for at, rs in self.chosen.items() if rs and {r.id for r in rs} <= pool]
            caps = {rid: self.p.repeat_cap(self.p.recipes[rid]) for rid in pool}
            room = sum(max(0, caps[rid] - self.locked_uses[rid]) for rid in pool)
            if room >= len(cells):
                continue
            failed.append(pool)
            where = self.cells_label(cells)
            if len(pool) == 1:
                (rid,) = pool
                head = f"{self.p.recipes[rid].name} is chosen for {where}"
                if room == 0:
                    yield f"{head}, but your fixed meals already have it {_word(caps[rid])}"
                else:
                    more = " more" if self.locked_uses[rid] else ""
                    yield f"{head}, but can be planned only {_word(room)}{more}"
            else:
                times = _times(min(caps.values()), max(caps.values()))
                yield (
                    f"Your choices for {where} can fill only {room} of those {len(cells)} meals "
                    f"({times})"
                )

    # --- 4, 5: kcal ------------------------------------------------------------------------------

    def reach(self, day: int) -> _Reach:
        extra = self.p.extra.get(day, Macros()).kcal
        today = [m for m in self.locks if m.day == day]
        fixed = extra + sum(_kcal(self.p, m) for m in today)
        low = high = 0
        for spec in self.specs:
            cell = self.cell(day, spec)
            if cell is None or not cell[0]:
                continue  # locked, or an empty optional slot (empty required ones stop earlier)
            pool, required = cell
            kcal = [r.per_portion.kcal for r in pool]
            lo, hi = self.p.portion_range(spec.slot)
            if required:
                low += min(kcal) * lo
            high += max(kcal) * hi
        return _Reach(fixed, fixed + low, fixed + high, extra, bool(today))

    def daily_kcal(self, reach: list[_Reach], rules: list[_Rule]) -> list[str]:
        tails: dict[str, list[int]] = {}
        for day, (r, rule) in enumerate(zip(reach, rules, strict=True)):
            if rule.least is not None and r.high < rule.least:
                tail = f"even the largest meals that fit reach only {r.high:,} kcal{_with(r)}"
                tail += f", below {rule.below}"
            elif rule.most is not None and r.low > rule.most:
                tail = f"even the smallest meals that fit come to {r.low:,} kcal{_with(r)}"
                tail += f", above {rule.above}"
            else:
                continue
            tails.setdefault(tail, []).append(day)
        return [f"{self.days_label(days)}: {tail}" for tail, days in tails.items()]

    def weekly_kcal(self, reach: list[_Reach], rules: list[_Rule]) -> Iterator[str]:
        week = self.p.targets.weekly.get(Nutrient.KCAL)
        if week is None:
            return
        pairs = list(zip(reach, rules, strict=True))
        most = sum(r.high if u.most is None else min(r.high, u.most) for r, u in pairs)
        fewest = sum(r.low if u.least is None else max(r.low, u.least) for r, u in pairs)
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

    def budget(self, reach: list[_Reach], rules: list[_Rule]) -> Iterator[str]:
        if self.p.budget is None:
            return
        open_meals = sum(
            (
                self.day_cost(day, max(0, (rule.least or 0) - r.fixed))
                for day, (r, rule) in enumerate(zip(reach, rules, strict=True))
            ),
            Fraction(0),
        )
        # The week's open meals must also supply what the weekly minimum still needs, at no
        # less than the cheapest kcal any candidate (or chosen recipe) offers.
        week = self.p.targets.weekly.get(Nutrient.KCAL)
        pools = [*self.pool.values(), *self.chosen.values()]
        ratios = [ratio for pool in pools if (ratio := self.ratio(pool)) is not None]
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
        """A lower bound on what a day's open cells cost (every ingredient bought) when they
        must supply at least `kcal`.

        A meal in cell c that supplies k kcal costs at least g_c(k) = max(m_c, rho_c * k), where
        m_c is the cell's cheapest meal at its fewest portions (0 for an optional slot, which may
        stay empty) and rho_c its cheapest cost per kcal; k lies between the cell's lightest and
        heaviest meal. Each g_c is convex and nondecreasing, so the cheapest way to supply `kcal`
        is: every cell at its lightest, then the remaining kcal from the cheapest increments
        (a fractional knapsack)."""
        base = Fraction(0)
        supplied = 0
        increments: list[tuple[Fraction, Fraction]] = []  # (cost per kcal, kcal available)
        for spec in self.specs:
            cell = self.cell(day, spec)
            if cell is None or not cell[0]:
                continue
            pool, required = cell
            lo, hi = self.p.portion_range(spec.slot)
            fixed = min(self.cost(r) for r in pool) * lo if required else 0
            first = min(r.per_portion.kcal for r in pool) * lo if required else 0
            most = max(r.per_portion.kcal for r in pool) * hi
            rho = self.ratio(pool)
            if rho is None:  # no option supplies kcal
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

    def ratio(self, pool: Sequence[Recipe]) -> Fraction | None:
        """The cheapest cost per kcal among `pool` (None: none supplies kcal)."""
        return min(
            (Fraction(self.cost(r), r.per_portion.kcal) for r in pool if r.per_portion.kcal > 0),
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

    def cells_label(self, cells: Sequence[tuple[int, Slot]]) -> str:
        """'Mon, Wed and Fri dinner'; 'Mon lunch and Fri dinner'."""
        if len({slot for _, slot in cells}) == 1:
            return f"{_join(self.day_name(d) for d, _ in cells)} {_SINGULAR[cells[0][1]]}"
        return _join(f"{self.day_name(d)} {_SINGULAR[s]}" for d, s in cells)


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


def _word(n: int) -> str:
    return {1: "once", 2: "twice"}.get(n, f"{n} times")


def _times(low: int, high: int) -> str:
    if low == high:
        return f"each at most {_word(high)}"
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

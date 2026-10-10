"""The planning problem and its answer: the contract between the API, `solve()`, the validator,
the baseline planner and the evals. Pure data plus a few definitional helpers.

Every quantity is an integer, so `solve()` and `validate()` do the same exact arithmetic and a
plan can never pass one and fail the other by a rounding error:

- A *portion* is half a recipe serving. Meal sizes are whole portions: 1 = half a serving,
  2 = one serving, 3 = one and a half, 4 = two. Each slot has its own allowed range.
- Nutrition is per portion: kcal and grams of protein, fat and carbs, rounded once when the
  problem is built.
- Ingredient amounts are whole grams per portion, rounded up. Store-cupboard staples (water,
  salt, pepper, dried herbs and spices, raising agents) and any line under 1 g per portion are
  0 g: they still carry allergen/diet tags but are not costed, bought or drawn from the pantry
  ("check you have" on the shopping list).
- Money is in minor units (pence/cents). Prices are per kilogram, so `grams * price_per_kg` is
  the cost in thousandths of a minor unit ("millipence"); objective terms use that unit.
- Days are indices 0..days-1 counted from `Problem.start`.

Hard constraints (validator codes with `hard=True`): one meal per required slot per day,
eligibility, portion ranges, allergens/diet/avoided foods, locks, repeat caps, daily kcal band
and calorie floor, budget. Protein, fat and carbs bands are soft: missing them costs
`Weights.macro` per gram, so a plan always exists when the hard rules allow one.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from datetime import date
from enum import StrEnum

from larder_core.allergens import Allergen
from larder_core.meals import SLOT_ORDER, Slot
from larder_core.tagging import AnimalTag, Diet

__all__ = [
    "SLOT_ORDER",
    "Allergen",
    "AnimalTag",
    "Band",
    "Catalog",
    "Diet",
    "Food",
    "Ingredient",
    "Lot",
    "Macros",
    "Meal",
    "Nutrient",
    "Plan",
    "PlanResult",
    "Problem",
    "Profile",
    "Recipe",
    "Slot",
    "SlotSpec",
    "Status",
    "Targets",
    "Weights",
    "check_problem",
]


class Nutrient(StrEnum):
    KCAL = "kcal"
    PROTEIN = "protein_g"
    FAT = "fat_g"
    CARBS = "carbs_g"


HARD_NUTRIENTS = frozenset({Nutrient.KCAL})


@dataclass(frozen=True, slots=True)
class Macros:
    kcal: int = 0
    protein_g: int = 0
    fat_g: int = 0
    carbs_g: int = 0

    def __add__(self, other: "Macros") -> "Macros":
        return Macros(
            self.kcal + other.kcal,
            self.protein_g + other.protein_g,
            self.fat_g + other.fat_g,
            self.carbs_g + other.carbs_g,
        )

    def times(self, n: int) -> "Macros":
        return Macros(self.kcal * n, self.protein_g * n, self.fat_g * n, self.carbs_g * n)

    def get(self, nutrient: Nutrient) -> int:
        return int(getattr(self, nutrient.value))


@dataclass(frozen=True, slots=True)
class Band:
    """Inclusive bounds; None means unbounded on that side."""

    min: int | None = None
    max: int | None = None

    def __post_init__(self) -> None:
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"empty band: min {self.min} > max {self.max}")

    def contains(self, value: int) -> bool:
        return self.distance(value) == 0

    def distance(self, value: int) -> int:
        """How far `value` lies outside the band (0 inside)."""
        if self.min is not None and value < self.min:
            return self.min - value
        if self.max is not None and value > self.max:
            return value - self.max
        return 0


@dataclass(frozen=True, slots=True)
class Food:
    id: int
    name: str
    category: str | None = None
    allergens: frozenset[Allergen] = frozenset()
    animal: frozenset[AnimalTag] = frozenset()
    price_per_kg: int = 0  # minor units per kg


@dataclass(frozen=True, slots=True)
class Ingredient:
    food_id: int
    grams: int  # per portion; 0 = store-cupboard staple (tagged, never costed or bought)


@dataclass(frozen=True, slots=True)
class Recipe:
    id: int
    name: str
    meal_types: frozenset[Slot]
    per_portion: Macros
    ingredients: tuple[Ingredient, ...] = ()
    # Ingredient lines whose allergen content isn't established (no food, or an unreviewed
    # approximate match): such a recipe is only safe for users with no allergies, no diet and
    # no avoided foods.
    unresolved: int = 0
    # Tags implied by the recipe's text (ingredient lines, name, instructions, category), on
    # top of the matched foods' tags.
    text_allergens: frozenset[Allergen] = frozenset()
    text_animal: frozenset[AnimalTag] = frozenset()
    cuisine: str | None = None
    preference: int = 0  # how much this user should like it, -100..100 (set by the prefilter)


@dataclass(frozen=True, slots=True)
class SlotSpec:
    """A slot planned every day. `candidates` are recipe ids (best first) the planner may use;
    an optional slot may be left empty. None fields fall back to the Problem defaults."""

    slot: Slot
    required: bool
    candidates: tuple[int, ...]
    min_portions: int | None = None
    max_portions: int | None = None
    max_repeats: int | None = None


@dataclass(frozen=True, slots=True)
class Lot:
    """Pantry stock of one food. `expires` is the last day index it can be eaten (inclusive);
    None means it keeps past the horizon. Lots with `expires < 0` are ignored."""

    food_id: int
    grams: int
    expires: int | None = None


@dataclass(frozen=True, slots=True)
class Meal:
    day: int
    slot: Slot
    recipe_id: int
    portions: int


@dataclass(frozen=True, slots=True)
class Targets:
    """`daily` bands apply to each day's total, `weekly` bands to the sum over all days; both
    include `Problem.extra` (food eaten off-plan). kcal bands are hard, the others soft. No
    day may go below `calorie_floor` kcal."""

    daily: Mapping[Nutrient, Band]
    weekly: Mapping[Nutrient, Band] = field(default_factory=dict[Nutrient, Band])
    calorie_floor: int = 1200


@dataclass(frozen=True, slots=True)
class Profile:
    """Hard exclusions."""

    allergens: frozenset[Allergen] = frozenset()
    avoid_food_ids: frozenset[int] = frozenset()
    diet: Diet | None = None

    @property
    def restricted(self) -> bool:
        return bool(self.allergens or self.avoid_food_ids or self.diet)


@dataclass(frozen=True, slots=True)
class Weights:
    """Objective weights, all in millipence-equivalents ("what would the user pay to get or avoid
    this?"), so money terms are exact and the rest are priced in the same unit. Maximise:

        + preference    * recipe.preference                         per meal
        + pantry        * grams of pantry used
        - cost          * millipence of shopping (grams bought * price_per_kg)
        - waste         * millipence of pantry food left to expire within the horizon
        - repeat        * meals that repeat a recipe already in the plan
        - optional_meal * meals in optional slots (a snack has to earn its place)
        - macro         * grams outside the protein/fat/carbs bands (daily and weekly)
        - churn         * slots whose recipe differs from the previous plan (replans)

    All weights are >= 0. `larder_solver.metrics.score` computes exactly this.
    """

    preference: int = 1_000  # 1 preference point = 1p
    pantry: int = 100  # 0.1p per gram used up
    cost: int = 1
    waste: int = 2  # wasting food costs twice its price
    repeat: int = 150_000  # £1.50 per repeat
    optional_meal: int = 120_000  # £1.20 per snack
    macro: int = 20_000  # 20p per gram outside a macro band
    churn: int = 200_000  # £2 per changed slot


@dataclass(frozen=True, slots=True)
class Problem:
    start: date
    days: int
    slots: tuple[SlotSpec, ...]
    recipes: Mapping[int, Recipe]
    foods: Mapping[int, Food]
    targets: Targets
    profile: Profile = field(default_factory=Profile)
    pantry: tuple[Lot, ...] = ()
    budget: int | None = None  # minor units for the whole horizon
    # Slots fixed by the user: a Meal, or None for "leave this slot empty". Locked meals skip
    # eligibility and portion checks but never the allergen/diet/avoid rules. `extra` never
    # relaxes a required slot: a caller logging an off-plan meal also locks that slot to None.
    locked: Mapping[tuple[int, Slot], Meal | None] = field(
        default_factory=dict[tuple[int, Slot], Meal | None]
    )
    extra: Mapping[int, Macros] = field(default_factory=dict[int, Macros])  # eaten off-plan
    min_portions: int = 1
    max_portions: int = 4
    max_repeats: int = 2
    weights: Weights = field(default_factory=Weights)

    def spec(self, slot: Slot) -> SlotSpec | None:
        return next((s for s in self.slots if s.slot == slot), None)

    def portion_range(self, slot: Slot) -> tuple[int, int]:
        """Allowed portions for an unlocked meal in `slot`."""
        s = self.spec(slot)
        lo = s.min_portions if s and s.min_portions is not None else self.min_portions
        hi = s.max_portions if s and s.max_portions is not None else self.max_portions
        return lo, hi

    def repeat_cap(self, recipe: Recipe) -> int:
        """Most times `recipe` may appear in the plan (locked meals included): the tightest cap
        among the planned slots it is eligible for, else `max_repeats`."""
        caps = [
            s.max_repeats if s.max_repeats is not None else self.max_repeats
            for s in self.slots
            if s.slot in recipe.meal_types
        ]
        return min(caps, default=self.max_repeats)


@dataclass(frozen=True, slots=True)
class Catalog:
    """Recipes and foods a problem draws on (the prefilter's input)."""

    recipes: Mapping[int, Recipe]
    foods: Mapping[int, Food]


@dataclass(frozen=True, slots=True)
class Plan:
    meals: tuple[Meal, ...]

    def at(self, day: int, slot: Slot) -> Meal | None:
        return next((m for m in self.meals if m.day == day and m.slot == slot), None)


class Status(StrEnum):
    OPTIMAL = "optimal"
    FEASIBLE = "feasible"  # a plan, not proven optimal (time limit)
    INFEASIBLE = "infeasible"  # proven: no plan satisfies the hard constraints
    UNKNOWN = "unknown"  # no plan found within the time limit
    INVALID = "invalid"  # the model itself was malformed (a bug)


@dataclass(frozen=True, slots=True)
class PlanResult:
    """`objective` is the maximised score in Weights units with every constant included (same
    sign and scale as `metrics.score(...).total`); `bound` is an upper bound on the best
    possible objective. For any plan returned: objective <= score(plan).total <= bound, with
    equality to the score at OPTIMAL. `wall_ms` runs from solve() entry to return."""

    status: Status
    plan: Plan | None
    planner: str  # "cpsat" | "greedy" | ...
    wall_ms: int
    objective: int | None = None
    bound: int | None = None
    notes: tuple[str, ...] = ()


def check_problem(problem: Problem) -> list[str]:
    """Structural invariants every producer of a Problem must meet ([] = fine). Ingredient
    foods missing from `foods` are allowed: the validator reports them as `unknown_food`."""
    errors: list[str] = []
    slots = [s.slot for s in problem.slots]
    if len(set(slots)) != len(slots):
        errors.append("duplicate slot specs")
    if problem.days < 1:
        errors.append("days must be >= 1")
    if not 1 <= problem.min_portions <= problem.max_portions:
        errors.append("need 1 <= min_portions <= max_portions")
    for s in problem.slots:
        lo, hi = problem.portion_range(s.slot)
        if not 1 <= lo <= hi:
            errors.append(f"{s.slot}: need 1 <= min_portions <= max_portions")
        if s.max_repeats is not None and s.max_repeats < 1:
            errors.append(f"{s.slot}: max_repeats must be >= 1")
        missing = [r for r in s.candidates if r not in problem.recipes]
        if missing:
            errors.append(f"{s.slot}: candidates not in recipes: {missing[:5]}")
    for (day, slot), meal in problem.locked.items():
        if not 0 <= day < problem.days or slot not in slots:
            errors.append(f"lock outside the plan: day {day} {slot}")
        if meal is not None and (
            (meal.day, meal.slot) != (day, slot) or meal.recipe_id not in problem.recipes
        ):
            errors.append(f"bad lock at day {day} {slot}")
    errors.extend(
        f"pantry food {lot.food_id} not in foods"
        for lot in problem.pantry
        if lot.food_id not in problem.foods
    )
    if any(lot.grams < 0 for lot in problem.pantry):
        errors.append("negative pantry grams")
    if any(d not in range(problem.days) for d in problem.extra):
        errors.append("extra intake outside the plan")
    if any(getattr(problem.weights, f.name) < 0 for f in fields(problem.weights)):
        errors.append("weights must be >= 0")
    if problem.budget is not None and problem.budget < 0:
        errors.append("negative budget")
    return errors

"""The planning problem and its answer: the contract between the API, `solve()`, the validator,
the baseline planner and the evals. Pure data, no behaviour beyond small helpers.

Every quantity is an integer, so `solve()` and `validate()` do the same exact arithmetic and a
plan can never pass one and fail the other by a rounding error:

- A *portion* is half a recipe serving. Meal sizes are whole portions: 1 = half a serving,
  2 = one serving, 3 = one and a half, 4 = two.
- Nutrition is per portion: kcal and grams of protein, fat and carbs, rounded once when the
  problem is built.
- Ingredient amounts are whole grams per portion, rounded up (so pantry and shopping checks err
  towards buying a little too much, never too little).
- Money is in minor units (pence/cents). Prices are per kilogram, so `grams * price_per_kg` is the
  cost in thousandths of a minor unit ("millipence"); objective money terms use that unit.
- Days are indices 0..days-1 counted from `Problem.start`.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
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
]


class Nutrient(StrEnum):
    KCAL = "kcal"
    PROTEIN = "protein_g"
    FAT = "fat_g"
    CARBS = "carbs_g"


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
        return (self.min is None or value >= self.min) and (self.max is None or value <= self.max)


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
    grams: int  # per portion


@dataclass(frozen=True, slots=True)
class Recipe:
    id: int
    name: str
    meal_types: frozenset[Slot]
    per_portion: Macros
    ingredients: tuple[Ingredient, ...] = ()
    # Ingredient lines that matched no food: their allergens are unknown, so the recipe is only
    # safe for users with no allergies and no diet.
    unresolved: int = 0
    # Tags implied by the recipe's ingredient *text* ("soy sauce", "worcestershire"), on top of
    # the matched foods' tags.
    text_allergens: frozenset[Allergen] = frozenset()
    text_animal: frozenset[AnimalTag] = frozenset()
    cuisine: str | None = None
    preference: int = 0  # how much this user should like it, -100..100 (set by the prefilter)


@dataclass(frozen=True, slots=True)
class SlotSpec:
    """A slot planned every day. `candidates` are recipe ids (best first) the planner may use;
    an optional slot may be left empty."""

    slot: Slot
    required: bool
    candidates: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Lot:
    """Pantry stock of one food. `expires` is the last day index it can be eaten (inclusive);
    None means it keeps past the horizon."""

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
    include `Problem.extra` (food eaten off-plan). No day may go below `calorie_floor` kcal."""

    daily: Mapping[Nutrient, Band]
    weekly: Mapping[Nutrient, Band] = field(default_factory=dict[Nutrient, Band])
    calorie_floor: int = 1200


@dataclass(frozen=True, slots=True)
class Profile:
    """Hard exclusions."""

    allergens: frozenset[Allergen] = frozenset()
    avoid_food_ids: frozenset[int] = frozenset()
    diet: Diet | None = None


@dataclass(frozen=True, slots=True)
class Weights:
    """Objective weights, all in millipence-equivalents ("what would the user pay to get or avoid
    this?"), so money terms are exact and the rest are priced in the same unit. Maximise:

        + preference * recipe.preference      per meal
        + pantry     * grams of pantry used
        - cost       * millipence of shopping (sum of grams bought * price_per_kg)
        - waste      * millipence of pantry food left to expire within the horizon
        - repeat     * meals that repeat a recipe already in the plan
        - churn      * slots whose recipe differs from the previous plan (replans)
    """

    preference: int = 1_000  # 1 preference point = 1p
    pantry: int = 100  # 0.1p per gram used up
    cost: int = 1
    waste: int = 2  # wasting food costs twice its price
    repeat: int = 150_000  # £1.50 per repeat
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
    # Slots fixed by the user or already eaten: a Meal, or None for "leave this slot empty".
    locked: Mapping[tuple[int, Slot], Meal | None] = field(
        default_factory=dict[tuple[int, Slot], Meal | None]
    )
    extra: Mapping[int, Macros] = field(default_factory=dict[int, Macros])  # eaten off-plan
    min_portions: int = 1
    max_portions: int = 4
    max_repeats: int = 2  # times one recipe may appear in the plan (locked meals included)
    weights: Weights = field(default_factory=Weights)

    def spec(self, slot: Slot) -> SlotSpec | None:
        return next((s for s in self.slots if s.slot == slot), None)


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
    status: Status
    plan: Plan | None
    planner: str  # "cpsat" | "greedy" | ...
    wall_ms: int
    objective: int | None = None  # in Weights units, as the planner computed it
    bound: int | None = None  # best proven bound on the objective, if any
    notes: tuple[str, ...] = ()

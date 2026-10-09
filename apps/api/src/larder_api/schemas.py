"""Request/response models. Field constraints here are the first line of input validation;
domain rules (calorie floor, deficit) live in larder_core.energy."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from larder_core.allergens import Allergen
from larder_core.energy import (
    DEFAULT_FLOOR_KCAL,
    DEFAULT_MAX_DEFICIT_KCAL,
    Activity,
    Goal,
    Sex,
)
from larder_core.meals import Slot

Currency = Literal["GBP", "EUR", "USD"]
Diet = Literal["vegetarian", "vegan", "pescatarian"]

_kcal = Field(ge=0, le=10_000)
_grams = Field(default=None, ge=0, le=2_000)


class ProfileStatus(BaseModel):
    has_goals: bool
    has_body: bool
    has_allergies: bool
    has_preferences: bool
    pantry_items: int


class Me(BaseModel):
    id: int
    created_at: datetime
    profile: ProfileStatus
    setup_complete: bool


class GoalsIn(BaseModel):
    goal: Goal | None = None
    kcal_min: float = _kcal
    kcal_max: float = _kcal
    calorie_floor: float = Field(default=DEFAULT_FLOOR_KCAL, ge=0, le=10_000)
    max_daily_deficit: float = Field(default=DEFAULT_MAX_DEFICIT_KCAL, ge=0, le=10_000)
    protein_g_min: float | None = _grams
    protein_g_max: float | None = _grams
    fat_g_min: float | None = _grams
    fat_g_max: float | None = _grams
    carbs_g_min: float | None = _grams
    carbs_g_max: float | None = _grams
    weekly_budget_minor: int | None = Field(default=None, ge=0, le=10_000_00)
    currency: Currency = "GBP"


class GoalsOut(GoalsIn):
    model_config = ConfigDict(from_attributes=True)

    updated_at: datetime


class BodyIn(BaseModel):
    sex: Sex
    age: int = Field(ge=0, le=130)
    height_cm: float = Field(gt=0, le=300)
    weight_kg: float = Field(gt=0, le=500)
    activity: Activity


class SuggestedTargets(BaseModel):
    kcal_min: float
    kcal_max: float
    protein_g_min: float | None


class BodyOut(BodyIn):
    tdee_kcal: float
    suggestions: dict[Goal, SuggestedTargets]


class PreferencesIn(BaseModel):
    diet: Diet | None = None
    liked_cuisines: list[str] = Field(default_factory=list[str], max_length=50)
    disliked_cuisines: list[str] = Field(default_factory=list[str], max_length=50)
    liked_food_ids: list[int] = Field(default_factory=list[int], max_length=200)
    disliked_food_ids: list[int] = Field(default_factory=list[int], max_length=200)


class PreferencesOut(PreferencesIn):
    model_config = ConfigDict(from_attributes=True)


class AllergiesIn(BaseModel):
    allergens: list[Allergen] = Field(default_factory=list[Allergen])
    avoid_food_ids: list[int] = Field(default_factory=list[int], max_length=200)


class AllergiesOut(AllergiesIn):
    avoid_foods: list["FoodSummary"] = Field(default_factory=list["FoodSummary"])


class AllergenOption(BaseModel):
    code: Allergen
    label: str


class FoodSummary(BaseModel):
    id: int
    description: str
    category: str | None
    kcal: float | None


class FoodUnit(BaseModel):
    """A unit the user can enter for this food, with its weight when one unit is known."""

    unit: str
    grams_each: float | None = None


class FoodDetail(FoodSummary):
    units: list[FoodUnit]


class PantryItemIn(BaseModel):
    food_id: int
    quantity: float = Field(gt=0, le=100_000)
    unit: str = Field(min_length=1, max_length=32)
    approx: bool = False
    expires_on: date | None = None


class PantryItemPatch(BaseModel):
    quantity: float | None = Field(default=None, gt=0, le=100_000)
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    approx: bool | None = None
    expires_on: date | None = None


class PantryItemOut(BaseModel):
    id: int
    food: FoodSummary
    grams: float
    quantity: float
    unit: str
    approx: bool
    expires_on: date | None
    source: str
    created_at: datetime


class Problems(BaseModel):
    """422 body for domain-rule failures (e.g. unsafe calorie targets)."""

    detail: list[str]


# --- plans (M3) -------------------------------------------------------------------------------


class MacrosOut(BaseModel):
    """Energy and macros as whole numbers (kcal, grams)."""

    kcal: int
    protein_g: int
    fat_g: int
    carbs_g: int


class BandOut(BaseModel):
    min: int | None = None
    max: int | None = None


class NutrientBands(BaseModel):
    kcal: BandOut | None = None
    protein_g: BandOut | None = None
    fat_g: BandOut | None = None
    carbs_g: BandOut | None = None


class TargetsOut(BaseModel):
    """What the planner aimed for: per-day bands, whole-plan bands, and the calorie floor."""

    daily: NutrientBands
    weekly: NutrientBands
    calorie_floor: int


class RecipeCard(BaseModel):
    id: int
    name: str
    category: str | None
    cuisine: str | None
    image_url: str | None


class MealOut(BaseModel):
    slot: Slot
    recipe: RecipeCard
    portions: int = Field(description="half-servings: 2 = one serving")
    servings: float
    nutrition: MacrosOut
    locked: bool = False
    status: Literal["planned", "eaten", "skipped", "off_plan"] = "planned"


class DayOut(BaseModel):
    day: int
    date: date
    meals: list[MealOut]
    totals: MacrosOut


class ViolationOut(BaseModel):
    """A rule the plan misses. `hard` ones (kcal band, budget, repeats) come only from the
    baseline planner; soft ones (protein/fat/carbs bands) are trade-offs any planner may make.
    Safety rules (allergens, diet, calorie floor) are never broken in a saved plan."""

    code: str
    message: str
    hard: bool
    day: int | None = None
    slot: Slot | None = None
    recipe_id: int | None = None


class PlanRequest(BaseModel):
    start: date | None = Field(
        default=None,
        description="first day (the user's local date, from yesterday to a week ahead); "
        "defaults to today (UTC)",
    )


class PlanOut(BaseModel):
    id: int
    version: int
    start: date
    days: list[DayOut]
    planner: str
    status: str
    created_at: datetime
    solve_ms: int
    currency: Currency
    targets: TargetsOut
    week_totals: MacrosOut
    cost_minor: int = Field(description="estimated shopping cost")
    budget_minor: int | None
    pantry_used_g: int
    waste_g: int = Field(description="pantry food that will expire unused within the plan")
    shopping_items: int
    # The hard exclusions this plan was made under (shown prominently, PLAN §8).
    excluded_allergens: list[Allergen]
    diet: Diet | None
    violations: list[ViolationOut]
    notes: list[str]


class ShoppingItemOut(BaseModel):
    food_id: int
    name: str
    category: str | None
    grams: int
    cost_minor: int = Field(description="share of total_minor; lines sum exactly to the total")
    checked: bool
    staple: bool = Field(description="store-cupboard item to check you have; no grams or cost")
    # A friendlier amount when the food has a natural unit, e.g. "≈ 2 medium" onions.
    approx_units: str | None = None


class ShoppingListOut(BaseModel):
    plan_id: int
    currency: Currency
    total_minor: int = Field(description="estimated cost of every non-staple line (= plan cost)")
    budget_minor: int | None
    items: list[ShoppingItemOut]


class ShoppingItemPatch(BaseModel):
    checked: bool


class RecipeIngredientOut(BaseModel):
    name: str
    measure: str
    food_id: int | None
    food_name: str | None
    grams: float | None


class RecipeDetail(RecipeCard):
    instructions: str
    source: str
    source_url: str | None
    servings: int | None
    servings_estimated: bool
    per_serving: MacrosOut | None
    meal_types: list[Slot]
    allergens: list[Allergen]
    # Allergen safety can't be proven when some ingredient lines matched no food.
    allergens_complete: bool
    suitable_for: list[Diet]
    ingredients: list[RecipeIngredientOut]

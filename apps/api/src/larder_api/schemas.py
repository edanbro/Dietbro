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

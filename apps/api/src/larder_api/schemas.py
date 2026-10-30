"""Request/response models. Field constraints here are the first line of input validation;
domain rules (calorie floor, deficit) live in larder_core.energy."""

from datetime import date, datetime, time
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from larder_core.allergens import Allergen
from larder_core.energy import (
    DEFAULT_FLOOR_KCAL,
    DEFAULT_MAX_DEFICIT_KCAL,
    Activity,
    Goal,
    Sex,
)
from larder_core.meals import Slot
from larder_core.tagging import Diet
from larder_llm.outcome import Logged, ReplanOutcome
from larder_llm.schemas import MAX_CHANGES, Change

Currency = Literal["GBP", "EUR", "USD"]
Units = Literal["metric", "us"]

_kcal = Field(ge=0, le=10_000)
_grams = Field(default=None, ge=0, le=2_000)


class ProfileStatus(BaseModel):
    has_goals: bool
    has_body: bool
    has_allergies: bool
    has_preferences: bool
    pantry_items: int
    expiring_soon: int = 0  # pantry items past or within 3 days of their use-by date


class RegionOption(BaseModel):
    country: str  # ISO 3166-1 alpha-2
    name: str
    currency: Currency


class RegionOut(RegionOption):
    locale: str  # BCP 47, for number and date formatting
    timezone: str  # IANA
    units: Units  # weights and heights: chosen, else the region's ("us" in the US)
    saved: bool  # False: nothing saved yet, these are the defaults (GB)


class RegionIn(BaseModel):
    country: str = Field(pattern=r"^[A-Za-z]{2}$")
    timezone: str | None = Field(default=None, max_length=64)
    locale: str | None = Field(default=None, pattern=r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
    units: Units | None = None  # None: keep the saved choice


class Me(BaseModel):
    id: int
    created_at: datetime
    profile: ProfileStatus
    setup_complete: bool
    region: RegionOut


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
    household: int = Field(
        default=1,
        ge=1,
        le=8,
        description="people the user cooks for: shopping, cost and amounts cover them all",
    )


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

    # The liked and disliked foods, named (the ids include the generics they count as).
    liked_foods: list["FoodSummary"] = Field(default_factory=list["FoodSummary"])
    disliked_foods: list["FoodSummary"] = Field(default_factory=list["FoodSummary"])
    # Busy nights (PUT /me/preferences/quick-nights): set on their own, not by PUT preferences.
    quick_days: list[int] = Field(default_factory=list[int])
    quick_minutes: int = 30
    # Which meals are planned (PUT /me/preferences/meals), every slot listed.
    meals: "MealsIn" = Field(default_factory=lambda: MealsIn())
    # How far from everyday meals to go (PUT /me/preferences/meal-style).
    meal_style: "MealStyle" = "everyday"


QuickMinutes = Literal[20, 30, 45]


MealMode = Literal["plan", "own", "skip"]
MealStyle = Literal["everyday", "mix", "adventurous"]


class MealsIn(BaseModel):
    """Which meals the planner plans: "plan" it, "own" (the user sorts it out, and about its
    share of the day's targets is kept free for it) or "skip" (not eaten: the planned meals
    cover the day). The same goes for up to three snacks; `snack` is the afternoon one."""

    breakfast: MealMode = "plan"
    lunch: MealMode = "plan"
    dinner: MealMode = "plan"
    morning_snack: MealMode = "skip"
    snack: MealMode = "plan"
    evening_snack: MealMode = "skip"


class MealStyleIn(BaseModel):
    """How far from everyday meals the planner goes: "everyday" (familiar meals, plus favourites
    and liked cuisines), "mix" (about half and half) or "adventurous" (the whole catalogue)."""

    meal_style: MealStyle


class QuickNightsIn(BaseModel):
    """Busy nights: on these weekdays (0 = Monday, 6 = Sunday) dinner takes at most
    `minutes`, about (the planner picks among recipes estimated that quick)."""

    days: list[Annotated[int, Field(ge=0, le=6)]] = Field(max_length=7)
    minutes: QuickMinutes = 30


class AllergiesIn(BaseModel):
    allergens: list[Allergen] = Field(default_factory=list[Allergen])
    avoid_food_ids: list[int] = Field(default_factory=list[int], max_length=200)


class AllergiesOut(AllergiesIn):
    avoid_foods: list["FoodSummary"] = Field(default_factory=list["FoodSummary"])


class AllergenOption(BaseModel):
    code: Allergen
    label: str


FoodKind = Literal["food", "product"]


class FoodSummary(BaseModel):
    id: int
    description: str
    category: str | None
    kcal: float | None
    kind: FoodKind = "food"  # product: a packaged, branded product (Open Food Facts)
    brand: str | None = None
    source: str = "usda"  # usda | cofid | off
    image_url: str | None = None  # products: Open Food Facts' photo (CC BY-SA)


NutritionGrade = Literal["A", "B", "C", "D", "E"]


class FoodUnit(BaseModel):
    """A unit the user can enter for this food, with its weight when one unit is known."""

    unit: str
    grams_each: float | None = None


class FoodDetail(FoodSummary):
    units: list[FoodUnit]
    barcode: str | None = None
    allergens: list[Allergen] = []  # what the food contains, as far as we can tell
    may_contain: list[Allergen] = []  # declared "may contain" traces (products)
    counts_as: "FoodSummary | None" = None  # the generic food it stands in for when planning
    attribution: str  # where the data comes from (licences ask for credit)
    # Nutri-Score method (larder_core.nutrigrade); a product's own grade when it has one.
    grade: NutritionGrade | None = None


class PantryItemIn(BaseModel):
    food_id: int
    quantity: float = Field(gt=0, le=100_000)
    unit: str = Field(min_length=1, max_length=32)
    approx: bool = False
    expires_on: date | None = None


Storage = Literal["fridge", "freezer", "cupboard"]


class PantryItemPatch(BaseModel):
    quantity: float | None = Field(default=None, gt=0, le=100_000)
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    approx: bool | None = None
    expires_on: date | None = None
    # Where it's kept; null goes back to where that food usually is.
    storage: Storage | None = None


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
    storage: Storage = "cupboard"  # where it's kept (the user's choice, else the usual place)
    checked_on: date = Field(
        description="when the user last added, changed or confirmed it (their stale-check clock)"
    )


class ExpiringItem(PantryItemOut):
    days_left: int  # negative: expired that many days ago


class ExpiringPantry(BaseModel):
    """Pantry items with something left whose use-by date is before `today` + `days`, soonest
    first (expired ones included)."""

    today: date
    days: int
    expired: int
    items: list[ExpiringItem]


# --- receipts (M6) ----------------------------------------------------------------------------

ReceiptStatus = Literal["queued", "processing", "ready", "failed", "confirmed"]
ReceiptSource = Literal["image", "text"]
LineStatus = Literal["suggested", "accepted", "edited", "rejected"]
MAX_RECEIPT_TEXT = 20_000


class ReceiptTextIn(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_RECEIPT_TEXT)
    purchased_on: date | None = None  # default: today (UTC)


class ReceiptLineOut(BaseModel):
    """A line read from the receipt and the pantry entry suggested for it. `food` is null when
    nothing matched (pick one with PATCH). `match_method`: receipt | alias | trigram | partial
    (a shorter phrase of the name matched) | user."""

    id: int
    position: int
    raw_text: str
    name: str
    food: FoodSummary | None
    match_method: str | None
    quantity: float | None
    unit: str | None
    grams: float | None
    approx: bool
    price_minor: int | None
    expires_on: date | None
    status: LineStatus
    pantry_item_id: int | None


class ReceiptOut(BaseModel):
    """Poll while `status` is queued or processing. ready: review `lines`; failed: `error`
    says why (the photo is already deleted); confirmed: lines are in the pantry."""

    id: int
    source: ReceiptSource
    status: ReceiptStatus
    purchased_on: date
    error: str | None
    created_at: datetime
    processed_at: datetime | None
    confirmed_at: datetime | None
    lines: list[ReceiptLineOut]


class ReceiptSummary(BaseModel):
    id: int
    source: ReceiptSource
    status: ReceiptStatus
    purchased_on: date
    error: str | None
    created_at: datetime
    lines: int


class ReceiptLinePatch(BaseModel):
    """Change a suggestion. Setting `food_id` re-estimates the amount for that food unless a
    quantity and unit are given too; any edit makes the line `edited`. `status`: accepted,
    rejected, or back to suggested."""

    food_id: int | None = None
    quantity: float | None = Field(default=None, gt=0, le=100_000)
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    approx: bool | None = None
    expires_on: date | None = None
    status: Literal["suggested", "accepted", "rejected"] | None = None


class ReceiptConfirmOut(BaseModel):
    receipt: ReceiptOut
    created: list[PantryItemOut]


class Problems(BaseModel):
    """422 body for domain-rule failures (e.g. unsafe calorie targets)."""

    detail: list[str]


# --- plans (M3) -------------------------------------------------------------------------------


class MacrosOut(BaseModel):
    """Energy and macros as whole numbers (kcal, grams). Fibre, sugars, saturated fat and salt
    (sodium x 2.5) come from recipes, one decimal; null when unknown. Day and week totals add
    planned meals only (food logged off-plan has energy and macros, not these)."""

    kcal: int
    protein_g: int
    fat_g: int
    carbs_g: int
    fiber_g: float | None = None
    sugars_g: float | None = None
    sat_fat_g: float | None = None
    salt_g: float | None = None
    # Vitamins and minerals, from recipes; null when unknown (an ingredient without data), and
    # a day or week total is null if any of its meals is.
    iron_mg: float | None = None
    calcium_mg: float | None = None
    potassium_mg: float | None = None
    vitamin_c_mg: float | None = None
    vitamin_d_ug: float | None = None
    folate_ug: float | None = None
    vitamin_b12_ug: float | None = None


class ReferenceIntakes(BaseModel):
    """Daily guides, shown for context, never planned for. Fibre (at least: UK advice), sugars,
    saturated fat and salt (at most) are the UK/EU reference intakes; the vitamins and minerals
    are the EU labelling reference intakes for adults, the % on food labels."""

    fiber_g: float = 30
    sugars_g: float = 90
    sat_fat_g: float = 20
    salt_g: float = 6
    iron_mg: float = 14
    calcium_mg: float = 800
    potassium_mg: float = 2000
    vitamin_c_mg: float = 80
    vitamin_d_ug: float = 5
    folate_ug: float = 200
    vitamin_b12_ug: float = 2.5


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
    reference: ReferenceIntakes = Field(default_factory=ReferenceIntakes)


class RecipeCard(BaseModel):
    id: int
    name: str
    category: str | None
    cuisine: str | None
    image_url: str | None
    minutes: int | None = Field(
        default=None, description="about how long it takes, estimated from the method"
    )


class MealOut(BaseModel):
    slot: Slot
    recipe: RecipeCard
    portions: int = Field(description="half-servings: 2 = one serving")
    servings: float
    nutrition: MacrosOut
    locked: bool = Field(default=False, description="pinned by the user (a craving or swap)")
    status: Literal["planned", "eaten"] = Field(
        default="planned", description="eaten: marked eaten (POST /plans/{id}/meals/eaten)"
    )
    uses_pantry: list[str] = Field(
        default=[], description="foods in the user's pantry now that the recipe uses"
    )


class AheadItemOut(BaseModel):
    """Something to do the evening before a meal (larder_api.prep_ahead)."""

    kind: Literal["defrost", "start"] = Field(
        description="defrost: take `text` (a pantry food) out of the freezer; start: do `text` "
        "(a step of the method) ahead"
    )
    slot: Slot
    recipe_id: int
    recipe_name: str
    text: str


class AheadOut(BaseModel):
    date: date  # the meals' day; the work is for the evening before
    items: list[AheadItemOut]


class MealLogOut(Logged):
    """Food eaten off-plan, a planned meal skipped (eating elsewhere), or a meal marked eaten
    that this version no longer plans, as snapshotted with the plan version: `DayOut.totals` =
    its meals + these. A meal marked eaten that the version still plans shows as that meal
    (`MealOut.status` eaten), not here."""

    recipe_id: int | None = Field(default=None, description="eaten: the recipe")
    id: int | None = Field(default=None, description="the log (DELETE /diary/logs/{id})")


class RemovedLogOut(BaseModel):
    """A log removed; `outcome`: the meal it stood for planned again (today or later)."""

    outcome: "OutcomeOut | None" = None


class DayOut(BaseModel):
    day: int
    date: date
    meals: list[MealOut]
    totals: MacrosOut
    logged: list[MealLogOut]


# --- diary and progress -----------------------------------------------------------------------


class DiaryDayOut(BaseModel):
    """What the user logged on a day: meals marked eaten, food logged off-plan and meals
    skipped (a skip eaten elsewhere carries that meal's energy). `eaten` adds them up;
    `planned_kcal` is the newest plan's total for the day (null: no plan covers it)."""

    date: date
    eaten: MacrosOut
    logged: list[MealLogOut]
    planned_kcal: int | None = None
    status: Literal["under", "on", "over"] | None = Field(
        default=None, description="against the daily kcal goal; null when nothing is logged"
    )


class DiaryOut(BaseModel):
    days: list[DiaryDayOut]  # oldest first
    today: date  # the user's local date
    kcal_min: float | None = None
    kcal_max: float | None = None
    protein_g_min: float | None = None
    # Of the logged days before today: how many landed within the kcal goal.
    logged_days: int = 0
    on_target_days: int = 0


class SpendingWeekOut(BaseModel):
    start: date  # the Monday
    spent_minor: int = Field(description="confirmed receipt lines bought that week")
    planned_minor: int | None = Field(
        description="estimated food cost of the plans starting that week (latest versions)"
    )


class SpendingCategoryOut(BaseModel):
    category: str | None  # USDA food group (a product counts as its generic food's group)
    spent_minor: int


class PricePointOut(BaseModel):
    on: date
    per_kg_minor: int


class CheaperOut(BaseModel):
    label: str = Field(description="the product, as named on the user's receipt or its pack")
    per_kg_minor: int
    last_bought: date


class PriceItemOut(BaseModel):
    food_id: int
    name: str
    history: list[PricePointOut] = Field(description="oldest first, at most 12")
    latest_minor: int = Field(description="per kg")
    usual_minor: int = Field(description="per kg: the median of the earlier prices")
    change_pct: int
    rise: bool = Field(description="the latest is at least 15% over the usual (2+ earlier)")
    cheaper: CheaperOut | None = None


class PricesOut(BaseModel):
    currency: Currency
    items: list[PriceItemOut] = Field(description="rises first, biggest first; then by name")


class RecapTopOut(BaseModel):
    recipe: RecipeCard
    times: int


class RecapRiseOut(BaseModel):
    name: str
    change_pct: int


class RecapOut(BaseModel):
    """A week looked back on (Monday to Sunday): only what happened, from the meal logs,
    confirmed receipts, weigh-ins and price watch."""

    week_start: date
    week_end: date
    currency: Currency
    planned_meals: int
    eaten_meals: int = Field(description="planned meals marked eaten")
    skipped_meals: int
    off_plan: int = Field(description="food logged that wasn't on the plan")
    logged_days: int
    avg_kcal: int | None = Field(description="a logged day's average")
    kcal_min: float | None
    kcal_max: float | None
    on_target_days: int = Field(description="logged days within the calorie band")
    protein_g_min: float | None
    protein_days: int | None = Field(description="logged days reaching the protein goal")
    spent_minor: int
    budget_minor: int | None
    planned_cost_minor: int | None
    weight_change_kg: float | None = Field(description="first to last weigh-in that week")
    weight_kg: float | None
    top_recipes: list[RecapTopOut]
    price_rises: list[RecapRiseOut]
    empty: bool = Field(description="nothing logged, bought or weighed that week")


class SpendingOut(BaseModel):
    """Grocery spending from the user's own confirmed receipts, week by week, beside what the
    plans estimated. Lines without a price, or rejected, don't count."""

    currency: Currency
    weeks: list[SpendingWeekOut]  # oldest first, ending with this week
    categories: list[SpendingCategoryOut]  # most spent first, over the whole period
    unmatched_minor: int = Field(description="spent on lines not matched to a food")


class ImportReadIn(BaseModel):
    url: str = Field(max_length=2000)


class ImportIngredient(BaseModel):
    line: str = Field(default="", max_length=300, description="as written on the page")
    name: str = Field(max_length=120)
    quantity: str = Field(default="", max_length=40)


class ImportDraft(BaseModel):
    """A recipe read from a page (or typed in), before it is checked and saved. The user can
    change anything first."""

    name: str = Field(min_length=1, max_length=120)
    slot: Slot
    servings: int = Field(ge=1, le=8)
    cuisine: str | None = Field(default=None, max_length=40)
    ingredients: list[ImportIngredient] = Field(min_length=2, max_length=25)
    instructions: str = Field(max_length=4000)
    image_url: str | None = Field(default=None, max_length=2000)
    source_url: str | None = Field(default=None, max_length=2000)


class ImportResultOut(BaseModel):
    recipe_id: int | None  # set when saved
    problems: list[str]  # what to fix when not saved, e.g. "couldn't match 'X'"
    copied: bool = False  # an edit of a catalogue recipe: saved as the user's own copy


class RecipeNoteIn(BaseModel):
    note: str | None = Field(default=None, max_length=1000)
    rating: int | None = Field(default=None, ge=1, le=5)


class RecipeNoteOut(BaseModel):
    note: str | None
    rating: int | None
    updated_at: datetime


class PushConfigOut(BaseModel):
    """Whether this server sends reminders, the key browsers subscribe with, and whether this
    user has any browser subscribed."""

    enabled: bool
    public_key: str | None = None
    subscribed: int = 0  # browsers this user turned reminders on in
    weekly_recap: bool = True  # also the Sunday-evening recap
    prep_reminders: bool = True  # also the evening heads-up for tomorrow's meals


class RecapSettingIn(BaseModel):
    enabled: bool


class AheadSettingIn(BaseModel):
    enabled: bool


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=10, max_length=200)
    auth: str = Field(min_length=8, max_length=100)


class PushSubscriptionIn(BaseModel):
    """A browser's PushSubscription.toJSON()."""

    endpoint: str = Field(pattern=r"^https://", max_length=2000)
    keys: PushKeys


class PushUnsubscribeIn(BaseModel):
    endpoint: str = Field(max_length=2000)


class WeightIn(BaseModel):
    measured_on: date
    weight_kg: float = Field(gt=20, le=500)


class WeightOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    measured_on: date
    weight_kg: float


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
    repeat_from: date | None = Field(
        default=None,
        description="plan the same meals as the 7 days from this date (an earlier week), where "
        "they still suit the user's allergies, diet and blocks",
    )
    template_id: int | None = Field(
        default=None, description="plan the meals of this saved template (GET /me/templates)"
    )

    @model_validator(mode="after")
    def _one_source(self) -> Self:
        if self.repeat_from is not None and self.template_id is not None:
            raise ValueError("give repeat_from or template_id, not both")
        return self


class OwnMealOut(BaseModel):
    """A meal the user sorts out themselves: about this much is kept free for it each day (and
    counted in the day's totals)."""

    slot: Slot
    kcal: int


class PlanOut(BaseModel):
    id: int
    version: int
    parent_id: int | None
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
    household: int = Field(
        default=1, description="people the plan is cooked for (its shopping, cost, pantry use)"
    )
    # The hard exclusions this plan was made under (shown prominently, PLAN §8).
    excluded_allergens: list[Allergen]
    diet: Diet | None
    violations: list[ViolationOut]
    notes: list[str]
    own_meals: list[OwnMealOut] = Field(default_factory=list[OwnMealOut])
    skipped_meals: list[Slot] = Field(
        default_factory=list[Slot], description="meals the user doesn't eat (never planned)"
    )


class EatenIn(BaseModel):
    """Mark a planned meal eaten: a meal of the plan, on or before the user's today."""

    today: date = Field(description="the user's local date (a later `date` is refused)")
    date: date
    slot: Slot


class PantryChangeOut(BaseModel):
    """Pantry food a meal marked eaten used (or, on undo, gave back), in the item's own unit."""

    pantry_item_id: int
    food_id: int
    name: str
    grams: float
    quantity: float
    unit: str
    remaining_quantity: float | None = Field(
        description="the item's quantity now; null = the item was deleted since (undo: nothing "
        "was given back)"
    )


class EatenOut(BaseModel):
    """A meal's eaten state after marking (or undoing) it. No new plan version is made: reload
    the plan and the pantry to see them."""

    plan_id: int
    date: date
    slot: Slot
    status: Literal["planned", "eaten"]
    changed: bool = Field(description="false: it already was in this state (a repeat)")
    meal: MealOut | None = Field(description="the plan's meal at that cell, if any")
    pantry: list[PantryChangeOut] = Field(description="taken (mark) or given back (undo)")
    notes: list[str]


class UsedInOut(BaseModel):
    """A recipe of the plan that needs a shopping line, and the days it's on."""

    recipe_id: int
    name: str
    dates: list[date]


class ShoppingItemOut(BaseModel):
    food_id: int
    name: str
    category: str | None
    grams: int
    cost_minor: int = Field(description="share of total_minor; lines sum exactly to the total")
    checked: bool
    stocked: bool = Field(default=False, description="bought and moved into the pantry")
    staple: bool = Field(description="store-cupboard item to check you have; no grams or cost")
    # A friendlier amount when the food has a natural unit, e.g. "≈ 2 medium" onions.
    approx_units: str | None = None
    pack_g: int | None = Field(
        default=None, description="the usual pack (larder_core.packs); None: sold loose"
    )
    packs: int | None = Field(default=None, description="whole packs that hold `grams`")
    till_minor: int = Field(
        default=0, description="what the whole packs cost (cost_minor when sold loose)"
    )
    used_in: list[UsedInOut] = Field(
        default_factory=list[UsedInOut], description="the plan's recipes that need it, by day"
    )


class UsualOut(BaseModel):
    """A food the user buys most weeks (from their receipts), to add to the list in one tap."""

    food_id: int
    name: str
    weeks: int = Field(description="weeks of the last 8 it was bought in")
    last_bought: date


class ShoppingListOut(BaseModel):
    plan_id: int
    currency: Currency
    total_minor: int = Field(description="estimated cost of every non-staple line (= plan cost)")
    till_minor: int = Field(
        default=0,
        description="estimated spend buying whole packs; the rest of each pack goes to the pantry",
    )
    budget_minor: int | None
    household: int = Field(default=1, description="people the amounts are for")
    items: list[ShoppingItemOut]


class ShoppingItemPatch(BaseModel):
    checked: bool


class StockIn(BaseModel):
    """Lines to move into the pantry; default: every ticked line not moved yet."""

    food_ids: list[int] | None = Field(default=None, max_length=500)


class ShoppingExtraIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ShoppingExtrasIn(BaseModel):
    """Several items at once (a recipe's ingredients): one request, all or none."""

    names: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(
        min_length=1, max_length=40
    )


class ShoppingExtraPatch(BaseModel):
    checked: bool


class ShoppingExtraOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    checked: bool


class RecipeIngredientOut(BaseModel):
    name: str
    measure: str
    food_id: int | None
    food_name: str | None
    grams: float | None
    # The signed-in viewer has this food (or a product that counts as it) in their pantry.
    in_pantry: bool = False


class RecipeDetail(RecipeCard):
    instructions: str
    # True for a recipe the assistant drafted for this user (private; nutrition computed by us).
    generated: bool
    source: str
    source_url: str | None
    servings: int | None
    servings_estimated: bool
    per_serving: MacrosOut | None
    # What a serving costs the viewer (their prices, `currency` minor units); None signed out.
    cost_per_serving: int | None = None
    currency: Currency | None = None
    grade: NutritionGrade | None = None  # Nutri-Score method, per 100 g of the dish
    meal_types: list[Slot]
    allergens: list[Allergen]
    # Allergen safety can't be proven when some ingredient lines matched no food.
    allergens_complete: bool
    suitable_for: list[Diet]
    ingredients: list[RecipeIngredientOut]
    # The signed-in viewer's verdict on it (PUT /recipes/{id}/feedback).
    feedback: "RecipeVerdict | None" = None
    # The viewer's own note and rating (PUT /recipes/{id}/note); never on a share link.
    note: RecipeNoteOut | None = None


RecipeVerdict = Literal["favourite", "never"]


class RecipeDeletedOut(BaseModel):
    """A recipe of the user's own, gone: deleted, or (`hidden`, when a plan of theirs has it)
    kept for those plans but never shown or planned again."""

    hidden: bool


class RecipeFeedbackIn(BaseModel):
    verdict: RecipeVerdict


class RecipeListItem(RecipeCard):
    slots: list[Slot]
    kcal_per_serving: int
    protein_g_per_serving: int
    uses_pantry: list[str] = Field(default=[], description="pantry foods it uses")
    favourite: bool = False
    missing: list[str] | None = Field(
        default=None, description="?pantry=true: the foods it needs that the pantry hasn't got"
    )
    cost_per_serving: int | None = Field(
        default=None,
        description="estimated cost of a serving, in RecipeListOut.currency minor units",
    )


class RecipeListOut(BaseModel):
    items: list[RecipeListItem]
    total: int  # how many match, for paging
    currency: Currency | None = None  # of the items' costs


# --- plan changes (M4, M5) -------------------------------------------------------------------


class ChangeProblem(BaseModel):
    """Body of a refused replan (400 bad_today, 409 busy / duplicate)."""

    detail: list[str]
    code: Literal["bad_today", "busy", "duplicate"]


class OutcomeOut(ReplanOutcome):
    """What one plan change request did."""

    type: Literal["outcome"] = "outcome"


class FoodLogItem(BaseModel):
    food_id: int
    grams: float = Field(gt=0, le=5000)


class FoodTextRequest(BaseModel):
    """What someone typed that they ate: "two eggs, toast and a coffee"."""

    text: str = Field(min_length=1, max_length=300)
    today: date = Field(description="the user's local date")


class ParsedFoodOut(BaseModel):
    name: str = Field(description="the user's words for it")
    food: "FoodSummary"
    grams: float
    estimated: bool = Field(description="the amount is a typical portion, not what they said")


class FoodTextOut(BaseModel):
    """Foods to check and then log (POST /diary/log); nothing has been logged yet."""

    items: list[ParsedFoodOut]
    unmatched: list[str] = Field(description="names that matched no food")


class RecentFoodItemOut(BaseModel):
    food: "FoodSummary"
    grams: float


class RecentFoodOut(BaseModel):
    """Food logged lately (diary quick-add), to log again: each mix of foods and amounts once,
    as the diary named it."""

    description: str
    kcal: int
    last_eaten_on: date
    items: list[RecentFoodItemOut]


class FoodLogRequest(BaseModel):
    """Food the user picked themselves (diary quick-add). Logged as food eaten off-plan, with
    exact amounts, so the rest of that day's plan rebalances around it."""

    eaten_on: date = Field(description="the day it was eaten (the user's local date)")
    slot: Slot | None = Field(default=None, description="default: the next meal by local time")
    items: list[FoodLogItem] = Field(min_length=1, max_length=10)
    client_id: UUID = Field(description="the client's id for this request: resending is safe")
    today: date = Field(description="the user's local date")
    local_time: time | None = None


class ReplanRequest(BaseModel):
    """Typed plan changes (larder_llm.schemas) from the plan screen or the diary, applied by
    the executor (larder_api.changes.replan)."""

    changes: list[Change] = Field(min_length=1, max_length=MAX_CHANGES)
    client_id: UUID = Field(description="the client's id for this request: resending is safe")
    today: date = Field(description="the user's local date")
    local_time: time | None = Field(
        default=None,
        description="the user's local time: today's meals whose time has passed count as eaten",
    )


class ShareIn(BaseModel):
    kind: Literal["recipe", "week", "list"]
    recipe_id: int | None = None  # for a recipe
    start: date | None = Field(
        default=None, description="for a week or its shopping list: the plan's start date"
    )


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    start: date = Field(description="save the week of the user's plan starting on this date")


class TemplatePatch(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class TemplateOut(BaseModel):
    id: int
    name: str
    created_at: datetime
    meals: int
    recipes: list[str] = Field(description="a few of its recipes' names, for a preview")


class DayMealOut(BaseModel):
    """A meal planned on a date (GET /plans/meals): to copy a day's meals to another."""

    slot: Slot
    recipe: RecipeCard


class ShareOut(BaseModel):
    token: str
    path: str  # the web page: /s/<token>


class SharedMealOut(BaseModel):
    slot: Slot
    recipe: RecipeCard
    kcal: int


class SharedDayOut(BaseModel):
    date: date
    meals: list[SharedMealOut]


class SharedItemOut(BaseModel):
    """A line of a shared shopping list: what to buy (no prices), ticked or not."""

    food_id: int
    name: str
    category: str | None
    grams: int
    approx_units: str | None = None
    checked: bool
    staple: bool


class SharedExtraOut(BaseModel):
    id: int
    name: str
    checked: bool


class SharedListOut(BaseModel):
    start: date
    household: int
    units: Units = "metric"  # how the owner reads weights
    items: list[SharedItemOut]
    extras: list[SharedExtraOut] = Field(description="the owner's own items (bin bags)")


class SharedTickIn(BaseModel):
    checked: bool


class SharedOut(BaseModel):
    """What a share link shows: one recipe, a week's meals, or a week's shopping list. Nothing
    about the person."""

    kind: Literal["recipe", "week", "list"]
    recipe: RecipeDetail | None = None
    days: list[SharedDayOut] | None = None
    shopping: SharedListOut | None = None


_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class CalendarTimes(BaseModel):
    """When each meal shows on the calendar (24-hour HH:MM, the user's local time)."""

    breakfast: str = Field(default="08:00", pattern=_HHMM)
    lunch: str = Field(default="13:00", pattern=_HHMM)
    dinner: str = Field(default="19:00", pattern=_HHMM)
    snack: str = Field(default="16:00", pattern=_HHMM)
    morning_snack: str = Field(default="10:30", pattern=_HHMM)
    evening_snack: str = Field(default="21:00", pattern=_HHMM)


class CalendarOut(BaseModel):
    enabled: bool
    path: str | None  # on the API: /calendar/<token>.ics
    times: CalendarTimes

"""Relational schema. Quantities are grams; food nutrients are per 100 g.

Data (M1): foods, recipes, embeddings. Users (M2): profile, goals, allergies, pantry; every user
table is keyed or filtered by `user_id`. Plans (M3): versioned weekly plans and shopping lists.
Chat (M4): threads and messages, requested changes, meals logged off-plan, LLM calls; recipes the
assistant drafts are private to their owner. Replans (M5): planned meals marked eaten (a meal log
that records the pantry food it used) and plan changes made from the plan screen (`client_id`).
Pantry intake (M6): receipt uploads (photo or pasted text) and the item lines read from them,
reviewed by the user before they become pantry items.
"""

import uuid
from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSON, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, deferred, mapped_column, relationship

# bge-small-en-v1.5 (see docs/adr/0005-local-embeddings.md).
EMBEDDING_DIM = 384


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class NutrientColumns:
    """Nutrient columns shared by foods (per 100 g) and recipes (per serving). Vitamins and
    minerals (iron down): a recipe's is null when an ingredient that matters (10 g or more)
    has no value for it (larder_core.nutrition.micro_totals), never a silent zero."""

    kcal: Mapped[float | None] = mapped_column(Float)
    protein_g: Mapped[float | None] = mapped_column(Float)
    fat_g: Mapped[float | None] = mapped_column(Float)
    carbs_g: Mapped[float | None] = mapped_column(Float)
    fiber_g: Mapped[float | None] = mapped_column(Float)
    sugars_g: Mapped[float | None] = mapped_column(Float)
    sat_fat_g: Mapped[float | None] = mapped_column(Float)
    sodium_mg: Mapped[float | None] = mapped_column(Float)
    iron_mg: Mapped[float | None] = mapped_column(Float)
    calcium_mg: Mapped[float | None] = mapped_column(Float)
    potassium_mg: Mapped[float | None] = mapped_column(Float)
    vitamin_c_mg: Mapped[float | None] = mapped_column(Float)
    vitamin_d_ug: Mapped[float | None] = mapped_column(Float)
    folate_ug: Mapped[float | None] = mapped_column(Float)
    vitamin_b12_ug: Mapped[float | None] = mapped_column(Float)


# Ids of non-USDA foods start here (foods_local_id_seq); USDA FDC ids are far below.
LOCAL_ID_START = 1_000_000_000


class Food(NutrientColumns, Base):
    """A food; nutrients are per 100 g.

    `source` usda: a USDA FoodData Central food, `id` = FDC id (data_type foundation, sr_legacy
    or survey_fndds). cofid: UK McCance & Widdowson (`source_id` = food code). off: an Open Food
    Facts product (`source_id` = barcode). `category` is always a USDA category name (other
    sources are mapped, their own label kept in `source_category`), so allergen tags, prices,
    shelf life and aisles work for every food. `generic_food_id` is the generic food a regional
    or branded one counts as (pantry matching, prices); recipes only use generic foods.
    """

    __tablename__ = "foods"
    __table_args__ = (
        # Trigram index for type-ahead food search (pg_trgm).
        Index(
            "ix_foods_description_trgm",
            "description",
            postgresql_using="gin",
            postgresql_ops={"description": "gin_trgm_ops"},
        ),
        Index("ix_foods_search_tsv", "search_tsv", postgresql_using="gin"),
        Index("ix_foods_countries", "countries", postgresql_using="gin"),
        Index(
            "uq_foods_barcode",
            "barcode",
            unique=True,
            postgresql_where=text("barcode IS NOT NULL"),
        ),
        UniqueConstraint("source", "source_id"),
        CheckConstraint(f"(source = 'usda') = (id < {LOCAL_ID_START})", name="usda_ids"),
        CheckConstraint(
            "generic_food_id IS NULL OR generic_food_id <> id", name="generic_not_self"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    description: Mapped[str] = mapped_column(Text)
    # foundation | sr_legacy | survey_fndds | cofid | branded
    data_type: Mapped[str] = mapped_column(String(32))
    category: Mapped[str | None] = mapped_column(String(128))
    source: Mapped[str] = mapped_column(String(16), server_default="usda", default="usda")
    source_id: Mapped[str | None] = mapped_column(String(32))  # NULL for USDA (the id is)
    source_category: Mapped[str | None] = mapped_column(Text)
    brand: Mapped[str | None] = mapped_column(Text)
    barcode: Mapped[str | None] = mapped_column(String(14))  # GTIN, normalised
    countries: Mapped[list[str] | None] = mapped_column(ARRAY(String(2)))  # NULL: anywhere
    generic_food_id: Mapped[int | None] = mapped_column(
        ForeignKey("foods.id", ondelete="SET NULL"), index=True
    )
    generic_method: Mapped[str | None] = mapped_column(String(16))  # how the link was made
    allergens_declared: Mapped[list[str] | None] = mapped_column(ARRAY(String(32)))
    traces_declared: Mapped[list[str] | None] = mapped_column(ARRAY(String(32)))
    ingredients_text: Mapped[str | None] = deferred(mapped_column(Text))
    origin: Mapped[str | None] = mapped_column(String(8))  # off: bulk | lookup
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Products: a link to Open Food Facts' photo (CC BY-SA, not stored) and its Nutri-Score.
    image_url: Mapped[str | None] = mapped_column(Text)
    off_grade: Mapped[str | None] = mapped_column(String(1))  # a-e
    search_tsv: Mapped[Any] = deferred(
        mapped_column(
            TSVECTOR,
            Computed(
                "to_tsvector('english'::regconfig, coalesce(brand, '') || ' ' || description)",
                persisted=True,
            ),
        )
    )

    portions: Mapped[list["FoodPortion"]] = relationship(
        back_populates="food", cascade="all, delete-orphan", passive_deletes=True
    )


class FoodPortion(Base):
    """`amount` `unit` of a food weighs `grams` ("1 clove" = 3 g, "1 cup chopped" = 160 g)."""

    __tablename__ = "food_portions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    food_id: Mapped[int] = mapped_column(ForeignKey("foods.id", ondelete="CASCADE"), index=True)
    amount: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(64))  # canonical unit, size word, or raw word
    qualifier: Mapped[str | None] = mapped_column(Text)  # "chopped", "2-1/2\" dia"
    grams: Mapped[float] = mapped_column(Float)

    food: Mapped[Food] = relationship(back_populates="portions")


class FoodEmbedding(Base):
    __tablename__ = "food_embeddings"
    __table_args__ = (
        Index(
            "ix_food_embeddings_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    food_id: Mapped[int] = mapped_column(
        ForeignKey("foods.id", ondelete="CASCADE"), primary_key=True
    )
    model: Mapped[str] = mapped_column(String(128))
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))


class Recipe(NutrientColumns, Base):
    """A recipe. Nutrient columns are per serving, computed from resolved ingredients."""

    __tablename__ = "recipes"
    __table_args__ = (UniqueConstraint("source", "source_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32))  # mealdb | curated | generated
    source_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(64))
    cuisine: Mapped[str | None] = mapped_column(String(64))
    instructions: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    servings: Mapped[int | None] = mapped_column(Integer)
    servings_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    # About how long it takes, estimated from the method (larder_core.cook_time); every writer
    # of `instructions` sets it. NULL without a method.
    minutes: Mapped[int | None] = mapped_column(SmallInteger)
    # True when every ingredient resolved to a food with grams: only these are plannable.
    nutrition_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    # Set for recipes drafted for one user (source "generated"): only that user may see, search
    # or be planned them. NULL = the shared catalogue.
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    ingredients: Mapped[list["RecipeIngredient"]] = relationship(
        back_populates="recipe",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="RecipeIngredient.position",
    )
    tags: Mapped[list["RecipeTag"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )


class RecipeIngredient(Base):
    """One ingredient line, kept verbatim plus its resolution (null when unresolved)."""

    __tablename__ = "recipe_ingredients"
    __table_args__ = (UniqueConstraint("recipe_id", "position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    raw_name: Mapped[str] = mapped_column(Text)
    raw_measure: Mapped[str] = mapped_column(Text, default="")
    food_id: Mapped[int | None] = mapped_column(
        ForeignKey("foods.id", ondelete="SET NULL"), index=True
    )
    grams: Mapped[float | None] = mapped_column(Float)
    match_method: Mapped[str | None] = mapped_column(String(32))  # alias | embedding
    match_score: Mapped[float | None] = mapped_column(Float)

    recipe: Mapped[Recipe] = relationship(back_populates="ingredients")


class RecipeTag(Base):
    __tablename__ = "recipe_tags"

    recipe_id: Mapped[int] = mapped_column(
        ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True
    )
    tag: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)


class RecipeEmbedding(Base):
    __tablename__ = "recipe_embeddings"
    __table_args__ = (
        Index(
            "ix_recipe_embeddings_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    recipe_id: Mapped[int] = mapped_column(
        ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True
    )
    model: Mapped[str] = mapped_column(String(128))
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))


class IngredientMatch(Base):
    """Cache: normalised ingredient name -> food (null food = tried, no confident match)."""

    __tablename__ = "ingredient_matches"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    food_id: Mapped[int | None] = mapped_column(ForeignKey("foods.id", ondelete="CASCADE"))
    method: Mapped[str] = mapped_column(String(32))  # alias | embedding | unmatched
    score: Mapped[float | None] = mapped_column(Float)
    model: Mapped[str | None] = mapped_column(String(128))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# --- users (M2) -------------------------------------------------------------------------------


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class User(Base):
    """An account. `auth_subject` is the identity provider's user id (Clerk JWT `sub`)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    auth_subject: Mapped[str] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = _now()
    # Region (larder_core.regions): ISO country, IANA time zone, BCP 47 locale. NULL until the
    # client saves the region it guessed from the browser (treated as GB meanwhile).
    country: Mapped[str | None] = mapped_column(String(2))
    timezone: Mapped[str | None] = mapped_column(String(64))
    locale: Mapped[str | None] = mapped_column(String(35))
    # The chat turn in progress (one per user): taken with a conditional UPDATE, released by
    # token; a lock older than the turn deadline is stale and may be taken over.
    chat_turn_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    chat_turn_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    chat_turn_message_id: Mapped[int | None] = mapped_column(Integer)  # the user's message
    # The private calendar feed (/calendar/<token>.ics): NULL when off. Meal times for it as
    # {"breakfast": "08:00", ...}; NULL means the defaults.
    calendar_token: Mapped[str | None] = mapped_column(
        String(32), unique=True, info={"constraint": "uq_users_calendar_token"}
    )
    calendar_times: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    # The Sunday-evening recap by push (larder_api.reminders.send_recaps), in browsers that
    # have reminders on.
    weekly_recap: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # The evening heads-up for tomorrow's meals (defrost, marinate; larder_api.prep_ahead).
    prep_reminders: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


class Goals(Base):
    """Daily energy/macro bands (validated by larder_core.energy) and a weekly budget."""

    __tablename__ = "goals"
    __table_args__ = (CheckConstraint("household BETWEEN 1 AND 8", name="household"),)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    goal: Mapped[str | None] = mapped_column(String(16))  # lose | maintain | gain
    kcal_min: Mapped[float] = mapped_column(Float)
    kcal_max: Mapped[float] = mapped_column(Float)
    calorie_floor: Mapped[float] = mapped_column(Float)
    max_daily_deficit: Mapped[float] = mapped_column(Float)
    protein_g_min: Mapped[float | None] = mapped_column(Float)
    protein_g_max: Mapped[float | None] = mapped_column(Float)
    fat_g_min: Mapped[float | None] = mapped_column(Float)
    fat_g_max: Mapped[float | None] = mapped_column(Float)
    carbs_g_min: Mapped[float | None] = mapped_column(Float)
    carbs_g_max: Mapped[float | None] = mapped_column(Float)
    weekly_budget_minor: Mapped[int | None] = mapped_column(Integer)  # pence / cents
    currency: Mapped[str] = mapped_column(String(3), default="GBP")
    # People the user cooks for: shopping, cost and amounts cover them all; nutrition is theirs.
    household: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    updated_at: Mapped[datetime] = _now()


class BodyProfile(Base):
    """Optional body stats for the TDEE estimate. Birth year, not age, so it stays correct."""

    __tablename__ = "body_profiles"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    sex: Mapped[str] = mapped_column(String(8))
    birth_year: Mapped[int] = mapped_column(Integer)
    height_cm: Mapped[float] = mapped_column(Float)
    weight_kg: Mapped[float] = mapped_column(Float)
    activity: Mapped[str] = mapped_column(String(16))
    updated_at: Mapped[datetime] = _now()


class BodyWeight(Base):
    """A weigh-in (one per day; a second the same day replaces it). The newest is copied to
    the body profile, so energy targets follow the user's weight."""

    __tablename__ = "body_weights"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    measured_on: Mapped[date] = mapped_column(Date, primary_key=True)  # the user's local date
    weight_kg: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Preferences(Base):
    """Soft preferences: the solver rewards likes and penalises dislikes, never forbids."""

    __tablename__ = "preferences"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    diet: Mapped[str | None] = mapped_column(String(16))  # vegetarian | vegan | pescatarian
    liked_cuisines: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    disliked_cuisines: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    liked_food_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list)
    disliked_food_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list)
    # Recipe feedback: favourites are planned more often; blocked ones never again.
    favourite_recipe_ids: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), default=list, server_default=text("'{}'")
    )
    blocked_recipe_ids: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), default=list, server_default=text("'{}'")
    )
    # Busy nights: on these weekdays (0 = Monday) dinner takes at most `quick_minutes`.
    quick_days: Mapped[list[int]] = mapped_column(
        ARRAY(SmallInteger), default=list, server_default=text("'{}'")
    )
    quick_minutes: Mapped[int] = mapped_column(SmallInteger, default=30, server_default="30")
    updated_at: Mapped[datetime] = _now()


class Allergies(Base):
    """Hard exclusions: allergen codes (larder_core.allergens) and specific foods."""

    __tablename__ = "allergies"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    allergens: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list)
    avoid_food_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list)
    updated_at: Mapped[datetime] = _now()


class PantryItem(Base):
    """Food on hand. `grams` is canonical; `quantity` + `unit` are kept as the user typed them."""

    __tablename__ = "pantry_items"
    __table_args__ = (
        CheckConstraint(
            "storage IS NULL OR storage IN ('fridge', 'freezer', 'cupboard')", name="storage"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    food_id: Mapped[int] = mapped_column(ForeignKey("foods.id"))
    grams: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(32))
    approx: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_on: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual | receipt
    # Where the user keeps it (fridge | freezer | cupboard); NULL: where that food usually is
    # (larder_core.shelf_life.storage_for). Frozen food is defrosted ahead (larder_api.prep_ahead).
    storage: Mapped[str | None] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = _now()

    food: Mapped[Food] = relationship()


# --- plans (M3) -------------------------------------------------------------------------------


class MealPlan(Base):
    """One version of a user's plan for `days` days from `start_date`. Replans (M5) add a new
    version (`parent_id` = the plan it replaced); rows are never edited in place, except
    shopping-list ticks and a meal's eaten status."""

    __tablename__ = "meal_plans"
    __table_args__ = (
        UniqueConstraint("user_id", "start_date", "version"),
        Index("ix_meal_plans_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    start_date: Mapped[date] = mapped_column(Date)
    days: Mapped[int] = mapped_column(SmallInteger)
    version: Mapped[int] = mapped_column(Integer)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("meal_plans.id", ondelete="SET NULL"))
    planner: Mapped[str] = mapped_column(String(16))  # cpsat | greedy
    status: Mapped[str] = mapped_column(String(16))  # larder_solver.problem.Status
    objective: Mapped[int | None] = mapped_column(BigInteger)
    solve_ms: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    # Snapshot of everything PlanOut shows that isn't a column (larder_api.planning.PlanStats):
    # targets, cost, pantry use, waste, score terms, violations, notes. Never recomputed.
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    meals: Mapped[list["PlanMeal"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="(PlanMeal.day, PlanMeal.id)"
    )
    shopping: Mapped[list["ShoppingItem"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )


class PlanMeal(Base):
    """A planned meal. `portions` are half-servings (2 = one serving). The macros are a snapshot
    of what the planner and validator used, so old plans never drift when recipes are re-imported.
    """

    __tablename__ = "plan_meals"
    __table_args__ = (UniqueConstraint("plan_id", "day", "slot"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("meal_plans.id", ondelete="CASCADE"))
    day: Mapped[int] = mapped_column(SmallInteger)
    slot: Mapped[str] = mapped_column(String(16))  # breakfast | lunch | dinner | snack
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id"))
    portions: Mapped[int] = mapped_column(SmallInteger)
    kcal: Mapped[int] = mapped_column(Integer)
    protein_g: Mapped[int] = mapped_column(Integer)
    fat_g: Mapped[int] = mapped_column(Integer)
    carbs_g: Mapped[int] = mapped_column(Integer)
    # planned | eaten: set in place when the meal is marked eaten (or undone), like shopping
    # ticks; the active `eaten` meal log is the fact replans count.
    status: Mapped[str] = mapped_column(String(16), default="planned")
    locked: Mapped[bool] = mapped_column(Boolean, default=False)

    plan: Mapped[MealPlan] = relationship(back_populates="meals")
    recipe: Mapped[Recipe] = relationship()


class ShoppingItem(Base):
    """What to buy for a plan: grams beyond what the pantry covers, with an estimated cost.
    Staples (salt, spices, ...) are listed to check, with no grams or cost."""

    __tablename__ = "shopping_items"
    __table_args__ = (UniqueConstraint("plan_id", "food_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("meal_plans.id", ondelete="CASCADE"))
    food_id: Mapped[int] = mapped_column(ForeignKey("foods.id"))
    grams: Mapped[int] = mapped_column(Integer)
    cost_minor: Mapped[int] = mapped_column(Integer)
    staple: Mapped[bool] = mapped_column(Boolean, default=False)
    checked: Mapped[bool] = mapped_column(Boolean, default=False)
    # Bought and moved into the pantry (POST /plans/{id}/shopping/stock); kept across replans.
    stocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    plan: Mapped[MealPlan] = relationship(back_populates="shopping")
    food: Mapped[Food] = relationship()


class PushSubscription(Base):
    """A browser that gets expiry reminders (Web Push): its push service endpoint and keys.
    `last_sent_on` (the user's local date) keeps it to one reminder a day."""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    last_sent_on: Mapped[date | None] = mapped_column(Date)
    recap_sent_on: Mapped[date | None] = mapped_column(Date)  # the Sunday it last went out
    ahead_sent_on: Mapped[date | None] = mapped_column(Date)  # the last evening heads-up
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ShareLink(Base):
    """A public link (/s/<token>) to one recipe, a week's plan, or a week's shopping list (the
    newest version starting on `plan_start`). Recipes and weeks are read-only; a list can be
    ticked off by anyone with the link (shopping together). Shows only the recipe, the meals or
    the list: never pantry, goals, weight or allergies. Revoking it stops the link working."""

    __tablename__ = "share_links"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'recipe' AND recipe_id IS NOT NULL AND plan_start IS NULL)"
            " OR (kind IN ('week', 'list') AND plan_start IS NOT NULL AND recipe_id IS NULL)",
            name="target",  # ck_share_links_target by the naming convention
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(32), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(8))  # recipe | week | list
    recipe_id: Mapped[int | None] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"))
    plan_start: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecipeNote(Base):
    """The user's own note on a recipe ("more chilli") and a 1-5 star rating. Private: shown on
    their recipe page and in cook mode, never on a share link. Ratings don't steer the planner;
    favourites and "never again" do."""

    __tablename__ = "recipe_notes"
    __table_args__ = (CheckConstraint("rating BETWEEN 1 AND 5", name="rating"),)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    recipe_id: Mapped[int] = mapped_column(
        ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True
    )
    note: Mapped[str | None] = mapped_column(Text)
    rating: Mapped[int | None] = mapped_column(SmallInteger)
    updated_at: Mapped[datetime] = _now()


class PlanTemplate(Base):
    """A week of meals saved by name ("busy weeknights") to plan from again. `cells` are
    [{"day": 0-6, "slot", "recipe_id"}], day counted from the template's first day. Planning from
    it checks every recipe again against the user's current allergies, diet and blocks."""

    __tablename__ = "plan_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    cells: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ShoppingExtra(Base):
    """Something the user wants on their shopping list that no plan needs ("bin bags"). Per
    user, not per plan, so it survives replans until bought and cleared."""

    __tablename__ = "shopping_extras"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    checked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- chat and LLM layer (M4) ------------------------------------------------------------------


class ChatThread(Base):
    """A conversation. The client shows the latest thread; "new chat" starts another."""

    __tablename__ = "chat_threads"
    __table_args__ = (Index("ix_chat_threads_user_updated", "user_id", "updated_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = _now()

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan", order_by="ChatMessage.id"
    )


class ChatMessage(Base):
    """One side of a chat turn. `text` is what the user saw; `api_messages` is the exact Messages
    API transcript this row added (the user message with its context block; or the assistant
    responses and tool results), replayed append-only on the next turn of the same `api_epoch`.
    It is JSON, not JSONB, so the replayed bytes (key order) match what was sent and cached.
    Refused turns and turns that never reached the model store `[]` (never replayed); offline
    replies store a plain assistant text message. `attachments` holds the outcome / recipe cards
    shown with the reply, so a reloaded thread looks like the live one."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_thread_id_id", "thread_id", "id"),
        Index(
            "ix_chat_messages_user_created_user_role",
            "user_id",
            "created_at",
            postgresql_where=text("role = 'user'"),
        ),
        Index("ix_chat_messages_plan_id", "plan_id", postgresql_where=text("plan_id IS NOT NULL")),
        UniqueConstraint("user_id", "client_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("chat_threads.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    # The client's id for a user message (idempotent resend); NULL on assistant rows.
    client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # The user's local date when they sent it (user rows): a later message may not go back.
    today: Mapped[date | None] = mapped_column(Date)
    text: Mapped[str] = mapped_column(Text)
    api_messages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # Transcript segment: replay covers only rows of the thread's current epoch. A new epoch
    # starts after an idle gap or when the segment gets long, or after a rejected replay.
    api_epoch: Mapped[int] = mapped_column(Integer, default=0)
    mode: Mapped[str | None] = mapped_column(String(16))  # llm | offline (assistant rows)
    offline_reason: Mapped[str | None] = mapped_column(String(16))  # no_key | budget | model_error
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    suggestions: Mapped[list[str]] = mapped_column(JSONB, default=list)
    # The last plan version this turn created, if any.
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("meal_plans.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    thread: Mapped[ChatThread] = relationship(back_populates="messages")


class Craving(Base):
    """A plan change the user asked for (PLAN §5 "cravings"): any intent - craving, off-plan,
    skip, swap - as typed by the model or the offline parser, and what became of it.
    (message_id, change_key) is unique: the same change applied twice for one message (a
    repeated tool call) returns the first result instead of applying it again."""

    __tablename__ = "cravings"
    __table_args__ = (
        Index("ix_cravings_user_created", "user_id", "created_at"),
        Index("ix_cravings_plan_id", "plan_id", postgresql_where=text("plan_id IS NOT NULL")),
        UniqueConstraint("message_id", "change_key"),
        UniqueConstraint("user_id", "client_id", "change_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="SET NULL")
    )
    # A change made from the plan screen (POST /plans/replan): the request's client id.
    client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    intent: Mapped[str] = mapped_column(String(16))  # craving | ate_off_plan | skip | swap
    raw_text: Mapped[str] = mapped_column(Text)  # the user's message
    parsed: Mapped[dict[str, Any]] = mapped_column(JSONB)  # larder_llm.schemas.Change
    change_key: Mapped[str] = mapped_column(String(64))  # sha256 of the canonical change JSON
    status: Mapped[str] = mapped_column(String(16))  # applied | failed | unchanged
    message: Mapped[str] = mapped_column(Text, default="")  # larder_llm.outcome.ChangeResult
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("meal_plans.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MealLog(Base):
    """Food eaten off-plan, a planned meal skipped, or a planned meal marked eaten. Nutrition
    is computed by the app from USDA data (never taken from a model) and is an estimate unless
    `estimated` is false. A skipped meal stores the planned meal's macros when eaten
    elsewhere, else zeros. Active logs (voided_at IS NULL) are facts every replan rebuilds
    from: their kcal count as eaten on that day and a slotted log keeps that slot free of
    planned meals. A newer slotted log for the same (day, slot), or a craving/swap there after
    a skip, voids the earlier one.

    An `eaten` log (M5, docs/adr/0015) copies the planned meal's macros (`recipe_id`, not an
    estimate) and records in `pantry_taken` exactly what was drawn from the pantry, so undoing
    it (voiding) gives the same amounts back."""

    __tablename__ = "meal_logs"
    __table_args__ = (
        Index("ix_meal_logs_user_eaten_on", "user_id", "eaten_on"),
        Index("ix_meal_logs_plan_id", "plan_id", postgresql_where=text("plan_id IS NOT NULL")),
        Index(
            "ix_meal_logs_craving_id", "craving_id", postgresql_where=text("craving_id IS NOT NULL")
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    eaten_on: Mapped[date] = mapped_column(Date)  # the user's local date
    slot: Mapped[str | None] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))  # off_plan | skipped | eaten
    description: Mapped[str] = mapped_column(Text)
    kcal: Mapped[int] = mapped_column(Integer)
    protein_g: Mapped[int] = mapped_column(Integer)
    fat_g: Mapped[int] = mapped_column(Integer)
    carbs_g: Mapped[int] = mapped_column(Integer)
    estimated: Mapped[bool] = mapped_column(Boolean, default=True)
    # How the estimate was made: [{"name", "food_id", "food", "grams"}].
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    source: Mapped[str] = mapped_column(String(16))  # chat | offline | app
    recipe_id: Mapped[int | None] = mapped_column(ForeignKey("recipes.id", ondelete="SET NULL"))
    # eaten: [{"pantry_item_id", "food_id", "grams", "quantity", "unit"}], amounts taken.
    pantry_taken: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    craving_id: Mapped[int | None] = mapped_column(ForeignKey("cravings.id", ondelete="SET NULL"))
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("meal_plans.id", ondelete="SET NULL"))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LlmCall(Base):
    """One Messages API request: tokens, cost, latency (PLAN §7). Feeds the per-user monthly
    cost cap and the M7/M8 cost-per-plan numbers."""

    __tablename__ = "llm_calls"
    __table_args__ = (
        Index("ix_llm_calls_user_created", "user_id", "created_at"),
        Index(
            "ix_llm_calls_thread_id", "thread_id", postgresql_where=text("thread_id IS NOT NULL")
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    thread_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_threads.id", ondelete="SET NULL")
    )
    purpose: Mapped[str] = mapped_column(String(32))  # chat | choose_food | ...
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_micro_usd: Mapped[int] = mapped_column(BigInteger)
    latency_ms: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))  # ok | refusal | max_tokens | error | cancelled
    request_id: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- pantry intake (M6) -----------------------------------------------------------------------


class ReceiptUpload(Base):
    """A receipt to read: a photo (`source` image) or pasted text. The worker reads it into
    `lines` (docs/adr/0016). Status: queued -> processing -> ready | failed; ready -> confirmed
    once its accepted lines are in the pantry. The photo is kept only until it has been read
    (success or failure), then deleted; the text read from it is dropped on confirm."""

    __tablename__ = "receipt_uploads"
    __table_args__ = (Index("ix_receipt_uploads_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(8))  # image | text
    status: Mapped[str] = mapped_column(
        String(16)
    )  # queued | processing | ready | failed | confirmed
    purchased_on: Mapped[date] = mapped_column(Date)
    text: Mapped[str | None] = mapped_column(Text)  # pasted, or read from the photo
    image: Mapped[bytes | None] = deferred(mapped_column(LargeBinary))  # until read
    image_type: Mapped[str | None] = mapped_column(String(32))  # image/jpeg | image/png | ...
    image_bytes: Mapped[int | None] = mapped_column(Integer)  # the photo's size, kept
    error: Mapped[str | None] = mapped_column(Text)
    read_ms: Mapped[int | None] = mapped_column(Integer)  # OCR + parse + match time
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = _now()
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lines: Mapped[list["ReceiptLine"]] = relationship(
        back_populates="upload",
        order_by="ReceiptLine.position",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ReceiptLine(Base):
    """One item line read from a receipt, with the suggested pantry entry: food (and how it was
    matched), quantity/unit/grams (`approx` when the size wasn't printed), use-by date. Status:
    suggested -> accepted | edited | rejected; confirm turns every accepted, edited or matched
    suggested line into a pantry item (`pantry_item_id`)."""

    __tablename__ = "receipt_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    upload_id: Mapped[int] = mapped_column(
        ForeignKey("receipt_uploads.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(SmallInteger)
    raw_text: Mapped[str] = mapped_column(Text)  # as printed (follow-on lines after " | ")
    name: Mapped[str] = mapped_column(Text)  # cleaned words the matcher used
    food_id: Mapped[int | None] = mapped_column(ForeignKey("foods.id"))
    match_method: Mapped[str | None] = mapped_column(
        String(16)
    )  # receipt|alias|trigram|partial|user
    quantity: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(32))
    grams: Mapped[float | None] = mapped_column(Float)
    approx: Mapped[bool] = mapped_column(Boolean, default=False)
    price_minor: Mapped[int | None] = mapped_column(Integer)
    expires_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="suggested")
    pantry_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("pantry_items.id", ondelete="SET NULL")
    )

    upload: Mapped[ReceiptUpload] = relationship(back_populates="lines")
    food: Mapped[Food | None] = relationship()

"""Relational schema. Quantities are grams; food nutrients are per 100 g.

Data (M1): foods, recipes, embeddings. Users (M2): profile, goals, allergies, pantry; every user
table is keyed or filtered by `user_id`. Plans (M3): versioned weekly plans and shopping lists.
LLM calls arrive with M4.
"""

from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

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
    """Macro columns shared by foods (per 100 g) and recipes (per serving)."""

    kcal: Mapped[float | None] = mapped_column(Float)
    protein_g: Mapped[float | None] = mapped_column(Float)
    fat_g: Mapped[float | None] = mapped_column(Float)
    carbs_g: Mapped[float | None] = mapped_column(Float)
    fiber_g: Mapped[float | None] = mapped_column(Float)
    sugars_g: Mapped[float | None] = mapped_column(Float)
    sat_fat_g: Mapped[float | None] = mapped_column(Float)
    sodium_mg: Mapped[float | None] = mapped_column(Float)


class Food(NutrientColumns, Base):
    """A USDA FoodData Central food. `id` is the FDC id; nutrients are per 100 g."""

    __tablename__ = "foods"
    __table_args__ = (
        # Trigram index for type-ahead food search (pg_trgm).
        Index(
            "ix_foods_description_trgm",
            "description",
            postgresql_using="gin",
            postgresql_ops={"description": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    description: Mapped[str] = mapped_column(Text)
    data_type: Mapped[str] = mapped_column(String(32))  # foundation | sr_legacy
    category: Mapped[str | None] = mapped_column(String(128))

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
    source: Mapped[str] = mapped_column(String(32))  # mealdb | user | generated
    source_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(64))
    cuisine: Mapped[str | None] = mapped_column(String(64))
    instructions: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    servings: Mapped[int | None] = mapped_column(Integer)
    servings_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    # True when every ingredient resolved to a food with grams: only these are plannable.
    nutrition_complete: Mapped[bool] = mapped_column(Boolean, default=False)
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


class Goals(Base):
    """Daily energy/macro bands (validated by larder_core.energy) and a weekly budget."""

    __tablename__ = "goals"

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

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    food_id: Mapped[int] = mapped_column(ForeignKey("foods.id"))
    grams: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(32))
    approx: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_on: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual | receipt (M6)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = _now()

    food: Mapped[Food] = relationship()


# --- plans (M3) -------------------------------------------------------------------------------


class MealPlan(Base):
    """One version of a user's plan for `days` days from `start_date`. Replans (M5) add a new
    version (`parent_id` = the plan it replaced); rows are never edited in place, except
    shopping-list ticks."""

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
    status: Mapped[str] = mapped_column(String(16), default="planned")  # eaten | skipped (M5)
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

    plan: Mapped[MealPlan] = relationship(back_populates="shopping")
    food: Mapped[Food] = relationship()

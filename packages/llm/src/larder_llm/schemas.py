"""The typed contract between the language model and the app.

The model never edits a plan. It asks for *changes* (PLAN §7: craving, ate off-plan, skip, swap)
through tools whose inputs are these models. Deterministic code then checks them (dates inside
the plan, slots, recipe visibility), builds a planning problem with locks, runs the planner and
the independent validator, and saves a new plan version. The same types come out of the offline
rule parser (`larder_llm.rules`), so both paths share one executor.

Tool schemas sent to the API are generated from these models by `larder_llm.tools.tool_schema`,
which keeps only what strict tool use supports; Pydantic re-validates every input here
(lengths, counts, ranges) before anything runs.
"""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from larder_core.meals import Slot

__all__ = [
    "AteOffPlan",
    "Change",
    "Craving",
    "CreateRecipeInput",
    "DraftIngredient",
    "EmptyInput",
    "ExplainMealInput",
    "ExplainPlanDiffInput",
    "OffPlanItem",
    "ReplanInput",
    "SearchRecipesInput",
    "Skip",
    "Swap",
    "When",
]

MAX_CHANGES = 6
MAX_TEXT = 200


class Strict(BaseModel):
    """Closed, immutable input: unknown fields are an error, never silently dropped."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class When(Strict):
    """A day in the user's own calendar (their local date) and optionally one meal of it."""

    date: date
    slot: Slot | None = Field(
        default=None,
        description="breakfast, lunch, dinner or snack. 'Tonight' means dinner.",
    )


# --- plan changes (intents) -------------------------------------------------------------------


class Craving(Strict):
    """The user wants something particular at a meal ("something spicy tonight")."""

    intent: Literal["craving"] = "craving"
    when: When
    dish: str | None = Field(
        default=None, max_length=120, description="A named dish, if any: 'lasagne', 'ramen'."
    )
    tags: list[Annotated[str, Field(max_length=40)]] = Field(
        default_factory=list[str],
        max_length=8,
        description="Qualities to match: 'spicy', 'curry', 'quick', 'light', 'vegetarian'.",
    )
    recipe_id: int | None = Field(
        default=None,
        description="Lock this exact recipe (an id returned by search_recipes or create_recipe).",
    )
    strength: Literal["hard", "soft"] = Field(
        default="soft",
        description=(
            "hard: the user insists; fail and say why if no safe match fits the plan. "
            "soft: a preference; keep the plan if nothing suitable fits."
        ),
    )


class OffPlanItem(Strict):
    name: str = Field(max_length=120, description="'Big Mac', 'pepperoni pizza', 'latte'.")
    quantity: str | None = Field(
        default=None, max_length=40, description="'2 slices', '300 g', '1 large'. Omit if unknown."
    )


class AteOffPlan(Strict):
    """The user ate (or will eat) something that isn't in the plan."""

    intent: Literal["ate_off_plan"] = "ate_off_plan"
    when: When
    description: str = Field(max_length=MAX_TEXT, description="What they said they ate.")
    items: list[OffPlanItem] = Field(
        default_factory=list[OffPlanItem],
        max_length=10,
        description="The foods in it, one per item, when you can tell them apart.",
    )


class Skip(Strict):
    """The user won't eat a planned meal (eating out, not hungry, away)."""

    intent: Literal["skip"] = "skip"
    when: When
    eating_elsewhere: bool = Field(
        default=True,
        description=(
            "True if they will eat a similar meal somewhere else (counted as a meal of the same "
            "size); false if they will not eat at all."
        ),
    )


class Swap(Strict):
    """Replace a planned meal with something else, optionally something particular."""

    intent: Literal["swap"] = "swap"
    when: When
    dish: str | None = Field(default=None, max_length=120)
    tags: list[Annotated[str, Field(max_length=40)]] = Field(
        default_factory=list[str], max_length=8
    )
    recipe_id: int | None = None


Change = Annotated[Craving | AteOffPlan | Skip | Swap, Field(discriminator="intent")]


# --- tool inputs ------------------------------------------------------------------------------


class EmptyInput(Strict):
    """For tools without parameters (get_plan, get_pantry)."""


class SearchRecipesInput(Strict):
    query: str = Field(
        max_length=MAX_TEXT,
        description="Dish names and qualities, e.g. 'spicy chicken curry' or 'quick pasta'.",
    )
    slot: Slot | None = Field(default=None, description="Only recipes that can fill this meal.")
    limit: int = Field(default=5, ge=1, le=10)


class ExplainMealInput(Strict):
    when: When


class ReplanInput(Strict):
    changes: list[Change] = Field(min_length=1, max_length=MAX_CHANGES)


class DraftIngredient(Strict):
    name: str = Field(max_length=120, description="Plain ingredient name: 'red onion'.")
    quantity: str = Field(
        max_length=40, description="Amount with unit for the whole recipe: '200 g', '2 tbsp', '1'."
    )


class CreateRecipeInput(Strict):
    """A recipe the model drafts. Only names and quantities are taken from it: nutrition,
    allergens and diet suitability are computed by the app from USDA data."""

    name: str = Field(max_length=120)
    slot: Slot
    servings: int = Field(ge=1, le=8)
    cuisine: str | None = Field(default=None, max_length=40)
    ingredients: list[DraftIngredient] = Field(min_length=2, max_length=25)
    instructions: str = Field(max_length=4000)


class ExplainPlanDiffInput(Strict):
    plan_id: int | None = Field(
        default=None, description="A plan version; default the current one (vs. its parent)."
    )

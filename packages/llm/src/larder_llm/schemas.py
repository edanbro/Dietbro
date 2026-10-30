"""Typed plan changes: the contract between every screen that changes a plan and the executor.

Nothing edits a plan directly. A screen asks for *changes* (PLAN §7: craving, ate off-plan,
skip, swap). Changes are *facts* (AteOffPlan, Skip: what the user did or will do; always
recorded) or *wishes* (Craving, Swap: preferences; may fail). Deterministic code checks them
(dates, slots, recipe visibility), builds a planning problem, runs the planner and the
independent validator, and saves a new plan version. Pydantic validates every input here
(lengths, counts, ranges) before anything runs. A model, where one is used, only ever fills
these types (structured output) and never sees the plan.
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
    "OffPlanItem",
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

    intent: Literal["craving"]
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
        description="This exact recipe (its id).",
    )
    strength: Literal["hard", "soft"] = Field(
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

    intent: Literal["ate_off_plan"]
    when: When
    description: str = Field(max_length=MAX_TEXT, description="What they said they ate.")
    items: list[OffPlanItem] = Field(
        default_factory=list[OffPlanItem],
        max_length=10,
        description="The foods in it, one per item, when you can tell them apart.",
    )


class Skip(Strict):
    """The user won't eat a planned meal (eating out, not hungry, away)."""

    intent: Literal["skip"]
    when: When
    eating_elsewhere: bool = Field(
        description=(
            "true only if the user said they'll eat somewhere else (eating out, at a friend's, "
            "takeaway): a meal of the same size is counted. false if they won't eat (not hungry, "
            "fasting) or didn't say. Never change it to make a re-plan succeed."
        ),
    )


class Swap(Strict):
    """Replace a planned meal with something else, optionally something particular."""

    intent: Literal["swap"]
    when: When
    dish: str | None = Field(default=None, max_length=120)
    tags: list[Annotated[str, Field(max_length=40)]] = Field(
        default_factory=list[str], max_length=8
    )
    recipe_id: int | None = None


Change = Annotated[Craving | AteOffPlan | Skip | Swap, Field(discriminator="intent")]


# --- recipe drafts ---------------------------------------------------------------------------


class DraftIngredient(Strict):
    name: str = Field(max_length=120, description="Plain ingredient name: 'red onion'.")
    quantity: str = Field(
        max_length=40, description="Amount with unit for the whole recipe: '200 g', '2 tbsp', '1'."
    )


class CreateRecipeInput(Strict):
    """A recipe typed in or read from a web page. Only names and quantities are taken from it:
    nutrition, allergens and diet suitability are computed by the app from USDA data."""

    name: str = Field(max_length=120)
    slot: Slot
    servings: int = Field(ge=1, le=8)
    cuisine: str | None = Field(default=None, max_length=40)
    ingredients: list[DraftIngredient] = Field(min_length=2, max_length=25)
    instructions: str = Field(max_length=4000)

"""The agent's tools (PLAN §7): names, descriptions and strict input schemas.

Handlers live in the API (they need the database and the signed-in user, bound server-side: no
tool takes a user id, so no tool can reach another user's data). This module only describes the
tools and turns the Pydantic input models into schemas the API accepts with `strict: true`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from larder_llm.schemas import (
    CreateRecipeInput,
    EmptyInput,
    ExplainMealInput,
    ExplainPlanDiffInput,
    ReplanInput,
    SearchRecipesInput,
)

__all__ = ["TOOLS", "ToolDef", "api_tools", "tool_schema"]


@dataclass(frozen=True, slots=True)
class ToolDef:
    name: str
    description: str
    input_model: type[BaseModel]
    writes: bool = False  # changes user data (plan versions, recipes, logs)


TOOLS: tuple[ToolDef, ...] = (
    ToolDef(
        "get_plan",
        "The user's current plan: each day's date, meals (recipe id, name, servings, kcal) and "
        "daily totals against their targets. Call it before changing or explaining the plan if "
        "the context block isn't enough.",
        EmptyInput,
    ),
    ToolDef(
        "get_pantry",
        "Food the user has at home, with amounts and expiry dates (soonest first).",
        EmptyInput,
    ),
    ToolDef(
        "search_recipes",
        "Find recipes for a dish or quality ('spicy', 'quick pasta'). Only returns recipes that "
        "are safe for this user (allergies, diet, avoided foods) and can fill the given meal. "
        "Use the returned ids with request_replan.",
        SearchRecipesInput,
    ),
    ToolDef(
        "explain_meal",
        "Why a planned meal was chosen: pantry food it uses (and what's expiring), cost, "
        "calories and protein, liked cuisines.",
        ExplainMealInput,
    ),
    ToolDef(
        "request_replan",
        "Apply what the user told you (cravings, food eaten off-plan, skipped meals, swaps) and "
        "re-plan the rest of the week. The app runs the planner and a safety check and saves a "
        "new plan version; it reports what changed and anything it could not do. Past days are "
        "never changed.",
        ReplanInput,
        writes=True,
    ),
    ToolDef(
        "create_recipe",
        "Draft a new recipe when nothing in search_recipes matches what the user wants. Give "
        "ingredient names and quantities only: the app matches each ingredient to USDA data, "
        "computes nutrition and checks it against the user's allergies and diet, and saves it "
        "for this user only. Returns the recipe id, or the problems to fix.",
        CreateRecipeInput,
        writes=True,
    ),
    ToolDef(
        "explain_plan_diff",
        "What changed between a plan version and the one before it, meal by meal, with reasons.",
        ExplainPlanDiffInput,
    ),
)

# Keywords strict tool schemas don't support; Pydantic still enforces them on our side.
_UNSUPPORTED = frozenset(
    {
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minItems",
        "maxItems",
        "uniqueItems",
        "discriminator",
        "title",
        "default",
    }
)


def _clean(node: Any) -> Any:
    if isinstance(node, list):
        return [_clean(v) for v in node]  # pyright: ignore[reportUnknownVariableType]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for key, value in node.items():  # pyright: ignore[reportUnknownVariableType]
        if key in _UNSUPPORTED:
            continue
        out["anyOf" if key == "oneOf" else key] = _clean(value)
    if out.get("type") == "object":
        out["additionalProperties"] = False
        out.setdefault("properties", {})
    return out


def tool_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The model's JSON schema, reduced to what strict tool use accepts: every object closed
    (`additionalProperties: false`), `oneOf` -> `anyOf`, length/range/count constraints and
    defaults dropped (validated client-side instead)."""
    return _clean(model.model_json_schema(mode="validation"))


def api_tools(defs: Sequence[ToolDef] = TOOLS) -> list[dict[str, Any]]:
    """Tool definitions for the Messages API, in a fixed order (the list is part of the cached
    prompt prefix, so it must be byte-identical across requests)."""
    return [
        {
            "name": d.name,
            "description": d.description,
            "input_schema": tool_schema(d.input_model),
            "strict": True,
        }
        for d in defs
    ]


def by_name(name: str, defs: Sequence[ToolDef] = TOOLS) -> ToolDef | None:
    """Exact match, else an unambiguous case-insensitive one (models occasionally vary case)."""
    exact = next((d for d in defs if d.name == name), None)
    if exact is not None:
        return exact
    folded = [d for d in defs if d.name.casefold() == name.casefold()]
    return folded[0] if len(folded) == 1 else None

"""The agent's tools (PLAN §7): names, descriptions and strict input schemas.

Handlers live in the API (they need the database and the signed-in user, bound server-side: no
tool takes a user id, so no tool can reach another user's data). This module only describes the
tools and turns the Pydantic input models into schemas the API accepts with `strict: true`.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

from pydantic import BaseModel

from larder_llm.schemas import (
    CreateRecipeInput,
    EmptyInput,
    ExplainMealInput,
    ExplainPlanDiffInput,
    ReplanInput,
    SearchRecipesInput,
)

__all__ = ["TOOLS", "ToolDef", "api_tools", "by_name", "tool_schema"]


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

# Limits strict tool schemas don't support. Pydantic still enforces them on our side; the model
# sees them as a hint appended to the description.
_LIMITS = (
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
)
_DROPPED = frozenset({"title", "default", "discriminator"})
_SCHEMA_LISTS = frozenset({"anyOf", "oneOf", "allOf"})
_SCHEMA_ONE = frozenset({"items", "additionalProperties", "not"})

type Schema = dict[str, Any]


def tool_schema(model: type[BaseModel]) -> Schema:
    """The model's JSON schema, reduced to what strict tool use accepts (Pydantic still
    validates everything server-side):

    - every object closed (`additionalProperties: false`); `oneOf` -> `anyOf`; `discriminator`,
      `title`, `default` dropped - only at schema positions, never inside `properties` or
      `$defs` maps (a field named "title" survives);
    - a non-required nullable property (`X | None = None`) is rendered as plain `X` and left out
      of `required` (omitted = None): strict schemas allow at most 24 optional and 16 union-typed
      parameters per request across all tools, and each nullable optional counts as both;
    - every property carrying a `const` (the `intent` discriminator) is required;
    - `minItems` kept when 0 or 1; other limits (`maxLength`, `minimum`/`maximum`, `maxItems`,
      ...) removed and appended to the property's description ("(1-8)", "(at most 6)"), so the
      model sees them.

    Tests: a snapshot of `api_tools()`; no unsupported keyword anywhere; every `anyOf` branch
    under `changes.items` requires its `const`; optional/union counts across all tools (with
    `$ref`s expanded) leave headroom (<= 18 optional, <= 10 union)."""
    raw = model.model_json_schema(mode="validation")
    defs: dict[str, Schema] = raw.get("$defs", {})
    out = _node(raw, defs)
    kept = _used_defs(out)
    if kept:
        out["$defs"] = {name: d for name, d in out["$defs"].items() if name in kept}
    else:
        out.pop("$defs", None)
    return out


def _node(schema: Schema, defs: dict[str, Schema]) -> Schema:
    """One schema position, cleaned."""
    if "$ref" in schema and len(schema) > 1:
        # `{"$ref": ..., "description": ...}`: siblings of `$ref` are not reliably honoured, so
        # inline the target (our definitions are small and never recursive).
        target = defs[str(schema["$ref"]).removeprefix("#/$defs/")]
        schema = {
            **{k: v for k, v in target.items() if k not in ("description", "title")},
            **{k: v for k, v in schema.items() if k != "$ref"},
        }
    required: list[str] = list(schema.get("required", []))
    out: Schema = {}
    for key, value in schema.items():
        if key in _DROPPED or key in _LIMITS:
            continue
        if key == "properties":
            out[key] = {
                name: _node(sub if name in required else _drop_null(sub), defs)
                for name, sub in value.items()
            }
        elif key == "$defs":
            out[key] = {name: _node(sub, defs) for name, sub in value.items()}
        elif key in _SCHEMA_LISTS:
            out["anyOf" if key == "oneOf" else key] = [_node(sub, defs) for sub in value]
        elif key in _SCHEMA_ONE and isinstance(value, dict):
            out[key] = _node(cast(Schema, value), defs)
        else:
            out[key] = value
    if schema.get("minItems") in (0, 1):
        out["minItems"] = schema["minItems"]
    hint = _limits_hint(schema)
    if hint:
        out["description"] = f"{out['description']} ({hint})" if "description" in out else hint
    if out.get("type") == "object":
        props: Schema = out.setdefault("properties", {})
        required += [n for n, p in props.items() if "const" in p and n not in required]
        if required:
            out["required"] = required
        out["additionalProperties"] = False
    return out


def _drop_null(prop: Schema) -> Schema:
    """`anyOf: [X, null]` -> X, keeping the property's own description: an omitted optional
    property means None to Pydantic, so the null branch only costs strict-schema budget."""
    branches: list[Schema] = prop.get("anyOf", [])
    rest = [b for b in branches if b.get("type") != "null"]
    if len(rest) == len(branches):
        return prop
    outer = {k: v for k, v in prop.items() if k != "anyOf"}
    if len(rest) > 1:
        return {**outer, "anyOf": rest}
    return {**rest[0], **outer}


def _limits_hint(schema: Schema) -> str:
    hint = _range_hint(schema)
    default = schema.get("default")
    if isinstance(default, bool | int | str):
        hint = ", ".join(h for h in (hint, f"default {json.dumps(default)}") if h)
    return hint


def _range_hint(schema: Schema) -> str:
    lo, hi = schema.get("minimum"), schema.get("maximum")
    if lo is None and "exclusiveMinimum" in schema:
        lo = f"more than {schema['exclusiveMinimum']}"
    if hi is None and "exclusiveMaximum" in schema:
        hi = f"less than {schema['exclusiveMaximum']}"
    if schema.get("type") == "array":
        lo = schema.get("minItems") if schema.get("minItems", 0) > 1 else None
        hi = schema.get("maxItems")
        return _range(lo, hi, " items")
    if schema.get("type") == "string":
        return _range(schema.get("minLength"), schema.get("maxLength"), " characters")
    return _range(lo, hi, "")


def _range(lo: object, hi: object, unit: str) -> str:
    if lo is not None and hi is not None:
        return f"{lo}-{hi}{unit}"
    if hi is not None:
        return f"at most {hi}{unit}"
    if lo is not None:
        return f"at least {lo}{unit}"
    return ""


def _used_defs(schema: Schema) -> set[str]:
    """Definitions reachable from the schema body (inlined ones drop out)."""
    defs: dict[str, Schema] = schema.get("$defs", {})
    used: set[str] = set()
    todo = _refs({k: v for k, v in schema.items() if k != "$defs"})
    while todo:
        name = todo.pop()
        if name not in used:
            used.add(name)
            todo |= _refs(defs.get(name, {}))
    return used


def _refs(node: object) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in cast(Schema, node).items():
            if key == "$ref" and isinstance(value, str):
                found.add(value.removeprefix("#/$defs/"))
            else:
                found |= _refs(value)
    elif isinstance(node, list):
        for value in cast(list[object], node):
            found |= _refs(value)
    return found


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

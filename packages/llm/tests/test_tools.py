"""Strict tool schemas: what the API accepts, what the model sees, and the complexity budget."""

import json
from typing import Any, cast

import pytest
from pydantic import BaseModel, Field, ValidationError

from larder_llm.schemas import (
    CreateRecipeInput,
    EmptyInput,
    ExplainMealInput,
    ExplainPlanDiffInput,
    ReplanInput,
    SearchRecipesInput,
)
from larder_llm.tools import TOOLS, api_tools, by_name, tool_schema

type Schema = dict[str, Any]

UNSUPPORTED = {
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "maxItems",
    "uniqueItems",
    "discriminator",
    "title",
    "default",
    "oneOf",
}

MINIMAL: dict[type[BaseModel], dict[str, Any]] = {
    EmptyInput: {},
    SearchRecipesInput: {"query": "spicy"},
    ExplainMealInput: {"when": {"date": "2026-10-14"}},
    ReplanInput: {
        "changes": [{"intent": "skip", "when": {"date": "2026-10-14"}, "eating_elsewhere": False}]
    },
    CreateRecipeInput: {
        "name": "Bean chilli",
        "slot": "dinner",
        "servings": 2,
        "ingredients": [
            {"name": "kidney beans", "quantity": "400 g"},
            {"name": "onion", "quantity": "1"},
        ],
        "instructions": "Simmer.",
    },
    ExplainPlanDiffInput: {},
}


def schema_nodes(node: Any, *, maps: bool = False) -> list[Schema]:
    """Every dict at a schema position (property and $defs maps are walked, not visited)."""
    found: list[Schema] = []
    if isinstance(node, dict):
        d = cast(Schema, node)
        if maps:
            for sub in d.values():
                found += schema_nodes(sub)
            return found
        found.append(d)
        for key, value in d.items():
            if key in ("properties", "$defs"):
                found += schema_nodes(value, maps=True)
            elif key in ("anyOf", "allOf"):
                for sub in value:
                    found += schema_nodes(sub)
            elif key == "items":
                found += schema_nodes(value)
    return found


def expand(node: Any, defs: dict[str, Schema]) -> Any:
    if isinstance(node, dict):
        d = cast(Schema, node)
        if "$ref" in d:
            return expand(defs[str(d["$ref"]).removeprefix("#/$defs/")], defs)
        return {k: expand(v, defs) for k, v in d.items() if k != "$defs"}
    if isinstance(node, list):
        return [expand(v, defs) for v in cast(list[Any], node)]
    return node


def count(schema: Schema) -> tuple[int, int]:
    """(optional properties, union-typed nodes) with every $ref expanded at each use."""
    optional = unions = 0
    for node in schema_nodes(expand(schema, schema.get("$defs", {}))):
        if "anyOf" in node or isinstance(node.get("type"), list):
            unions += 1
        if node.get("type") == "object":
            required = set(node.get("required", []))
            optional += sum(1 for name in node["properties"] if name not in required)
    return optional, unions


def test_every_tool_is_strict_and_closed() -> None:
    tools = api_tools()
    assert [t["name"] for t in tools] == [d.name for d in TOOLS]
    for t in tools:
        assert t["strict"] is True
        assert set(t) == {"name", "description", "input_schema", "strict"}
        for node in schema_nodes(t["input_schema"]):
            assert not UNSUPPORTED & set(node), (t["name"], node)
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert "properties" in node
            if "minItems" in node:
                assert node["minItems"] in (0, 1)
            if "$ref" in node:
                assert set(node) == {"$ref"}, "no siblings next to $ref"


def test_snapshot_of_the_replan_schema() -> None:
    schema = tool_schema(ReplanInput)
    defs = schema["$defs"]
    assert set(defs) == {"AteOffPlan", "Craving", "OffPlanItem", "Skip", "Swap", "When"}
    assert schema["properties"]["changes"] == {
        "description": "Everything the user's message asks for, in the order they said it. "
        "(at most 6 items)",
        "items": {
            "anyOf": [{"$ref": f"#/$defs/{n}"} for n in ("Craving", "AteOffPlan", "Skip")]
            + [{"$ref": "#/$defs/Swap"}]
        },
        "type": "array",
        "minItems": 1,
    }
    assert defs["When"]["properties"]["slot"] == {
        "enum": ["breakfast", "lunch", "dinner", "snack"],
        "type": "string",
        "description": "breakfast, lunch, dinner or snack. 'Tonight' means dinner.",
    }
    assert defs["When"]["required"] == ["date"]
    assert defs["Craving"]["properties"]["dish"] == {
        "type": "string",
        "description": "A named dish, if any: 'lasagne', 'ramen'. (at most 120 characters)",
    }
    assert defs["Craving"]["properties"]["tags"]["items"] == {
        "type": "string",
        "description": "at most 40 characters",
    }
    assert defs["Craving"]["required"] == ["intent", "when", "strength"]
    assert defs["Skip"]["required"] == ["intent", "when", "eating_elsewhere"]
    assert defs["OffPlanItem"]["properties"]["quantity"]["type"] == "string"


def test_limits_become_hints() -> None:
    recipe = tool_schema(CreateRecipeInput)["properties"]
    assert recipe["servings"] == {"type": "integer", "description": "1-8"}
    assert recipe["ingredients"]["description"] == "2-25 items"
    assert "minItems" not in recipe["ingredients"]
    assert recipe["cuisine"] == {"type": "string", "description": "at most 40 characters"}
    search = tool_schema(SearchRecipesInput)["properties"]
    assert search["limit"] == {"type": "integer", "description": "1-10, default 5"}
    assert "$defs" not in tool_schema(SearchRecipesInput)  # Slot inlined, unused def pruned


def test_every_change_branch_requires_its_intent() -> None:
    replan = next(t for t in api_tools() if t["name"] == "request_replan")["input_schema"]
    branches = expand(replan, replan["$defs"])["properties"]["changes"]["items"]["anyOf"]
    assert len(branches) == 4
    for branch in branches:
        consts = [n for n, p in branch["properties"].items() if "const" in p]
        assert consts == ["intent"]
        assert "intent" in branch["required"]


def test_complexity_budget_has_headroom() -> None:
    optional = unions = 0
    for t in api_tools():
        o, u = count(t["input_schema"])
        optional, unions = optional + o, unions + u
    assert optional <= 18
    assert unions <= 10
    assert unions == 1  # only changes.items: nullable optionals are plain types


def test_field_names_that_look_like_keywords_survive() -> None:
    class Odd(BaseModel):
        title: str = Field(max_length=10)
        default: int | None = None

    schema = tool_schema(Odd)
    assert set(schema["properties"]) == {"title", "default"}
    title = schema["properties"]["title"]
    assert title == {"type": "string", "description": "at most 10 characters"}
    assert schema["properties"]["default"] == {"type": "integer"}
    assert schema["required"] == ["title"]


def test_schemas_are_byte_stable() -> None:
    assert json.dumps(api_tools()) == json.dumps(api_tools())


@pytest.mark.parametrize("model", list(MINIMAL), ids=lambda m: m.__name__)
def test_input_models_accept_the_minimal_example(model: type[BaseModel]) -> None:
    assert model.model_validate(MINIMAL[model])
    assert any(d.input_model is model for d in TOOLS)


def test_a_change_without_intent_is_rejected() -> None:
    change = {"when": {"date": "2026-10-14", "slot": "dinner"}, "dish": "lasagne"}
    with pytest.raises(ValidationError):
        ReplanInput.model_validate({"changes": [change]})
    with pytest.raises(ValidationError):
        ReplanInput.model_validate({"changes": []})


def test_omitted_optionals_mean_none() -> None:
    parsed = ReplanInput.model_validate(
        {"changes": [{"intent": "craving", "when": {"date": "2026-10-14"}, "strength": "soft"}]}
    )
    change = parsed.changes[0]
    assert change.when.slot is None
    assert change.intent == "craving"
    assert change.dish is None


def test_by_name_matches_exactly_then_unambiguously_ignoring_case() -> None:
    assert by_name("get_plan") is TOOLS[0]
    assert by_name("Get_Plan") is TOOLS[0]
    assert by_name("get-plan") is None
    assert by_name("nope") is None

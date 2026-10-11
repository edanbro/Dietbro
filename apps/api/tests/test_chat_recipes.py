"""Chat helpers that read or write recipes and foods: search_recipes, the recipe guard, food
matching (no caching), off-plan estimates and create_recipe."""

from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, time

import pytest
from safety import assert_user_safe
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_api import planning
from larder_api.chat import foods, offplan
from larder_api.chat.create import create_recipe
from larder_api.chat.handlers import guard_recipe, visible_recipe
from larder_api.chat.scope import ChatScope, Models
from larder_api.chat.search import search_recipes
from larder_api.settings import Settings
from larder_core.meals import Slot
from larder_db import models as db
from larder_db.engine import make_sessionmaker
from larder_llm.client import LLMUnavailable, ModelCall
from larder_llm.fake import ScriptedStructuredModel
from larder_llm.schemas import AteOffPlan, CreateRecipeInput, DraftIngredient, OffPlanItem, When
from larder_solver import Plan, PlanResult, Problem, greedy

TODAY = date(2026, 10, 14)
PIZZA, MUSHROOM, PEANUTS, LENTILS, TOMATO = 1_900_001, 169251, 2515376, 172420, 170457
SALT = 173468

NewUser = Callable[..., Awaitable[int]]
AddRecipe = Callable[..., Awaitable[int]]


def planner(problem: Problem, previous: Plan | None) -> PlanResult:
    return greedy(problem, previous)


def scope_for(
    engine: AsyncEngine, user_id: int, *, fast: ScriptedStructuredModel | None = None
) -> tuple[ChatScope, list[ModelCall]]:
    calls: list[ModelCall] = []

    async def log_call(call: ModelCall) -> None:
        calls.append(call)

    async def emit(_: object) -> None:
        return None

    scope = ChatScope(
        user_id=user_id,
        today=TODAY,
        local_time=time(12, 0),
        now=datetime(2026, 10, 14, 12, tzinfo=UTC),
        thread_id=0,
        message_id=0,
        raw_text="",
        sessionmaker=make_sessionmaker(engine),
        catalog=planning.CatalogCache(),
        planner=planner,
        settings=Settings(),
        models=Models(fast=fast),
        emit=emit,
        log_call=log_call,
    )
    return scope, calls


async def cached_matches(engine: AsyncEngine) -> int:
    async with make_sessionmaker(engine)() as session:
        return await session.scalar(select(func.count()).select_from(db.IngredientMatch)) or 0


# --- search_recipes ---------------------------------------------------------------------------


async def test_search_matches_words_and_qualities(
    db_engine: AsyncEngine, menu: dict[str, int], new_user: NewUser
) -> None:
    scope, _ = scope_for(db_engine, await new_user())

    spicy = await search_recipes(scope, "something spicy", Slot.DINNER)
    lasagne = await search_recipes(scope, "lasagne", None)

    assert {h.name for h in spicy} == {"Chicken curry", "Chilli con carne"}
    assert all("spicy" in h.matched for h in spicy)
    assert [h.name for h in lasagne] == ["Lasagne"]
    assert lasagne[0].kcal_per_serving == 700
    assert lasagne[0].slots == (Slot.LUNCH, Slot.DINNER)


async def test_search_applies_the_planners_hard_filters_and_the_slot(
    db_engine: AsyncEngine, menu: dict[str, int], new_user: NewUser
) -> None:
    scope, _ = scope_for(db_engine, await new_user(allergens=["peanuts"], diet="vegetarian"))

    satay = await search_recipes(scope, "satay peanut rice", None)
    breakfast = await search_recipes(scope, "porridge", Slot.DINNER)

    assert "Satay rice" not in {h.name for h in satay}
    assert all(h.name not in {"Chicken and broccoli rice", "Chicken curry"} for h in satay)
    assert breakfast == []


async def test_search_includes_only_the_users_own_private_recipes(
    db_engine: AsyncEngine, menu: dict[str, int], new_user: NewUser, add_recipe: AddRecipe
) -> None:
    a, b = await new_user("user_a"), await new_user("user_b")
    stew = [("lentil", LENTILS, 240), ("tomato", TOMATO, 600)]
    await add_recipe("Grandma's stew", "Vegetarian", 500, 30, stew, owner=a)

    mine = await search_recipes(scope_for(db_engine, a)[0], "grandma stew", None)
    theirs = await search_recipes(scope_for(db_engine, b)[0], "grandma stew", None)

    assert "Grandma's stew" in {h.name for h in mine}
    assert "Grandma's stew" not in {h.name for h in theirs}


# --- the recipe guard -------------------------------------------------------------------------


async def test_guard_accepts_a_safe_recipe_for_its_slot(
    db_engine: AsyncEngine, menu: dict[str, int], new_user: NewUser
) -> None:
    scope, _ = scope_for(db_engine, await new_user(allergens=["peanuts"]))

    assert await guard_recipe(scope, menu["Lasagne"], Slot.DINNER) is None
    assert await guard_recipe(scope, menu["Lasagne"], Slot.BREAKFAST) == (
        "Lasagne isn't a breakfast recipe."
    )
    reason = await guard_recipe(scope, menu["Satay rice"], Slot.DINNER)
    assert reason is not None
    assert "peanuts" in reason


async def test_another_users_recipe_is_invisible(
    db_engine: AsyncEngine, menu: dict[str, int], new_user: NewUser, add_recipe: AddRecipe
) -> None:
    a, b = await new_user("user_a"), await new_user("user_b")
    stew = [("lentil", LENTILS, 240), ("tomato", TOMATO, 600)]
    secret = await add_recipe("Grandma's stew", "Vegetarian", 500, 30, stew, owner=a)

    assert await visible_recipe(scope_for(db_engine, a)[0], secret) is not None
    assert await visible_recipe(scope_for(db_engine, b)[0], secret) is None
    assert await guard_recipe(scope_for(db_engine, b)[0], secret, Slot.DINNER) == (
        "I can't use that recipe."
    )
    assert await guard_recipe(scope_for(db_engine, b)[0], 424242, Slot.DINNER) == (
        "I can't use that recipe."
    )


# --- foods ------------------------------------------------------------------------------------


@pytest.fixture
async def pizzas(db_engine: AsyncEngine, menu: dict[str, int]) -> tuple[int, int]:
    """Two pizzas no single word tells apart (the takeaway pizza from the menu stays too)."""
    async with make_sessionmaker(db_engine)() as session:
        session.add_all(
            [
                db.Food(id=9001, description="Pizza, pepperoni, frozen", data_type="x", kcal=290),
                db.Food(id=9002, description="Pizza, veggie, frozen", data_type="x", kcal=240),
            ]
        )
        await session.commit()
    return 9001, 9002


async def test_match_food_prefers_curated_aliases_then_a_clear_trigram_winner(
    db_engine: AsyncEngine, menu: dict[str, int], new_user: NewUser
) -> None:
    scope, _ = scope_for(db_engine, await new_user())

    alias = await foods.match_food(scope, "Mushrooms")
    takeaway = await foods.match_food(scope, "cheese pizza")
    nothing = await foods.match_food(scope, "zorblax")

    assert alias == foods.FoodMatch(MUSHROOM, "Mushrooms, white, raw", "alias")
    assert takeaway is not None
    assert (takeaway.food_id, takeaway.method) == (PIZZA, "trigram")
    assert nothing is None
    assert await cached_matches(db_engine) == 0  # chat words never reach the importer's cache


async def test_ambiguous_foods_go_to_the_fast_model_which_can_only_pick_a_candidate(
    db_engine: AsyncEngine, new_user: NewUser, pizzas: tuple[int, int]
) -> None:
    user = await new_user()
    offline, _ = scope_for(db_engine, user)
    picks = ScriptedStructuredModel(
        answers=[foods.FoodPick(food_id=pizzas[1]), foods.FoodPick(food_id=1), LLMUnavailable()]
    )
    online, calls = scope_for(db_engine, user, fast=picks)

    assert await foods.match_food(offline, "pizza") is None
    chosen = await foods.match_food(online, "pizza")
    invented = await foods.match_food(online, "pizza")
    unavailable = await foods.match_food(online, "pizza")

    assert chosen == foods.FoodMatch(pizzas[1], "Pizza, veggie, frozen", "llm")
    assert invented is None
    assert unavailable is None
    assert [c.purpose for c in calls] == ["choose_food"] * 3
    assert "Pizza, pepperoni, frozen" in picks.prompts[0][1]


async def test_grams_from_quantities_and_portions(
    db_engine: AsyncEngine, menu: dict[str, int], new_user: NewUser
) -> None:
    scope, _ = scope_for(db_engine, await new_user())

    assert await foods.grams_for(scope, PIZZA, "2 slices") == (126.0, False)
    assert await foods.grams_for(scope, PIZZA, "300 g") == (300.0, False)
    assert await foods.grams_for(scope, PIZZA, None) == (63.0, True)  # one typical portion
    assert await foods.grams_for(scope, MUSHROOM, None) == (100.0, True)  # no portions known
    assert await foods.grams_for(scope, MUSHROOM, "2 slices") == (50.0, True)  # a generic slice


async def test_off_plan_estimate_falls_back_to_a_typical_meal(
    db_engine: AsyncEngine, menu: dict[str, int], new_user: NewUser
) -> None:
    scope, _ = scope_for(db_engine, await new_user())
    change = AteOffPlan(
        intent="ate_off_plan",
        when=When(date=TODAY, slot=Slot.SNACK),
        description="a zorblax and 2 slices of pizza",
        items=[OffPlanItem(name="zorblax"), OffPlanItem(name="pizza", quantity="2 slices")],
    )

    partly = await offplan.estimate(scope, change)
    unknown = await offplan.estimate(
        scope, change.model_copy(update={"items": [OffPlanItem(name="zorblax")]})
    )

    assert partly.macros.kcal == round(268 * 1.26)
    assert partly.unmatched == ["zorblax"]
    assert partly.estimated
    assert unknown.macros == offplan.TYPICAL_SNACK
    assert unknown.note is not None
    assert "typical snack" in unknown.note


# --- create_recipe ----------------------------------------------------------------------------


def draft(
    name: str = "Chicken and rice",
    *lines: tuple[str, str],
    instructions: str = "Cook the rice; roast the chicken; serve.",
    slot: Slot = Slot.DINNER,
) -> CreateRecipeInput:
    lines = lines or (("chicken", "300 g"), ("rice", "150 g"), ("broccoli", "200 g"))
    return CreateRecipeInput(
        name=name,
        slot=slot,
        servings=2,
        cuisine="British",
        ingredients=[DraftIngredient(name=n, quantity=q) for n, q in lines],
        instructions=instructions,
    )


async def test_created_recipe_is_private_plannable_and_computed_by_us(
    db_engine: AsyncEngine, menu: dict[str, int], new_user: NewUser
) -> None:
    async with make_sessionmaker(db_engine)() as session:
        salt = db.Food(
            id=SALT, description="Salt, table", data_type="x", category="Spices and Herbs", kcal=0
        )
        session.add(salt)
        await session.commit()
    user = await new_user(allergens=["peanuts"])
    scope, _ = scope_for(db_engine, user)

    created = await create_recipe(
        scope,
        draft("Chicken and rice", ("chicken", "300 g"), ("rice", "150 g"), ("salt", "to taste")),
    )

    assert created.problems == []
    assert created.recipe_id is not None
    # 300 g chicken (215 kcal/100 g) + 150 g rice (365) over 2 servings.
    assert created.kcal_per_serving == round((3 * 215 + 1.5 * 365) / 2)
    async with make_sessionmaker(db_engine)() as session:
        private = await planning.load_private_recipes(session, user)
        shared = await planning.load_catalog(session)
        row = await session.get(db.Recipe, created.recipe_id)
        assert row is not None
        assert (row.source, row.owner_user_id, row.nutrition_complete) == ("generated", user, True)
        await assert_user_safe(session, user, TODAY)
    assert created.recipe_id in private.catalog.recipes
    assert created.recipe_id not in shared.catalog.recipes
    assert await guard_recipe(scope, created.recipe_id, Slot.DINNER) is None


@pytest.mark.parametrize(
    ("profile", "recipe", "problem"),
    [
        ({}, draft("Zorblax bake", ("zorblax", "200 g"), ("rice", "100 g")), "couldn't match"),
        ({}, draft("Chicken", ("chicken", "some"), ("rice", "100 g")), "give an amount"),
        (
            {"allergens": ["peanuts"]},
            draft("Pizza bake", ("cheese pizza", "300 g"), ("rice", "100 g")),
            "couldn't verify 'cheese pizza'",
        ),
        (
            {"allergens": ["peanuts"]},
            draft("Peanut chicken", ("chicken", "300 g"), ("rice", "100 g")),
            "peanuts",
        ),
        (
            {"avoid": [MUSHROOM]},
            draft(instructions="Cook the rice, top with sliced mushrooms."),
            "mushrooms, which you avoid",
        ),
        (
            {},
            draft("Rice mountain", ("rice", "1500 g"), ("chicken", "100 g")),
            "too much for one meal",
        ),
        ({}, draft("Oily rice", ("olive oil", "60 g"), ("rice", "100 g")), "too much of it is oil"),
    ],
)
@pytest.mark.usefixtures("foods")  # olive oil
async def test_created_recipes_must_pass_the_planners_own_gate(
    db_engine: AsyncEngine,
    menu: dict[str, int],
    new_user: NewUser,
    profile: dict[str, list[str] | list[int]],
    recipe: CreateRecipeInput,
    problem: str,
) -> None:
    scope, _ = scope_for(db_engine, await new_user(**profile))

    created = await create_recipe(scope, recipe)

    assert created.recipe_id is None
    assert any(problem in p for p in created.problems), created.problems
    async with make_sessionmaker(db_engine)() as session:
        mine = await session.scalar(
            select(func.count(db.Recipe.id)).where(db.Recipe.owner_user_id == scope.user_id)
        )
    assert mine == 0

import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Request
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_api import planning
from larder_api.auth import JWKSCache, TokenVerifier, get_verifier
from larder_api.chat.models import get_models
from larder_api.chat.tasks import ChatTurns, get_chat_turns
from larder_api.clock import get_clock
from larder_api.db import get_sessionmaker
from larder_api.main import app
from larder_api.routers.plans import get_catalog_cache, get_replan_planner
from larder_api.routers.recipes import get_optional_verifier
from larder_api.settings import get_settings
from larder_db.engine import make_sessionmaker
from larder_db.models import (
    Allergies,
    Food,
    FoodPortion,
    Goals,
    Preferences,
    Recipe,
    RecipeIngredient,
    User,
)
from larder_solver import greedy

# Test helpers next to this file (safety.py, chat_support.py) are imported by name.
sys.path.insert(0, str(Path(__file__).parent))
from chat_support import CHAT_PLANNER, ChatEnv
from safety import assert_user_safe

ISSUER = "https://test.clerk.accounts.dev"
ORIGIN = "http://localhost:3000"
KID = "test-key"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
ONION, OLIVE_OIL = 170000, 171413


def jwks(key: rsa.RSAPrivateKey = KEY, kid: str = KID) -> dict[str, Any]:
    public: dict[str, Any] = RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    return {"keys": [public | {"kid": kid, "use": "sig", "alg": "RS256"}]}


def make_token(
    sub: str = "user_a",
    *,
    key: rsa.RSAPrivateKey = KEY,
    kid: str = KID,
    exp_in: int = 300,
    **claims: Any,
) -> str:
    now = int(time.time())
    payload = {
        "sub": sub,
        "iss": ISSUER,
        "iat": now,
        "nbf": now,
        "exp": now + exp_in,
        "azp": ORIGIN,
    }
    return jwt.encode(payload | claims, key, algorithm="RS256", headers={"kid": kid})


def auth_header(sub: str = "user_a") -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub)}"}


type Auth = Callable[..., dict[str, str]]
type Token = Callable[..., str]


@pytest.fixture
def auth() -> Auth:
    """`auth("user_b")` -> Authorization header for that user."""
    return auth_header


@pytest.fixture
def token() -> Token:
    """`token(exp_in=-60, iss=...)` -> a signed session JWT with overridden claims."""
    return make_token


@pytest.fixture
def jwks_calls() -> list[int]:
    return []


@pytest.fixture
async def api(db_engine: AsyncEngine, jwks_calls: list[int]) -> AsyncIterator[httpx.AsyncClient]:
    async def fetch() -> dict[str, Any]:
        jwks_calls.append(1)
        return jwks()

    verifier = TokenVerifier(ISSUER, JWKSCache(fetch, min_refresh_s=0), [ORIGIN])
    maker = make_sessionmaker(db_engine)
    app.dependency_overrides[get_sessionmaker] = lambda: maker
    app.dependency_overrides[get_verifier] = lambda: verifier
    app.dependency_overrides[get_optional_verifier] = lambda: verifier
    # A fresh plannable catalog per test (the app keeps one for CATALOG_TTL_S otherwise).
    app.state.catalog = planning.CatalogCache()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def foods(db_engine: AsyncEngine) -> None:
    async with make_sessionmaker(db_engine)() as session:
        session.add_all(
            [
                Food(
                    id=ONION,
                    description="Onions, raw",
                    data_type="sr_legacy",
                    category="Vegetables and Vegetable Products",
                    kcal=40,
                    portions=[
                        FoodPortion(amount=1, unit="large", grams=150),
                        FoodPortion(amount=1, unit="medium", qualifier='(2-1/2" dia)', grams=110),
                        FoodPortion(amount=1, unit="cup", qualifier="chopped", grams=160),
                    ],
                ),
                Food(
                    id=OLIVE_OIL,
                    description="Oil, olive, salad or cooking",
                    data_type="sr_legacy",
                    category="Fats and Oils",
                    kcal=884,
                    portions=[FoodPortion(amount=1, unit="tbsp", grams=13.5)],
                ),
                Food(id=1, description="Onion rings, frozen", data_type="sr_legacy", kcal=270),
            ]
        )
        await session.commit()


# --- a small catalogue for planning and chat tests --------------------------------------------
# Real FDC ids with curated aliases, so every recipe line is an exact match (reviewed tags).
RICE, BROCCOLI, CHICKEN, PEANUTS, APPLE, LENTILS = 168877, 321900, 171447, 2515376, 171688, 172420
OATS, CHILLI, CURRY_POWDER, PASTA, CHEESE = 173904, 170106, 170924, 169736, 328637
TOMATO, BEEF, MUSHROOM = 170457, 171796, 169251
PIZZA = 1_900_001  # a takeaway food for off-plan estimates (no recipe uses it)

# id, description, category, per 100 g: kcal, protein, fat, carbs
MENU_FOODS: list[tuple[int, str, str, float, float, float, float]] = [
    (
        RICE,
        "Rice, white, long-grain, regular, raw, enriched",
        "Cereal Grains and Pasta",
        365,
        7,
        1,
        80,
    ),
    (BROCCOLI, "Broccoli, raw", "Vegetables and Vegetable Products", 34, 2.8, 0.4, 7),
    (
        CHICKEN,
        "Chicken, broilers or fryers, meat and skin, raw",
        "Poultry Products",
        215,
        18,
        15,
        0,
    ),
    (PEANUTS, "Peanuts, raw", "Legumes and Legume Products", 567, 26, 49, 16),
    (
        APPLE,
        "Apples, raw, with skin (Includes foods for USDA's Food Distribution Program)",
        "Fruits and Fruit Juices",
        52,
        0.3,
        0.2,
        14,
    ),
    (LENTILS, "Lentils, raw", "Legumes and Legume Products", 352, 25, 1, 63),
    (
        OATS,
        "Cereals, oats, regular and quick, not fortified, dry",
        "Breakfast Cereals",
        379,
        13,
        6.5,
        68,
    ),
    (CHILLI, "Peppers, hot chili, red, raw", "Vegetables and Vegetable Products", 40, 1.9, 0.4, 9),
    (CURRY_POWDER, "Spices, curry powder", "Spices and Herbs", 325, 14, 14, 56),
    (PASTA, "Pasta, dry, enriched", "Cereal Grains and Pasta", 371, 13, 1.5, 75),
    (CHEESE, "Cheese, cheddar", "Dairy and Egg Products", 409, 23, 34, 2),
    (
        TOMATO,
        "Tomatoes, red, ripe, raw, year round average",
        "Vegetables and Vegetable Products",
        18,
        0.9,
        0.2,
        3.9,
    ),
    (
        BEEF,
        "Beef, ground, 85% lean meat / 15% fat, raw (Includes foods for USDA's Food Distribution "
        "Program)",
        "Beef Products",
        215,
        18.6,
        15,
        0,
    ),
    (MUSHROOM, "Mushrooms, white, raw", "Vegetables and Vegetable Products", 22, 3.1, 0.3, 3.3),
    (PIZZA, "Pizza, cheese topping, regular crust, frozen, cooked", "Fast Foods", 268, 11, 10, 33),
]
PIZZA_SLICE_G = 63.0

# name, category, kcal and protein per serving, lines (alias name, food, grams for 2 servings)
MENU: list[tuple[str, str, float, float, list[tuple[str, int, float]]]] = [
    ("Porridge", "Breakfast", 380, 14, [("oat", OATS, 200)]),
    ("Oat and apple bowl", "Breakfast", 400, 12, [("oat", OATS, 160), ("apple", APPLE, 300)]),
    ("Rice and apple breakfast", "Breakfast", 420, 9, [("rice", RICE, 160), ("apple", APPLE, 200)]),
    ("Peanut porridge", "Breakfast", 450, 18, [("oat", OATS, 160), ("peanut", PEANUTS, 60)]),
    (
        "Chicken and broccoli rice",
        "Chicken",
        620,
        48,
        [("chicken", CHICKEN, 300), ("broccoli", BROCCOLI, 300), ("rice", RICE, 200)],
    ),
    (
        "Chicken traybake",
        "Chicken",
        560,
        52,
        [("chicken", CHICKEN, 400), ("broccoli", BROCCOLI, 400)],
    ),
    ("Lentil stew", "Vegetarian", 520, 30, [("lentil", LENTILS, 240), ("tomato", TOMATO, 600)]),
    ("Satay rice", "Vegetarian", 650, 25, [("peanut", PEANUTS, 150), ("rice", RICE, 200)]),
    (
        "Chicken curry",
        "Chicken",
        640,
        45,
        [
            ("chicken", CHICKEN, 300),
            ("curry powder", CURRY_POWDER, 10),
            ("chilli", CHILLI, 30),
            ("rice", RICE, 200),
        ],
    ),
    (
        "Chilli con carne",
        "Beef",
        660,
        40,
        [("beef", BEEF, 300), ("chilli", CHILLI, 40), ("tomato", TOMATO, 400), ("rice", RICE, 200)],
    ),
    (
        "Lasagne",
        "Beef",
        700,
        42,
        [
            ("lasagne sheet", PASTA, 200),
            ("beef", BEEF, 300),
            ("cheese", CHEESE, 100),
            ("tomato", TOMATO, 300),
        ],
    ),
    (
        "Mushroom risotto",
        "Vegetarian",
        560,
        18,
        [("rice", RICE, 200), ("mushroom", MUSHROOM, 400), ("cheese", CHEESE, 60)],
    ),
    ("Tomato pasta", "Pasta", 540, 18, [("spaghetti", PASTA, 220), ("tomato", TOMATO, 600)]),
    (
        "Feast platter",
        "Miscellaneous",
        1000,
        70,
        [("beef", BEEF, 500), ("rice", RICE, 300), ("cheese", CHEESE, 150)],
    ),
    ("Apple slices", "Snack", 120, 1, [("apple", APPLE, 460)]),
    ("Apple and peanuts", "Snack", 260, 8, [("apple", APPLE, 300), ("peanut", PEANUTS, 40)]),
]


def menu_recipe(
    name: str,
    category: str,
    kcal: float,
    protein: float,
    lines: list[tuple[str, int, float]],
    *,
    owner: int | None = None,
    complete: bool = True,
    cuisine: str = "British",
) -> Recipe:
    return Recipe(
        source="generated" if owner else "test",
        source_id=f"{owner or 0}:{name}",
        name=name,
        category=category,
        cuisine=cuisine,
        instructions="Cook and serve.",
        servings=2,
        servings_estimated=False,
        nutrition_complete=complete,
        owner_user_id=owner,
        kcal=kcal,
        protein_g=protein,
        fat_g=round(kcal * 0.3 / 9, 1),
        carbs_g=round(kcal * 0.5 / 4, 1),
        ingredients=[
            RecipeIngredient(
                position=i,
                raw_name=raw,
                raw_measure=f"{grams}g",
                food_id=food,
                grams=grams,
                match_method="alias",
            )
            for i, (raw, food, grams) in enumerate(lines)
        ],
    )


@pytest.fixture
async def menu(db_engine: AsyncEngine) -> dict[str, int]:
    """MENU_FOODS and MENU in the database; recipe ids by name."""
    async with make_sessionmaker(db_engine)() as session:
        session.add_all(
            Food(
                id=fid,
                description=d,
                data_type="sr_legacy",
                category=c,
                kcal=k,
                protein_g=p,
                fat_g=f,
                carbs_g=cb,
                portions=[FoodPortion(amount=1, unit="slice", grams=PIZZA_SLICE_G)]
                if fid == PIZZA
                else [],
            )
            for fid, d, c, k, p, f, cb in MENU_FOODS
        )
        recipes = [menu_recipe(*spec) for spec in MENU]
        session.add_all(recipes)
        await session.commit()
        return {r.name: r.id for r in recipes}


type NewUser = Callable[..., Awaitable[int]]


@pytest.fixture
def new_user(db_engine: AsyncEngine) -> NewUser:
    """`await new_user("user_a", allergens=["peanuts"], diet=None, kcal=(1700, 2300))` -> id of
    a user with goals, allergies and preferences set (setup complete)."""

    async def make(
        sub: str = "user_a",
        *,
        allergens: list[str] | None = None,
        avoid: list[int] | None = None,
        diet: str | None = None,
        kcal: tuple[int, int] = (1700, 2300),
        protein: float | None = 90,
        budget: int | None = None,
    ) -> int:
        async with make_sessionmaker(db_engine)() as session:
            user = User(auth_subject=sub)
            session.add(user)
            await session.flush()
            session.add_all(
                [
                    Goals(
                        user_id=user.id,
                        kcal_min=kcal[0],
                        kcal_max=kcal[1],
                        calorie_floor=1200,
                        max_daily_deficit=1000,
                        protein_g_min=protein,
                        weekly_budget_minor=budget,
                        currency="GBP",
                    ),
                    Allergies(
                        user_id=user.id, allergens=allergens or [], avoid_food_ids=avoid or []
                    ),
                    Preferences(
                        user_id=user.id,
                        diet=diet,
                        liked_cuisines=[],
                        disliked_cuisines=[],
                        liked_food_ids=[],
                        disliked_food_ids=[],
                    ),
                ]
            )
            await session.commit()
            return user.id

    return make


type MakePlan = Callable[[int, date], Coroutine[Any, Any, int]]


@pytest.fixture
def make_plan(db_engine: AsyncEngine) -> MakePlan:
    """`await make_plan(user_id, start)` -> id of a new 7-day plan version, made the way
    POST /plans makes one (greedy planner), for any start date."""

    async def make(user_id: int, start: date) -> int:
        async with make_sessionmaker(db_engine)() as session:
            user = await session.get(User, user_id)
            assert user is not None
            inputs = await planning.load_inputs(session, user)
            catalog = await planning.load_catalog(session)
            private = await planning.load_private_recipes(session, user_id)
            latest = await planning.latest_plan(session, user_id)
            version = await planning.next_version(session, user_id, start)
            seed = planning.plan_seed(user_id, start, version)
            problem = planning.make_problem(inputs, catalog, start, seed=seed, private=private)
            result = greedy(problem)
            plan, violations = planning.check_outcome(problem, result)
            stats = planning.plan_stats(
                problem, result, plan, violations, seed=seed, time_limit_ms=0
            )
            prepared = planning.Prepared(problem, version, seed, latest.id if latest else None)
            row = planning.save_plan(
                session,
                user_id,
                prepared,
                result,
                plan,
                stats,
                inputs.goals.currency,
                catalog.unshoppable | private.unshoppable,
            )
            await session.commit()
            return row.id

    return make


type AddRecipe = Callable[..., Awaitable[int]]


@pytest.fixture
def add_recipe(db_engine: AsyncEngine) -> AddRecipe:
    """`await add_recipe(name, category, kcal, protein, lines, owner=None, complete=True,
    cuisine="British")` -> id (see `menu_recipe`; `owner` makes it a private generated one)."""

    async def add(*args: Any, **kwargs: Any) -> int:
        async with make_sessionmaker(db_engine)() as session:
            recipe = menu_recipe(*args, **kwargs)
            session.add(recipe)
            await session.commit()
            return recipe.id

    return add


# --- chat ---------------------------------------------------------------------------------------


@pytest.fixture
async def chat(api: httpx.AsyncClient, db_engine: AsyncEngine) -> AsyncIterator[ChatEnv]:
    """The chat API with its seams pinned for one test (chat_support.ChatEnv). Afterwards every
    user in the database must still be safe (DESIGN §9.6): nothing planned or owned conflicts
    with their allergies, diet or avoided foods."""
    env = ChatEnv(turns=ChatTurns(deadline_s=30), auth=auth_header)

    def chat_turns(request: Request) -> ChatTurns:
        request.app.state.chat_turns = env.turns  # the test's own (it may replace them)
        return get_chat_turns(request)

    overrides: dict[Callable[..., Any], Callable[..., Any]] = {
        get_models: lambda: env.models,
        get_clock: lambda: env.clock,
        get_settings: lambda: env.settings,
        get_catalog_cache: lambda: env.cache,
        get_replan_planner: lambda: CHAT_PLANNER,
        get_chat_turns: chat_turns,
    }
    app.dependency_overrides.update(overrides)
    await env.turns.open()
    yield env
    await env.turns.close()
    app.state.chat_turns = None
    for dependency in overrides:
        app.dependency_overrides.pop(dependency, None)
    async with make_sessionmaker(db_engine)() as session:
        for user_id in list(await session.scalars(select(User.id))):
            await assert_user_safe(session, user_id, env.now.date())

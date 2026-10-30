"""GDPR: GET /me/export holds every row we keep about a user, DELETE /me removes them all and
nobody else's (DESIGN §10). Driven by the schema: a new table with a user_id / owner_user_id
column fails here until it is exported."""

import uuid
from collections.abc import Callable
from datetime import date
from typing import Any

import httpx
from sqlalchemy import Table, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from larder_db import models as db
from larder_db.engine import make_sessionmaker

Auth = Callable[..., dict[str, str]]
ONION = 170000

OWNER_COLUMNS = ("user_id", "owner_user_id")
USER_TABLES = {
    t.name: t for t in db.Base.metadata.sorted_tables if any(c in t.columns for c in OWNER_COLUMNS)
}

type Rows = Callable[[dict[str, Any]], list[dict[str, Any]]]
# Where each user table's rows are in the export.
EXPORTED: dict[str, Rows] = {
    "goals": lambda e: [e["goals"]],
    "body_profiles": lambda e: [e["body"]],
    "body_weights": lambda e: e["weights"],
    "push_subscriptions": lambda e: e["push_subscriptions"],
    "share_links": lambda e: e["share_links"],
    "plan_templates": lambda e: e["plan_templates"],
    "recipe_notes": lambda e: e["recipe_notes"],
    "preferences": lambda e: [e["preferences"]],
    "allergies": lambda e: [e["allergies"]],
    "pantry_items": lambda e: e["pantry"],
    "shopping_extras": lambda e: e["shopping_extras"],
    "meal_plans": lambda e: e["plans"],
    "cravings": lambda e: e["cravings"],
    "meal_logs": lambda e: e["meal_logs"],
    "llm_calls": lambda e: e["llm_calls"],
    "recipes": lambda e: e["recipes"],
    "receipt_uploads": lambda e: e["receipts"],
}


def test_every_table_with_user_data_is_exported() -> None:
    assert set(USER_TABLES) == set(EXPORTED)


async def seed(session: AsyncSession, sub: str) -> dict[str, int]:
    """One row for this user in every user table; table -> the row's id (user id for tables
    keyed by user)."""
    user = db.User(auth_subject=sub)
    session.add(user)
    await session.flush()
    uid = user.id
    recipe = db.Recipe(
        source="generated",
        source_id=f"{sub}-1",
        name=f"{sub}'s onion soup",
        owner_user_id=uid,
        servings=2,
        nutrition_complete=True,
        kcal=300,
        ingredients=[
            db.RecipeIngredient(position=0, raw_name="onion", raw_measure="300 g", food_id=ONION)
        ],
    )
    plan = db.MealPlan(
        user_id=uid,
        start_date=date(2026, 10, 12),
        days=7,
        version=1,
        planner="greedy",
        status="feasible",
        solve_ms=1,
        currency="GBP",
        stats={},
    )
    session.add_all(
        [
            db.Goals(
                user_id=uid,
                kcal_min=1800,
                kcal_max=2200,
                calorie_floor=1200,
                max_daily_deficit=1000,
            ),
            db.BodyProfile(
                user_id=uid,
                sex="female",
                birth_year=1990,
                height_cm=170,
                weight_kg=60,
                activity="moderate",
            ),
            db.BodyWeight(user_id=uid, measured_on=date(2026, 10, 12), weight_kg=60),
            db.Preferences(user_id=uid, liked_cuisines=["Thai"]),
            db.Allergies(user_id=uid, allergens=["peanuts"]),
            recipe,
            plan,
        ]
    )
    await session.flush()
    meal = db.PlanMeal(
        plan_id=plan.id,
        day=0,
        slot="dinner",
        recipe_id=recipe.id,
        portions=2,
        kcal=300,
        protein_g=5,
        fat_g=5,
        carbs_g=40,
    )
    line = db.ShoppingItem(plan_id=plan.id, food_id=ONION, grams=300, cost_minor=30)
    pantry = db.PantryItem(user_id=uid, food_id=ONION, grams=500, quantity=500, unit="g")
    extra = db.ShoppingExtra(user_id=uid, name="bin bags", checked=False)
    push = db.PushSubscription(
        user_id=uid,
        endpoint=f"https://push.example/{sub}",
        p256dh="p" * 20,
        auth="a" * 16,
    )
    session.add_all([meal, line, pantry, extra, push])
    await session.flush()
    craving = db.Craving(
        user_id=uid,
        client_id=uuid.uuid4(),
        intent="ate_off_plan",
        parsed={"intent": "ate_off_plan"},
        change_key="k",
        status="applied",
    )
    session.add(craving)
    await session.flush()
    log = db.MealLog(
        user_id=uid,
        eaten_on=date(2026, 10, 12),
        slot="lunch",
        kind="off_plan",
        description="pizza",
        kcal=800,
        protein_g=30,
        fat_g=30,
        carbs_g=90,
        source="app",
        craving_id=craving.id,
        plan_id=plan.id,
    )
    call = db.LlmCall(
        user_id=uid,
        purpose="choose_food",
        model="claude-sonnet-5-5",
        input_tokens=10,
        output_tokens=5,
        cost_micro_usd=100,
        latency_ms=50,
        status="ok",
    )
    upload = db.ReceiptUpload(
        user_id=uid,
        source="image",
        status="ready",
        purchased_on=date(2026, 10, 12),
        text="ONIONS 1KG 0.95",
        image_type="image/jpeg",
        image_bytes=1234,
        lines=[
            db.ReceiptLine(
                position=0,
                raw_text="ONIONS 1KG 0.95",
                name="onion",
                food_id=ONION,
                match_method="alias",
                quantity=1,
                unit="kg",
                grams=1000,
                approx=False,
                status="suggested",
            )
        ],
    )
    share = db.ShareLink(token=f"share-{sub}", user_id=uid, kind="recipe", recipe_id=recipe.id)
    template = db.PlanTemplate(
        user_id=uid, name="Busy week", cells=[{"day": 0, "slot": "dinner", "recipe_id": recipe.id}]
    )
    note = db.RecipeNote(user_id=uid, recipe_id=recipe.id, note="More chilli", rating=4)
    session.add_all([log, call, upload, share, template, note])
    await session.flush()
    return {
        "goals": uid,
        "body_profiles": uid,
        "body_weights": uid,
        "preferences": uid,
        "allergies": uid,
        "pantry_items": pantry.id,
        "shopping_extras": extra.id,
        "push_subscriptions": push.id,
        "share_links": share.id,
        "plan_templates": template.id,
        "recipe_notes": uid,
        "meal_plans": plan.id,
        "cravings": craving.id,
        "meal_logs": log.id,
        "llm_calls": call.id,
        "recipes": recipe.id,
        "receipt_uploads": upload.id,
    }


async def owned(session: AsyncSession, table: Table, user_id: int) -> int:
    column = next(table.columns[c] for c in OWNER_COLUMNS if c in table.columns)
    return (
        await session.scalar(select(func.count()).select_from(table).where(column == user_id)) or 0
    )


async def test_export_covers_every_table_and_delete_removes_only_that_user(
    api: httpx.AsyncClient, auth: Auth, db_engine: AsyncEngine, foods: None
) -> None:
    async with make_sessionmaker(db_engine)() as session:
        mine, theirs = await seed(session, "user_a"), await seed(session, "user_b")
        await session.commit()
    a, b = mine["goals"], theirs["goals"]
    assert set(mine) == set(USER_TABLES)

    response = await api.get("/me/export", headers=auth("user_a"))

    assert response.status_code == 200
    export = response.json()
    for table, rows in EXPORTED.items():
        found = rows(export)
        assert found, table
        ids = {r.get("id") for r in found if r}
        if "id" in USER_TABLES[table].columns:
            assert mine[table] in ids, table
            assert theirs[table] not in ids, table
    assert export["meal_logs"][0]["description"] == "pizza"
    assert export["recipes"][0]["ingredients"][0]["raw_name"] == "onion"
    assert export["plans"][0]["meals"][0]["recipe_id"] == mine["recipes"]
    assert export["receipts"][0]["lines"][0]["raw_text"] == "ONIONS 1KG 0.95"
    assert not {"p256dh", "auth"} & export["push_subscriptions"][0].keys()  # browser secrets
    assert "image" not in export["receipts"][0]

    assert (await api.delete("/me", headers=auth("user_a"))).status_code == 204

    async with make_sessionmaker(db_engine)() as session:
        for name, table in USER_TABLES.items():
            assert await owned(session, table, a) == 0, name
            assert await owned(session, table, b) == 1, name
        lines = await session.scalar(select(func.count()).select_from(db.ReceiptLine))
        assert lines == 1  # user B's; user A's went with their upload

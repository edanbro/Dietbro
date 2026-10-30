"""Editing recipes (PUT /recipes/{id}): the user's own in place, a catalogue recipe as their own
copy, both through the same checks as a new recipe; and private notes and ratings
(PUT/DELETE /recipes/{id}/note)."""

from collections.abc import Awaitable, Callable, Coroutine
from datetime import date
from typing import Any

import httpx
from app_support import AppEnv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_db import models as db
from larder_db.engine import make_sessionmaker

NewUser = Callable[..., Awaitable[int]]
MakePlan = Callable[[int, date], Coroutine[Any, Any, int]]


def body(*lines: tuple[str, str], name: str = "Chicken and rice") -> dict[str, Any]:
    return {
        "name": name,
        "slot": "dinner",
        "servings": 2,
        "ingredients": [{"name": n, "quantity": q} for n, q in lines],
        "instructions": "Cook the rice. Roast the chicken.",
    }


ORIGINAL = body(("chicken", "300 g"), ("rice", "150 g"), ("broccoli", "200 g"))


async def imported(api: httpx.AsyncClient, env: AppEnv, sub: str = "user_a") -> int:
    response = await api.post("/recipes/import", json=ORIGINAL, headers=env.auth(sub))
    assert response.json()["problems"] == [], response.text
    return response.json()["recipe_id"]


async def test_editing_your_own_recipe_changes_it_in_place(
    api: httpx.AsyncClient, env: AppEnv, menu: dict[str, int], new_user: NewUser
) -> None:
    await new_user("user_a")
    rid = await imported(api, env)
    before = (await api.get(f"/recipes/{rid}", headers=env.auth("user_a"))).json()

    edited = body(("chicken", "300 g"), ("rice", "250 g"), name="Chicken and more rice")
    edited["instructions"] = "Cook the rice for 15 minutes. Fry the chicken for 10 minutes."
    response = await api.put(f"/recipes/{rid}", json=edited, headers=env.auth("user_a"))

    assert response.status_code == 200, response.text
    assert response.json() == {"recipe_id": rid, "problems": [], "copied": False}
    after = (await api.get(f"/recipes/{rid}", headers=env.auth("user_a"))).json()
    assert after["name"] == "Chicken and more rice"
    assert [i["name"] for i in after["ingredients"]] == ["chicken", "rice"]
    assert after["per_serving"]["kcal"] != before["per_serving"]["kcal"]
    assert after["source"] == "imported"  # where it came from stays
    assert (before["minutes"], after["minutes"]) == (30, 25)  # follows the method


async def test_an_unsafe_edit_is_refused_and_changes_nothing(
    api: httpx.AsyncClient, env: AppEnv, menu: dict[str, int], new_user: NewUser
) -> None:
    await new_user("user_a", allergens=["peanuts"])
    rid = await imported(api, env)

    unsafe = body(("chicken", "300 g"), ("rice", "150 g"), ("peanuts", "50 g"))
    response = await api.put(f"/recipes/{rid}", json=unsafe, headers=env.auth("user_a"))

    assert response.status_code == 200
    result = response.json()
    assert result["recipe_id"] is None
    assert result["problems"]
    after = (await api.get(f"/recipes/{rid}", headers=env.auth("user_a"))).json()
    assert [i["name"] for i in after["ingredients"]] == ["chicken", "rice", "broccoli"]


async def test_editing_a_catalogue_recipe_saves_your_own_copy(
    api: httpx.AsyncClient,
    env: AppEnv,
    menu: dict[str, int],
    new_user: NewUser,
    db_engine: AsyncEngine,
) -> None:
    owner = await new_user("user_a")
    original = menu["Chicken and broccoli rice"]

    response = await api.put(
        f"/recipes/{original}",
        json=body(("chicken", "300 g"), ("broccoli", "300 g"), name="My chicken and broccoli"),
        headers=env.auth("user_a"),
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["copied"] is True
    assert result["recipe_id"] not in (None, original)
    async with make_sessionmaker(db_engine)() as session:
        copy = await session.get(db.Recipe, result["recipe_id"])
        kept = await session.get(db.Recipe, original)
        assert copy is not None
        assert kept is not None
        assert (copy.source, copy.owner_user_id) == ("custom", owner)
        assert kept.name == "Chicken and broccoli rice"  # the catalogue's stays as it was
        assert kept.owner_user_id is None


async def test_someone_elses_recipe_cannot_be_edited(
    api: httpx.AsyncClient, env: AppEnv, menu: dict[str, int], new_user: NewUser
) -> None:
    await new_user("user_a")
    await new_user("user_b")
    rid = await imported(api, env, "user_a")

    response = await api.put(f"/recipes/{rid}", json=ORIGINAL, headers=env.auth("user_b"))

    assert response.status_code == 404


async def test_notes_and_ratings_are_private(
    api: httpx.AsyncClient, env: AppEnv, menu: dict[str, int], new_user: NewUser
) -> None:
    await new_user("user_a")
    await new_user("user_b")
    rid = menu["Chicken and broccoli rice"]
    h = env.auth("user_a")

    saved = await api.put(
        f"/recipes/{rid}/note", json={"note": " More chilli ", "rating": 4}, headers=h
    )
    assert saved.status_code == 200, saved.text
    assert (saved.json()["note"], saved.json()["rating"]) == ("More chilli", 4)

    mine = (await api.get(f"/recipes/{rid}", headers=h)).json()
    assert mine["note"]["note"] == "More chilli"
    theirs = (await api.get(f"/recipes/{rid}", headers=env.auth("user_b"))).json()
    assert theirs["note"] is None
    link = (await api.post("/share", json={"kind": "recipe", "recipe_id": rid}, headers=h)).json()
    public = (await api.get(f"/public/share/{link['token']}")).json()
    assert public["recipe"]["note"] is None

    bad = await api.put(f"/recipes/{rid}/note", json={"rating": 6}, headers=h)
    assert bad.status_code == 422

    rating_only = await api.put(f"/recipes/{rid}/note", json={"note": "", "rating": 5}, headers=h)
    assert (rating_only.json()["note"], rating_only.json()["rating"]) == (None, 5)

    cleared = await api.put(f"/recipes/{rid}/note", json={}, headers=h)
    assert cleared.status_code == 200
    assert cleared.json() is None
    assert (await api.get(f"/recipes/{rid}", headers=h)).json()["note"] is None

    await api.put(f"/recipes/{rid}/note", json={"note": "Again"}, headers=h)
    assert (await api.delete(f"/recipes/{rid}/note", headers=h)).status_code == 204
    assert (await api.get(f"/recipes/{rid}", headers=h)).json()["note"] is None
    assert (await api.put("/recipes/999999/note", json={"note": "x"}, headers=h)).status_code == 404


async def test_deleting_your_own_recipe(
    api: httpx.AsyncClient,
    env: AppEnv,
    db_engine: AsyncEngine,
    menu: dict[str, int],
    new_user: NewUser,
    make_plan: MakePlan,
) -> None:
    user_id = await new_user("user_a")
    await new_user("user_b")
    auth = env.auth("user_a")
    plan_id = await make_plan(user_id, date(2026, 10, 12))  # before: it can't plan them
    unused, planned = await imported(api, env), await imported(api, env)
    await api.put(f"/recipes/{planned}/feedback", json={"verdict": "favourite"}, headers=auth)
    async with make_sessionmaker(db_engine)() as session:
        meal = await session.scalar(select(db.PlanMeal).where(db.PlanMeal.plan_id == plan_id))
        assert meal is not None
        meal.recipe_id = planned
        await session.commit()

    not_theirs = await api.delete(f"/recipes/{unused}", headers=env.auth("user_b"))
    catalogue = await api.delete(f"/recipes/{menu['Porridge']}", headers=auth)
    gone = await api.delete(f"/recipes/{unused}", headers=auth)
    hidden = await api.delete(f"/recipes/{planned}", headers=auth)

    assert (not_theirs.status_code, catalogue.status_code) == (404, 404)
    assert gone.json() == {"hidden": False}
    assert (await api.get(f"/recipes/{unused}", headers=auth)).status_code == 404
    # A plan has it: kept for the plan, but never shown or planned again.
    assert hidden.json() == {"hidden": True}
    browse = (await api.get("/recipes", params={"limit": 60}, headers=auth)).json()
    assert planned not in {i["id"] for i in browse["items"]}
    assert (await api.get(f"/recipes/{planned}", headers=auth)).json()["feedback"] == "never"

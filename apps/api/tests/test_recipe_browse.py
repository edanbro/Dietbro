"""Browsing recipes (GET /recipes) and recipe feedback: favourites and "never again"."""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_db.engine import make_sessionmaker
from larder_db.models import PantryItem, Recipe

Auth = Callable[..., dict[str, str]]
NewUser = Callable[..., Awaitable[int]]

pytestmark = pytest.mark.usefixtures("menu")


async def browse(api: httpx.AsyncClient, auth: Auth, **params: str | int | bool) -> Any:
    response = await api.get("/recipes", params=params, headers=auth())
    assert response.status_code == 200, response.text
    return response.json()


def names(page: Any) -> list[str]:
    return [item["name"] for item in page["items"]]


async def test_browse_needs_setup(api: httpx.AsyncClient, auth: Auth) -> None:
    response = await api.get("/recipes", headers=auth())
    assert response.status_code == 409


async def test_browse_lists_only_safe_recipes(
    api: httpx.AsyncClient, auth: Auth, new_user: NewUser
) -> None:
    await new_user("user_a", allergens=["peanuts"])

    page = await browse(api, auth, limit=60)

    assert page["total"] == len(page["items"])
    assert "Porridge" in names(page)
    assert not {"Peanut porridge", "Satay rice"} & set(names(page))


async def test_browse_searches_and_filters_by_slot(
    api: httpx.AsyncClient, auth: Auth, new_user: NewUser
) -> None:
    await new_user("user_a")

    spicy = await browse(api, auth, q="spicy")
    breakfasts = await browse(api, auth, slot="breakfast", limit=60)

    assert names(spicy)[0] == "Chicken curry"
    assert "Porridge" in names(breakfasts)
    assert "Chicken curry" not in names(breakfasts)


async def test_favourites_rank_first_and_never_again_hides(
    api: httpx.AsyncClient, auth: Auth, new_user: NewUser, menu: dict[str, int]
) -> None:
    await new_user("user_a")
    traybake, porridge = menu["Chicken traybake"], menu["Porridge"]

    fav = await api.put(
        f"/recipes/{traybake}/feedback", json={"verdict": "favourite"}, headers=auth()
    )
    never = await api.put(
        f"/recipes/{porridge}/feedback", json={"verdict": "never"}, headers=auth()
    )
    assert (fav.status_code, never.status_code) == (204, 204)

    page = await browse(api, auth, limit=60)
    assert names(page)[0] == "Chicken traybake"
    assert page["items"][0]["favourite"] is True
    assert "Porridge" not in names(page)
    assert names(await browse(api, auth, favourites=True)) == ["Chicken traybake"]
    detail = (await api.get(f"/recipes/{porridge}", headers=auth())).json()
    assert detail["feedback"] == "never"

    # A new verdict replaces the old one; deleting clears it.
    await api.put(f"/recipes/{porridge}/feedback", json={"verdict": "favourite"}, headers=auth())
    assert set(names(await browse(api, auth, favourites=True))) == {"Chicken traybake", "Porridge"}
    assert (await api.delete(f"/recipes/{porridge}/feedback", headers=auth())).status_code == 204
    assert (await api.get(f"/recipes/{porridge}", headers=auth())).json()["feedback"] is None


async def test_feedback_on_a_missing_recipe_is_404(
    api: httpx.AsyncClient, auth: Auth, new_user: NewUser
) -> None:
    await new_user("user_a")
    response = await api.put("/recipes/999999/feedback", json={"verdict": "never"}, headers=auth())
    assert response.status_code == 404


async def test_never_again_recipes_are_not_planned(
    api: httpx.AsyncClient, auth: Auth, new_user: NewUser, menu: dict[str, int]
) -> None:
    await new_user("user_a")
    for name in ("Porridge", "Oat and apple bowl"):
        await api.put(f"/recipes/{menu[name]}/feedback", json={"verdict": "never"}, headers=auth())

    response = await api.post("/plans", json={}, headers=auth())

    assert response.status_code == 201, response.text
    planned = {m["recipe"]["name"] for d in response.json()["days"] for m in d["meals"]}
    assert planned
    assert not {"Porridge", "Oat and apple bowl"} & planned


async def test_recipe_marks_what_is_in_the_pantry(
    api: httpx.AsyncClient, auth: Auth, new_user: NewUser, menu: dict[str, int]
) -> None:
    await new_user("user_a")
    bowl = menu["Oat and apple bowl"]
    before = (await api.get(f"/recipes/{bowl}", headers=auth())).json()
    oats = next(i for i in before["ingredients"] if i["name"] == "oat")
    added = await api.post(
        "/pantry", json={"food_id": oats["food_id"], "quantity": 500, "unit": "g"}, headers=auth()
    )
    assert added.status_code == 201, added.text

    after = (await api.get(f"/recipes/{bowl}", headers=auth())).json()

    assert [i["in_pantry"] for i in before["ingredients"]] == [False, False]
    assert {i["name"]: i["in_pantry"] for i in after["ingredients"]} == {
        "oat": True,
        "apple": False,
    }


async def test_browse_shows_cooking_time_and_filters_quick_recipes(
    api: httpx.AsyncClient,
    auth: Auth,
    new_user: NewUser,
    menu: dict[str, int],
    db_engine: AsyncEngine,
) -> None:
    await new_user("user_a")
    porridge, traybake = menu["Porridge"], menu["Chicken traybake"]
    async with make_sessionmaker(db_engine)() as session:
        for rid, minutes in ((porridge, 10), (traybake, 50)):
            await session.execute(update(Recipe).where(Recipe.id == rid).values(minutes=minutes))
        await session.commit()

    everything = {i["name"]: i for i in (await browse(api, auth, limit=60))["items"]}
    quick = await browse(api, auth, max_minutes=30, limit=60)
    detail = (await api.get(f"/recipes/{porridge}", headers=auth())).json()

    assert everything["Porridge"]["minutes"] == 10
    assert everything["Chicken traybake"]["minutes"] == 50
    # Only recipes known to be quick: one without an estimate isn't.
    assert names(quick) == ["Porridge"]
    assert detail["minutes"] == 10


async def test_cook_from_the_pantry_puts_fewest_foods_to_get_first(
    api: httpx.AsyncClient,
    auth: Auth,
    new_user: NewUser,
    menu: dict[str, int],
    db_engine: AsyncEngine,
) -> None:
    user_id = await new_user("user_a")
    traybake = (await api.get(f"/recipes/{menu['Chicken traybake']}", headers=auth())).json()
    foods = {i["name"]: i["food_id"] for i in traybake["ingredients"]}
    for name in ("chicken", "broccoli"):
        body = {"food_id": foods[name], "quantity": 500, "unit": "g"}
        assert (await api.post("/pantry", json=body, headers=auth())).status_code == 201
    porridge = (await api.get(f"/recipes/{menu['Porridge']}", headers=auth())).json()
    async with make_sessionmaker(db_engine)() as session:  # oats, all used up
        oats = porridge["ingredients"][0]["food_id"]
        session.add(PantryItem(user_id=user_id, food_id=oats, grams=0, quantity=0, unit="g"))
        await session.commit()

    page = await browse(api, auth, pantry=True, limit=60)
    usual = await browse(api, auth, limit=60)
    items = {i["name"]: i for i in page["items"]}

    assert names(page)[:2] == ["Chicken traybake", "Chicken and broccoli rice"]
    assert items["Chicken traybake"]["missing"] == []
    [rice] = items["Chicken and broccoli rice"]["missing"]
    assert rice.startswith("Rice")
    # Only recipes using something in the pantry; a used-up item isn't in it.
    assert all(i["uses_pantry"] for i in page["items"])
    assert "Porridge" not in items
    assert all(i["missing"] is None for i in usual["items"])
    assert not next(i for i in usual["items"] if i["name"] == "Porridge")["uses_pantry"]
    missing = [len(i["missing"]) for i in page["items"]]
    assert missing == sorted(missing)


async def test_recipes_say_what_a_serving_costs(
    api: httpx.AsyncClient, auth: Auth, new_user: NewUser, menu: dict[str, int]
) -> None:
    await new_user("user_a")
    page = await browse(api, auth, limit=60)
    curry = next(i for i in page["items"] if i["name"] == "Chicken curry")
    detail = (await api.get(f"/recipes/{menu['Chicken curry']}", headers=auth())).json()
    signed_out = (await api.get(f"/recipes/{menu['Chicken curry']}")).json()

    assert page["currency"] == "GBP"
    assert all(i["cost_per_serving"] > 0 for i in page["items"])
    # The recipe page and the list price it the same way (the planner's grams and prices).
    assert (detail["cost_per_serving"], detail["currency"]) == (curry["cost_per_serving"], "GBP")
    assert (signed_out["cost_per_serving"], signed_out["currency"]) == (None, None)

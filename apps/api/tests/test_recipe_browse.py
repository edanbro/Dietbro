"""Browsing recipes (GET /recipes) and recipe feedback: favourites and "never again"."""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

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

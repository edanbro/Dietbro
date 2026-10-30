"""Share links (/share, /public/share/{token}): read-only public pages for a recipe or a week."""

from collections.abc import Awaitable, Callable, Coroutine
from datetime import date
from typing import Any

import httpx
import pytest
from app_support import AppEnv

NewUser = Callable[..., Awaitable[int]]
MakePlan = Callable[[int, date], Coroutine[Any, Any, int]]
MON = date(2026, 10, 12)


async def share(api: httpx.AsyncClient, env: AppEnv, sub: str, **body: Any) -> httpx.Response:
    return await api.post("/share", json=body, headers=env.auth(sub))


async def test_a_recipe_link_shows_the_recipe_until_revoked(
    api: httpx.AsyncClient, env: AppEnv, menu: dict[str, int], new_user: NewUser
) -> None:
    await new_user("user_a")
    recipe_id = next(iter(menu.values()))

    first = await share(api, env, "user_a", kind="recipe", recipe_id=recipe_id)
    again = await share(api, env, "user_a", kind="recipe", recipe_id=recipe_id)
    assert first.status_code == 200, first.text
    token = first.json()["token"]
    assert again.json()["token"] == token  # asking twice gives the same link
    assert first.json()["path"] == f"/s/{token}"
    assert len(token) >= 20

    public = await api.get(f"/public/share/{token}")  # no sign-in
    assert public.status_code == 200
    assert public.headers["x-robots-tag"] == "noindex"
    shared = public.json()
    assert shared["kind"] == "recipe"
    assert shared["recipe"]["id"] == recipe_id
    assert shared["recipe"]["feedback"] is None
    assert not any(i["in_pantry"] for i in shared["recipe"]["ingredients"])

    revoked = await api.delete(f"/share/{token}", headers=env.auth("user_a"))
    assert revoked.status_code == 204
    assert (await api.get(f"/public/share/{token}")).status_code == 404
    fresh = await share(api, env, "user_a", kind="recipe", recipe_id=recipe_id)
    assert fresh.json()["token"] != token


async def test_a_week_link_shows_only_the_meals(
    api: httpx.AsyncClient,
    env: AppEnv,
    menu: dict[str, int],
    new_user: NewUser,
    make_plan: MakePlan,
) -> None:
    user_id = await new_user("user_a", allergens=["peanuts"])
    await make_plan(user_id, MON)

    created = await share(api, env, "user_a", kind="week", start=MON.isoformat())
    assert created.status_code == 200, created.text
    shared = (await api.get(f"/public/share/{created.json()['token']}")).json()

    assert set(shared) == {"kind", "recipe", "days", "shopping"}
    assert shared["recipe"] is None
    assert shared["shopping"] is None
    assert shared["days"][0]["date"] == MON.isoformat()
    assert len(shared["days"]) == 7
    meal = shared["days"][0]["meals"][0]
    assert set(meal) == {"slot", "recipe", "kcal"}
    assert set(meal["recipe"]) == {"id", "name", "category", "cuisine", "image_url", "minutes"}
    text = str(shared).lower()
    assert "peanut" not in text  # nothing about the person's allergies


async def test_only_your_own_things_can_be_shared(
    api: httpx.AsyncClient, env: AppEnv, menu: dict[str, int], new_user: NewUser
) -> None:
    await new_user("user_a")
    await new_user("user_b")
    no_plan = await share(api, env, "user_a", kind="week", start=MON.isoformat())
    assert no_plan.status_code == 404
    missing = await share(api, env, "user_a", kind="recipe", recipe_id=999_999)
    assert missing.status_code == 404
    bad = await share(api, env, "user_a", kind="recipe")
    assert bad.status_code == 422

    token = (
        await share(api, env, "user_a", kind="recipe", recipe_id=next(iter(menu.values())))
    ).json()["token"]
    stolen = await api.delete(f"/share/{token}", headers=env.auth("user_b"))
    assert stolen.status_code == 404  # only the owner revokes


@pytest.mark.parametrize("token", ["nope", "x" * 22])
async def test_unknown_links(api: httpx.AsyncClient, token: str) -> None:
    assert (await api.get(f"/public/share/{token}")).status_code == 404


async def test_sharing_needs_sign_in(api: httpx.AsyncClient) -> None:
    assert (await api.post("/share", json={"kind": "recipe", "recipe_id": 1})).status_code == 401


async def list_link(api: httpx.AsyncClient, env: AppEnv, sub: str = "user_a") -> str:
    created = await share(api, env, sub, kind="list", start=MON.isoformat())
    assert created.status_code == 200, created.text
    return created.json()["token"]


async def test_a_shopping_list_link_can_be_ticked_without_signing_in(
    api: httpx.AsyncClient,
    env: AppEnv,
    menu: dict[str, int],
    new_user: NewUser,
    make_plan: MakePlan,
) -> None:
    user_id = await new_user("user_a", allergens=["peanuts"])
    plan_id = await make_plan(user_id, MON)
    extra = await api.post(
        "/shopping/extras", json={"name": "Bin bags"}, headers=env.auth("user_a")
    )
    token = await list_link(api, env)

    public = await api.get(f"/public/share/{token}")
    shared = public.json()
    assert public.headers["cache-control"] == "no-store"  # ticks show up straight away
    assert shared["kind"] == "list"
    listed = shared["shopping"]
    assert listed["start"] == MON.isoformat()
    bought = [i for i in listed["items"] if not i["staple"]]
    assert bought
    assert set(bought[0]) == {
        "food_id",
        "name",
        "category",
        "grams",
        "approx_units",
        "checked",
        "staple",
    }  # no prices
    assert listed["extras"] == [{"id": extra.json()["id"], "name": "Bin bags", "checked": False}]
    assert "peanut" not in str(shared).lower()

    food = bought[0]["food_id"]
    ticked = await api.patch(f"/public/share/{token}/items/{food}", json={"checked": True})
    bagged = await api.patch(
        f"/public/share/{token}/extras/{extra.json()['id']}", json={"checked": True}
    )
    own = (await api.get(f"/plans/{plan_id}/shopping", headers=env.auth("user_a"))).json()
    extras = (await api.get("/shopping/extras", headers=env.auth("user_a"))).json()

    assert ticked.status_code == 200, ticked.text
    assert next(i for i in ticked.json()["items"] if i["food_id"] == food)["checked"] is True
    assert bagged.json()["extras"][0]["checked"] is True
    # The owner sees what was ticked in the shop.
    assert next(i for i in own["items"] if i["food_id"] == food)["checked"] is True
    assert extras[0]["checked"] is True

    await api.delete(f"/share/{token}", headers=env.auth("user_a"))
    again = await api.patch(f"/public/share/{token}/items/{food}", json={"checked": False})
    assert again.status_code == 404


async def test_a_shopping_list_link_follows_the_newest_plan(
    api: httpx.AsyncClient,
    env: AppEnv,
    menu: dict[str, int],
    new_user: NewUser,
    make_plan: MakePlan,
) -> None:
    user_id = await new_user("user_a")
    await make_plan(user_id, MON)
    token = await list_link(api, env)
    newer = await make_plan(user_id, MON)

    own = (await api.get(f"/plans/{newer}/shopping", headers=env.auth("user_a"))).json()
    food = next(i["food_id"] for i in own["items"] if not i["staple"])
    await api.patch(f"/public/share/{token}/items/{food}", json={"checked": True})
    after = (await api.get(f"/plans/{newer}/shopping", headers=env.auth("user_a"))).json()

    assert next(i for i in after["items"] if i["food_id"] == food)["checked"] is True


async def test_a_shopping_list_link_ticks_only_its_own_list(
    api: httpx.AsyncClient,
    env: AppEnv,
    menu: dict[str, int],
    new_user: NewUser,
    make_plan: MakePlan,
) -> None:
    a = await new_user("user_a")
    await new_user("user_b")
    await make_plan(a, MON)
    token = await list_link(api, env)
    week = (await share(api, env, "user_a", kind="week", start=MON.isoformat())).json()["token"]
    theirs = await api.post("/shopping/extras", json={"name": "Milk"}, headers=env.auth("user_b"))
    food = next(
        i["food_id"]
        for i in (await api.get(f"/public/share/{token}")).json()["shopping"]["items"]
        if not i["staple"]
    )

    other_extra = await api.patch(
        f"/public/share/{token}/extras/{theirs.json()['id']}", json={"checked": True}
    )
    not_listed = await api.patch(f"/public/share/{token}/items/999999", json={"checked": True})
    read_only = await api.patch(f"/public/share/{week}/items/{food}", json={"checked": True})
    no_plan = await share(api, env, "user_b", kind="list", start=MON.isoformat())

    assert other_extra.status_code == 404
    assert not_listed.status_code == 404
    assert read_only.status_code == 404  # a week's link shows meals; it ticks nothing
    assert no_plan.status_code == 404
    mine = (await api.get("/shopping/extras", headers=env.auth("user_b"))).json()
    assert mine[0]["checked"] is False

"""Share links (/share, /public/share/{token}): read-only public pages for a recipe or a week."""

from collections.abc import Awaitable, Callable, Coroutine
from datetime import date
from typing import Any

import httpx
import pytest
from chat_support import ChatEnv

NewUser = Callable[..., Awaitable[int]]
MakePlan = Callable[[int, date], Coroutine[Any, Any, int]]
MON = date(2026, 10, 12)


async def share(api: httpx.AsyncClient, chat: ChatEnv, sub: str, **body: Any) -> httpx.Response:
    return await api.post("/share", json=body, headers=chat.auth(sub))


async def test_a_recipe_link_shows_the_recipe_until_revoked(
    api: httpx.AsyncClient, chat: ChatEnv, menu: dict[str, int], new_user: NewUser
) -> None:
    await new_user("user_a")
    recipe_id = next(iter(menu.values()))

    first = await share(api, chat, "user_a", kind="recipe", recipe_id=recipe_id)
    again = await share(api, chat, "user_a", kind="recipe", recipe_id=recipe_id)
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

    revoked = await api.delete(f"/share/{token}", headers=chat.auth("user_a"))
    assert revoked.status_code == 204
    assert (await api.get(f"/public/share/{token}")).status_code == 404
    fresh = await share(api, chat, "user_a", kind="recipe", recipe_id=recipe_id)
    assert fresh.json()["token"] != token


async def test_a_week_link_shows_only_the_meals(
    api: httpx.AsyncClient,
    chat: ChatEnv,
    menu: dict[str, int],
    new_user: NewUser,
    make_plan: MakePlan,
) -> None:
    user_id = await new_user("user_a", allergens=["peanuts"])
    await make_plan(user_id, MON)

    created = await share(api, chat, "user_a", kind="week", start=MON.isoformat())
    assert created.status_code == 200, created.text
    shared = (await api.get(f"/public/share/{created.json()['token']}")).json()

    assert set(shared) == {"kind", "recipe", "days"}
    assert shared["recipe"] is None
    assert shared["days"][0]["date"] == MON.isoformat()
    assert len(shared["days"]) == 7
    meal = shared["days"][0]["meals"][0]
    assert set(meal) == {"slot", "recipe", "kcal"}
    assert set(meal["recipe"]) == {"id", "name", "category", "cuisine", "image_url"}
    text = str(shared).lower()
    assert "peanut" not in text  # nothing about the person's allergies


async def test_only_your_own_things_can_be_shared(
    api: httpx.AsyncClient, chat: ChatEnv, menu: dict[str, int], new_user: NewUser
) -> None:
    await new_user("user_a")
    await new_user("user_b")
    no_plan = await share(api, chat, "user_a", kind="week", start=MON.isoformat())
    assert no_plan.status_code == 404
    missing = await share(api, chat, "user_a", kind="recipe", recipe_id=999_999)
    assert missing.status_code == 404
    bad = await share(api, chat, "user_a", kind="recipe")
    assert bad.status_code == 422

    token = (
        await share(api, chat, "user_a", kind="recipe", recipe_id=next(iter(menu.values())))
    ).json()["token"]
    stolen = await api.delete(f"/share/{token}", headers=chat.auth("user_b"))
    assert stolen.status_code == 404  # only the owner revokes


@pytest.mark.parametrize("token", ["nope", "x" * 22])
async def test_unknown_links(api: httpx.AsyncClient, token: str) -> None:
    assert (await api.get(f"/public/share/{token}")).status_code == 404


async def test_sharing_needs_sign_in(api: httpx.AsyncClient) -> None:
    assert (await api.post("/share", json={"kind": "recipe", "recipe_id": 1})).status_code == 401

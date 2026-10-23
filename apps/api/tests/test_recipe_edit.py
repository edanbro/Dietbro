"""Editing recipes (PUT /recipes/{id}): the user's own in place, a catalogue recipe as their own
copy, both through the same checks as a new recipe; and private notes and ratings
(PUT/DELETE /recipes/{id}/note)."""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from chat_support import ChatEnv
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_db import models as db
from larder_db.engine import make_sessionmaker

NewUser = Callable[..., Awaitable[int]]


def body(*lines: tuple[str, str], name: str = "Chicken and rice") -> dict[str, Any]:
    return {
        "name": name,
        "slot": "dinner",
        "servings": 2,
        "ingredients": [{"name": n, "quantity": q} for n, q in lines],
        "instructions": "Cook the rice. Roast the chicken.",
    }


ORIGINAL = body(("chicken", "300 g"), ("rice", "150 g"), ("broccoli", "200 g"))


async def imported(api: httpx.AsyncClient, chat: ChatEnv, sub: str = "user_a") -> int:
    response = await api.post("/recipes/import", json=ORIGINAL, headers=chat.auth(sub))
    assert response.json()["problems"] == [], response.text
    return response.json()["recipe_id"]


async def test_editing_your_own_recipe_changes_it_in_place(
    api: httpx.AsyncClient, chat: ChatEnv, menu: dict[str, int], new_user: NewUser
) -> None:
    await new_user("user_a")
    rid = await imported(api, chat)
    before = (await api.get(f"/recipes/{rid}", headers=chat.auth("user_a"))).json()

    edited = body(("chicken", "300 g"), ("rice", "250 g"), name="Chicken and more rice")
    edited["instructions"] = "Cook the rice for 15 minutes. Fry the chicken for 10 minutes."
    response = await api.put(f"/recipes/{rid}", json=edited, headers=chat.auth("user_a"))

    assert response.status_code == 200, response.text
    assert response.json() == {"recipe_id": rid, "problems": [], "copied": False}
    after = (await api.get(f"/recipes/{rid}", headers=chat.auth("user_a"))).json()
    assert after["name"] == "Chicken and more rice"
    assert [i["name"] for i in after["ingredients"]] == ["chicken", "rice"]
    assert after["per_serving"]["kcal"] != before["per_serving"]["kcal"]
    assert after["source"] == "imported"  # where it came from stays
    assert (before["minutes"], after["minutes"]) == (30, 25)  # follows the method


async def test_an_unsafe_edit_is_refused_and_changes_nothing(
    api: httpx.AsyncClient, chat: ChatEnv, menu: dict[str, int], new_user: NewUser
) -> None:
    await new_user("user_a", allergens=["peanuts"])
    rid = await imported(api, chat)

    unsafe = body(("chicken", "300 g"), ("rice", "150 g"), ("peanuts", "50 g"))
    response = await api.put(f"/recipes/{rid}", json=unsafe, headers=chat.auth("user_a"))

    assert response.status_code == 200
    result = response.json()
    assert result["recipe_id"] is None
    assert result["problems"]
    after = (await api.get(f"/recipes/{rid}", headers=chat.auth("user_a"))).json()
    assert [i["name"] for i in after["ingredients"]] == ["chicken", "rice", "broccoli"]


async def test_editing_a_catalogue_recipe_saves_your_own_copy(
    api: httpx.AsyncClient,
    chat: ChatEnv,
    menu: dict[str, int],
    new_user: NewUser,
    db_engine: AsyncEngine,
) -> None:
    owner = await new_user("user_a")
    original = menu["Chicken and broccoli rice"]

    response = await api.put(
        f"/recipes/{original}",
        json=body(("chicken", "300 g"), ("broccoli", "300 g"), name="My chicken and broccoli"),
        headers=chat.auth("user_a"),
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
    api: httpx.AsyncClient, chat: ChatEnv, menu: dict[str, int], new_user: NewUser
) -> None:
    await new_user("user_a")
    await new_user("user_b")
    rid = await imported(api, chat, "user_a")

    response = await api.put(f"/recipes/{rid}", json=ORIGINAL, headers=chat.auth("user_b"))

    assert response.status_code == 404


async def test_notes_and_ratings_are_private(
    api: httpx.AsyncClient, chat: ChatEnv, menu: dict[str, int], new_user: NewUser
) -> None:
    await new_user("user_a")
    await new_user("user_b")
    rid = menu["Chicken and broccoli rice"]
    h = chat.auth("user_a")

    saved = await api.put(
        f"/recipes/{rid}/note", json={"note": " More chilli ", "rating": 4}, headers=h
    )
    assert saved.status_code == 200, saved.text
    assert (saved.json()["note"], saved.json()["rating"]) == ("More chilli", 4)

    mine = (await api.get(f"/recipes/{rid}", headers=h)).json()
    assert mine["note"]["note"] == "More chilli"
    theirs = (await api.get(f"/recipes/{rid}", headers=chat.auth("user_b"))).json()
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

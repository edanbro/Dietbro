from collections.abc import Callable
from typing import Any

import httpx
import pytest

Auth = Callable[..., dict[str, str]]


GOALS: dict[str, Any] = {"kcal_min": 1800, "kcal_max": 2200, "protein_g_min": 90}
BODY: dict[str, Any] = {
    "sex": "male",
    "age": 30,
    "height_cm": 180,
    "weight_kg": 80,
    "activity": "moderate",
}


async def test_goals_round_trip(api: httpx.AsyncClient, auth: Auth) -> None:
    assert (await api.get("/me/goals", headers=auth())).json() is None

    put = await api.put("/me/goals", json=GOALS | {"weekly_budget_minor": 6000}, headers=auth())
    got = await api.get("/me/goals", headers=auth())

    assert put.status_code == 200
    assert got.json()["kcal_min"] == 1800
    assert got.json()["calorie_floor"] == 1200
    assert got.json()["currency"] == "GBP"


@pytest.mark.parametrize(
    ("goals", "message"),
    [
        ({"kcal_min": 900, "kcal_max": 1200}, "calorie floor"),
        ({"kcal_min": 1500, "kcal_max": 1600, "calorie_floor": 800}, "can't be below 1000"),
        ({"kcal_min": 2200, "kcal_max": 1800}, "above the daily maximum"),
    ],
)
async def test_unsafe_goals_are_refused(
    api: httpx.AsyncClient, goals: dict[str, Any], message: str, auth: Auth
) -> None:
    response = await api.put("/me/goals", json=goals, headers=auth())

    assert response.status_code == 400
    assert any(message in p for p in response.json()["detail"])


async def test_deficit_is_checked_against_body_stats(api: httpx.AsyncClient, auth: Auth) -> None:
    # TDEE for BODY is ~2759 kcal; 1300 is a ~1460 kcal/day deficit.
    goals = {"kcal_min": 1300, "kcal_max": 1500}
    assert (await api.put("/me/goals", json=goals, headers=auth())).status_code == 200

    await api.put("/me/body", json=BODY, headers=auth())
    response = await api.put("/me/goals", json=goals, headers=auth())

    assert response.status_code == 400
    assert "deficit" in response.json()["detail"][0]


async def test_body_returns_tdee_and_valid_suggestions(api: httpx.AsyncClient, auth: Auth) -> None:
    response = await api.put("/me/body", json=BODY, headers=auth())

    body = response.json()
    assert body["tdee_kcal"] == 2759
    assert body["age"] == 30
    lose = body["suggestions"]["lose"]
    assert (await api.put("/me/goals", json=lose, headers=auth())).status_code == 200


async def test_minors_are_refused(api: httpx.AsyncClient, auth: Auth) -> None:
    response = await api.put("/me/body", json=BODY | {"age": 16}, headers=auth())

    assert response.status_code == 400


async def test_body_can_be_deleted(api: httpx.AsyncClient, auth: Auth) -> None:
    await api.put("/me/body", json=BODY, headers=auth())

    assert (await api.delete("/me/body", headers=auth())).status_code == 204
    assert (await api.get("/me/body", headers=auth())).json() is None


async def test_preferences_and_allergies(api: httpx.AsyncClient, auth: Auth) -> None:
    prefs = {"diet": "vegetarian", "liked_cuisines": ["Italian", "Italian", "Thai"]}
    allergies = {"allergens": ["peanuts", "milk"], "avoid_food_ids": [3, 3]}

    p = await api.put("/me/preferences", json=prefs, headers=auth())
    a = await api.put("/me/allergies", json=allergies, headers=auth())

    assert p.json()["liked_cuisines"] == ["Italian", "Thai"]
    assert a.json() == {"allergens": ["milk", "peanuts"], "avoid_food_ids": [3]}
    assert (
        await api.put("/me/allergies", json={"allergens": ["kale"]}, headers=auth())
    ).status_code == 422


async def test_allergen_list(api: httpx.AsyncClient) -> None:
    response = await api.get("/allergens")

    assert len(response.json()) == 14
    assert {"code": "peanuts", "label": "Peanuts"} in response.json()


async def test_setup_complete_after_goals_allergies_preferences(
    api: httpx.AsyncClient, auth: Auth
) -> None:
    await api.put("/me/goals", json=GOALS, headers=auth())
    await api.put("/me/allergies", json={"allergens": []}, headers=auth())
    await api.put("/me/preferences", json={}, headers=auth())

    me = (await api.get("/me", headers=auth())).json()

    assert me["setup_complete"] is True
    assert me["profile"]["has_body"] is False


async def test_profiles_are_per_user(api: httpx.AsyncClient, auth: Auth) -> None:
    await api.put("/me/goals", json=GOALS, headers=auth("user_a"))

    assert (await api.get("/me/goals", headers=auth("user_b"))).json() is None


async def test_export_and_delete_account(api: httpx.AsyncClient, auth: Auth) -> None:
    await api.put("/me/goals", json=GOALS, headers=auth())
    await api.put("/me/body", json=BODY, headers=auth())
    first_id = (await api.get("/me", headers=auth())).json()["id"]

    export = await api.get("/me/export", headers=auth())
    assert export.headers["content-disposition"].startswith("attachment")
    data = export.json()
    assert data["goals"]["kcal_min"] == 1800
    assert data["body"]["weight_kg"] == 80
    assert data["user"]["id"] == first_id

    assert (await api.delete("/me", headers=auth())).status_code == 204
    me = (await api.get("/me", headers=auth())).json()  # signs in again: a fresh, empty user
    assert me["id"] != first_id
    assert me["profile"]["has_goals"] is False

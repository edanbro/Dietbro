"""The user's own shopping items (not from a plan)."""

from collections.abc import Callable

import httpx

Auth = Callable[..., dict[str, str]]


async def test_extras_round_trip(api: httpx.AsyncClient, auth: Auth) -> None:
    bags = (await api.post("/shopping/extras", json={"name": " bin bags "}, headers=auth())).json()
    await api.post("/shopping/extras", json={"name": "foil"}, headers=auth())

    ticked = await api.patch(
        f"/shopping/extras/{bags['id']}", json={"checked": True}, headers=auth()
    )
    listed = (await api.get("/shopping/extras", headers=auth())).json()

    assert bags["name"] == "bin bags"
    assert ticked.json()["checked"] is True
    assert [(e["name"], e["checked"]) for e in listed] == [("bin bags", True), ("foil", False)]


async def test_clearing_removes_only_ticked_items(api: httpx.AsyncClient, auth: Auth) -> None:
    bags = (await api.post("/shopping/extras", json={"name": "bin bags"}, headers=auth())).json()
    await api.post("/shopping/extras", json={"name": "foil"}, headers=auth())
    await api.patch(f"/shopping/extras/{bags['id']}", json={"checked": True}, headers=auth())

    assert (await api.delete("/shopping/extras", headers=auth())).status_code == 204

    listed = (await api.get("/shopping/extras", headers=auth())).json()
    assert [e["name"] for e in listed] == ["foil"]


async def test_other_users_extras_are_invisible(api: httpx.AsyncClient, auth: Auth) -> None:
    mine = (await api.post("/shopping/extras", json={"name": "foil"}, headers=auth())).json()

    other = auth("user_b")
    assert (await api.get("/shopping/extras", headers=other)).json() == []
    patched = await api.patch(
        f"/shopping/extras/{mine['id']}", json={"checked": True}, headers=other
    )
    deleted = await api.delete(f"/shopping/extras/{mine['id']}", headers=other)
    assert (patched.status_code, deleted.status_code) == (404, 404)


async def test_blank_names_are_refused(api: httpx.AsyncClient, auth: Auth) -> None:
    response = await api.post("/shopping/extras", json={"name": ""}, headers=auth())
    assert response.status_code == 422

"""Importing recipes from web pages: the guarded fetch (larder_api.recipe_import) and the routes
POST /recipes/import/read and POST /recipes/import."""

import gzip
import json
from collections.abc import Awaitable, Callable, Iterable
from typing import cast

import httpx
import pytest
from chat_support import ChatEnv
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_api import recipe_import
from larder_api.recipe_import import ImportError_, fetch_recipe, public_address
from larder_core.recipe_import import ImportedRecipe
from larder_db import models as db
from larder_db.engine import make_sessionmaker

NewUser = Callable[..., Awaitable[int]]

PAGE = (
    "<html><head><script type='application/ld+json'>"
    + json.dumps(
        {
            "@type": "Recipe",
            "name": "Chicken and rice",
            "recipeYield": "2",
            "recipeCategory": "Dinner",
            "recipeIngredient": ["300g chicken breast, diced", "150 g rice", "200g broccoli"],
            "recipeInstructions": "Cook the rice. Roast the chicken.",
            "image": "https://example.com/dish.jpg",
        }
    )
    + "</script></head></html>"
)

DNS = {"example.com": {"93.184.216.34"}, "internal.test": {"10.0.0.5"}}


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    async def resolve(host: str, port: int) -> set[str]:
        if host not in DNS:
            raise OSError("no such host")
        return DNS[host]

    monkeypatch.setattr(recipe_import, "resolve", resolve)


def client(
    routes: dict[str, httpx.Response], seen: list[httpx.Request] | None = None
) -> httpx.AsyncClient:
    """Answers by the address as the user wrote it: the request itself goes to the checked IP,
    with the name in the Host header."""

    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        url = request.url.copy_with(netloc=request.headers["host"].encode())
        canned = routes.get(str(url), httpx.Response(404))
        # A fresh, unread stream each time, as from the network (the fetch reads it raw).
        raw = b"".join(cast(Iterable[bytes], canned.stream))  # as sent, still compressed
        return httpx.Response(
            canned.status_code, headers=canned.headers, stream=httpx.ByteStream(raw)
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


def html(body: str) -> httpx.Response:
    return httpx.Response(200, text=body, headers={"content-type": "text/html; charset=utf-8"})


@pytest.mark.parametrize(
    ("ip", "public"),
    [
        ("93.184.216.34", True),
        ("2606:2800:220:1::1", True),
        ("127.0.0.1", False),
        ("10.1.2.3", False),
        ("192.168.0.1", False),
        ("169.254.169.254", False),  # cloud metadata
        ("::1", False),
        ("::ffff:127.0.0.1", False),
        ("fd00::1", False),
        ("0.0.0.0", False),
        ("64:ff9b::7f00:1", False),  # NAT64 for 127.0.0.1
        ("64:ff9b::a9fe:a9fe", False),  # NAT64 for 169.254.169.254
        ("2002:7f00:1::1", False),  # 6to4 around 127.0.0.1
        ("2002:c0a8:1::1", False),  # 6to4 around 192.168.0.1
        ("2001:0:4136:e378:8000:63bf:3fff:fdd2", False),  # Teredo, client 192.0.2.45
    ],
)
def test_only_public_addresses(ip: str, public: bool) -> None:
    assert public_address(ip) is public


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/recipe",
        "https://internal.test/recipe",  # resolves to a private address
        "https://user:secret@example.com/recipe",
        "https://example.com:8443/recipe",
        "https://nowhere.example/recipe",
    ],
)
async def test_refuses_addresses_it_must_not_fetch(url: str) -> None:
    with pytest.raises(ImportError_):
        await fetch_recipe(url, client({}))


async def test_reads_the_recipe_and_follows_a_public_redirect() -> None:
    routes = {
        "https://example.com/r": httpx.Response(
            301, headers={"location": "https://example.com/recipe"}
        ),
        "https://example.com/recipe": html(PAGE),
    }
    recipe = await fetch_recipe("https://example.com/r", client(routes))
    assert recipe.name == "Chicken and rice"
    assert recipe.ingredients[0] == "300g chicken breast, diced"


async def test_the_connection_goes_to_the_checked_address() -> None:
    seen: list[httpx.Request] = []
    await fetch_recipe(
        "https://example.com/recipe", client({"https://example.com/recipe": html(PAGE)}, seen)
    )
    [request] = seen
    assert request.url.host == "93.184.216.34"  # not a second lookup of the name
    assert request.headers["host"] == "example.com"
    assert request.extensions["sni_hostname"] == "example.com"  # TLS checks the name


async def test_compressed_pages_are_read_and_bombs_are_refused() -> None:
    def gz(body: bytes) -> httpx.Response:
        return httpx.Response(
            200,
            content=gzip.compress(body),
            headers={"content-type": "text/html", "content-encoding": "gzip"},
        )

    routes = {
        "https://example.com/recipe": gz(PAGE.encode()),
        "https://example.com/bomb": gz(b" " * (recipe_import.MAX_BYTES * 5)),
        "https://example.com/br": httpx.Response(
            200, content=b"x", headers={"content-type": "text/html", "content-encoding": "br"}
        ),
    }
    recipe = await fetch_recipe("https://example.com/recipe", client(routes))
    assert recipe.name == "Chicken and rice"
    with pytest.raises(ImportError_, match="too big"):
        await fetch_recipe("https://example.com/bomb", client(routes))
    with pytest.raises(ImportError_, match="can't be read"):
        await fetch_recipe("https://example.com/br", client(routes))


async def test_a_redirect_to_a_private_address_is_refused() -> None:
    routes = {
        "https://example.com/r": httpx.Response(
            302, headers={"location": "https://internal.test/admin"}
        ),
    }
    with pytest.raises(ImportError_, match="can't be used"):
        await fetch_recipe("https://example.com/r", client(routes))


async def test_pages_without_a_recipe_or_not_html() -> None:
    routes = {
        "https://example.com/plain": html("<html>just words</html>"),
        "https://example.com/img": httpx.Response(200, headers={"content-type": "image/png"}),
    }
    with pytest.raises(ImportError_, match="No recipe found"):
        await fetch_recipe("https://example.com/plain", client(routes))
    with pytest.raises(ImportError_, match="isn't a web page"):
        await fetch_recipe("https://example.com/img", client(routes))


# --- routes -------------------------------------------------------------------------------------


async def test_read_route_returns_an_editable_draft(
    api: httpx.AsyncClient, chat: ChatEnv, new_user: NewUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    await new_user("user_a")
    real = recipe_import.fetch_recipe

    async def fetch(url: str) -> ImportedRecipe:
        return await real(url, client({"https://example.com/recipe": html(PAGE)}))

    monkeypatch.setattr(recipe_import, "fetch_recipe", fetch)

    response = await api.post(
        "/recipes/import/read",
        json={"url": "https://example.com/recipe"},
        headers=chat.auth("user_a"),
    )
    assert response.status_code == 200, response.text
    draft = response.json()
    assert (draft["name"], draft["slot"], draft["servings"]) == ("Chicken and rice", "dinner", 2)
    assert [(i["quantity"], i["name"]) for i in draft["ingredients"]] == [
        ("300g", "chicken breast"),
        ("150 g", "rice"),
        ("200g", "broccoli"),
    ]
    assert draft["source_url"] == "https://example.com/recipe"

    refused = await api.post(
        "/recipes/import/read",
        json={"url": "https://internal.test/x"},
        headers=chat.auth("user_a"),
    )
    assert refused.status_code == 422
    assert "can't be used" in refused.json()["detail"]


def body(*lines: tuple[str, str]) -> dict[str, object]:
    return {
        "name": "Chicken and rice",
        "slot": "dinner",
        "servings": 2,
        "ingredients": [{"name": n, "quantity": q} for n, q in lines],
        "instructions": "Cook the rice. Roast the chicken.",
        "image_url": "https://example.com/dish.jpg",
        "source_url": "https://example.com/recipe",
    }


async def test_import_saves_a_private_checked_recipe(
    api: httpx.AsyncClient,
    chat: ChatEnv,
    db_engine: AsyncEngine,
    menu: dict[str, int],
    new_user: NewUser,
) -> None:
    owner = await new_user("user_a")
    await new_user("user_b")

    response = await api.post(
        "/recipes/import",
        json=body(("chicken", "300 g"), ("rice", "150 g"), ("broccoli", "200 g")),
        headers=chat.auth("user_a"),
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["problems"] == []
    async with make_sessionmaker(db_engine)() as session:
        row = await session.get(db.Recipe, result["recipe_id"])
        assert row is not None
        assert (row.source, row.owner_user_id) == ("imported", owner)
        assert row.source_url == "https://example.com/recipe"
        assert row.image_url == "https://example.com/dish.jpg"
    mine = await api.get(f"/recipes/{result['recipe_id']}", headers=chat.auth("user_a"))
    theirs = await api.get(f"/recipes/{result['recipe_id']}", headers=chat.auth("user_b"))
    assert (mine.status_code, theirs.status_code) == (200, 404)


async def test_import_reports_what_to_fix(
    api: httpx.AsyncClient, chat: ChatEnv, menu: dict[str, int], new_user: NewUser
) -> None:
    await new_user("user_a")
    response = await api.post(
        "/recipes/import",
        json=body(("zorblax", "200 g"), ("rice", "150 g")),
        headers=chat.auth("user_a"),
    )
    assert response.status_code == 200
    result = response.json()
    assert result["recipe_id"] is None
    assert any("zorblax" in p for p in result["problems"])

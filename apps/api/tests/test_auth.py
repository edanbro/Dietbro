from collections.abc import Callable
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from larder_api.main import app

Auth = Callable[..., dict[str, str]]
Token = Callable[..., str]

OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


async def test_missing_token_is_401(api: httpx.AsyncClient) -> None:
    response = await api.get("/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "claims",
    [
        pytest.param({"key": OTHER_KEY}, id="bad-signature"),
        pytest.param({"iss": "https://evil.example"}, id="wrong-issuer"),
        pytest.param({"exp_in": -60}, id="expired"),
        pytest.param({"azp": "https://evil.example"}, id="wrong-origin"),
        pytest.param({"kid": "unknown"}, id="unknown-key"),
    ],
)
async def test_invalid_tokens_are_401(
    api: httpx.AsyncClient, token: Token, claims: dict[str, Any]
) -> None:
    response = await api.get("/me", headers={"Authorization": f"Bearer {token(**claims)}"})

    assert response.status_code == 401


async def test_garbage_token_is_401(api: httpx.AsyncClient) -> None:
    response = await api.get("/me", headers={"Authorization": "Bearer not-a-jwt"})

    assert response.status_code == 401


async def test_first_request_creates_the_user_once(api: httpx.AsyncClient, auth: Auth) -> None:
    first = await api.get("/me", headers=auth("user_a"))
    second = await api.get("/me", headers=auth("user_a"))
    other = await api.get("/me", headers=auth("user_b"))

    assert first.status_code == 200
    assert first.json()["id"] == second.json()["id"] != other.json()["id"]
    assert first.json()["setup_complete"] is False


async def test_signing_keys_are_cached(
    api: httpx.AsyncClient, auth: Auth, jwks_calls: list[int]
) -> None:
    for _ in range(3):
        await api.get("/me", headers=auth())

    assert len(jwks_calls) == 1


async def test_auth_not_configured_is_503(auth: Auth) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/me", headers=auth())

    assert response.status_code == 503

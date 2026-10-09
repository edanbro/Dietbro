import time
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_api.auth import JWKSCache, TokenVerifier, get_verifier
from larder_api.db import get_sessionmaker
from larder_api.main import app
from larder_db.engine import make_sessionmaker
from larder_db.models import Food, FoodPortion

ISSUER = "https://test.clerk.accounts.dev"
ORIGIN = "http://localhost:3000"
KID = "test-key"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
ONION, OLIVE_OIL = 170000, 171413


def jwks(key: rsa.RSAPrivateKey = KEY, kid: str = KID) -> dict[str, Any]:
    public: dict[str, Any] = RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    return {"keys": [public | {"kid": kid, "use": "sig", "alg": "RS256"}]}


def make_token(
    sub: str = "user_a",
    *,
    key: rsa.RSAPrivateKey = KEY,
    kid: str = KID,
    exp_in: int = 300,
    **claims: Any,
) -> str:
    now = int(time.time())
    payload = {
        "sub": sub,
        "iss": ISSUER,
        "iat": now,
        "nbf": now,
        "exp": now + exp_in,
        "azp": ORIGIN,
    }
    return jwt.encode(payload | claims, key, algorithm="RS256", headers={"kid": kid})


def auth_header(sub: str = "user_a") -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub)}"}


type Auth = Callable[..., dict[str, str]]
type Token = Callable[..., str]


@pytest.fixture
def auth() -> Auth:
    """`auth("user_b")` -> Authorization header for that user."""
    return auth_header


@pytest.fixture
def token() -> Token:
    """`token(exp_in=-60, iss=...)` -> a signed session JWT with overridden claims."""
    return make_token


@pytest.fixture
def jwks_calls() -> list[int]:
    return []


@pytest.fixture
async def api(db_engine: AsyncEngine, jwks_calls: list[int]) -> AsyncIterator[httpx.AsyncClient]:
    async def fetch() -> dict[str, Any]:
        jwks_calls.append(1)
        return jwks()

    verifier = TokenVerifier(ISSUER, JWKSCache(fetch, min_refresh_s=0), [ORIGIN])
    maker = make_sessionmaker(db_engine)
    app.dependency_overrides[get_sessionmaker] = lambda: maker
    app.dependency_overrides[get_verifier] = lambda: verifier
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def foods(db_engine: AsyncEngine) -> None:
    async with make_sessionmaker(db_engine)() as session:
        session.add_all(
            [
                Food(
                    id=ONION,
                    description="Onions, raw",
                    data_type="sr_legacy",
                    category="Vegetables and Vegetable Products",
                    kcal=40,
                    portions=[
                        FoodPortion(amount=1, unit="large", grams=150),
                        FoodPortion(amount=1, unit="medium", qualifier='(2-1/2" dia)', grams=110),
                        FoodPortion(amount=1, unit="cup", qualifier="chopped", grams=160),
                    ],
                ),
                Food(
                    id=OLIVE_OIL,
                    description="Oil, olive, salad or cooking",
                    data_type="sr_legacy",
                    category="Fats and Oils",
                    kcal=884,
                    portions=[FoodPortion(amount=1, unit="tbsp", grams=13.5)],
                ),
                Food(id=1, description="Onion rings, frozen", data_type="sr_legacy", kcal=270),
            ]
        )
        await session.commit()

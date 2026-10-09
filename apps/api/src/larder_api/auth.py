"""Authentication: verify Clerk session JWTs and map them to a local user.

The web app sends `Authorization: Bearer <session token>`. We check the RS256 signature against
the Clerk instance's JWKS, plus `iss`, `exp`/`nbf` and `azp` (the origin the token was minted
for). The JWT `sub` is the Clerk user id; the first authenticated request creates our `users`
row. Every user-data query then filters by that row's id (see routers).
"""

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, cast

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from larder_api.db import get_session
from larder_db.models import User

logger = logging.getLogger(__name__)

type FetchJWKS = Callable[[], Awaitable[dict[str, Any]]]


class AuthError(Exception):
    pass


@dataclass
class JWKSCache:
    """Signing keys by `kid`, refetched hourly or when an unknown `kid` appears (rate-limited)."""

    fetch: FetchJWKS
    ttl_s: float = 3600
    min_refresh_s: float = 30
    _keys: dict[str, jwt.PyJWK] = field(default_factory=dict[str, jwt.PyJWK])
    _fetched_at: float = 0.0

    async def key(self, kid: str) -> jwt.PyJWK:
        now = time.monotonic()
        stale = now - self._fetched_at > self.ttl_s
        unknown = kid not in self._keys and now - self._fetched_at > self.min_refresh_s
        if stale or unknown:
            jwks = await self.fetch()
            self._keys = {k["kid"]: jwt.PyJWK(k) for k in jwks.get("keys", []) if k.get("kid")}
            self._fetched_at = now
        if kid not in self._keys:
            raise AuthError("unknown signing key")
        return self._keys[kid]


@dataclass
class TokenVerifier:
    issuer: str
    jwks: JWKSCache
    authorized_parties: list[str]
    leeway_s: float = 5

    async def subject(self, token: str) -> str:
        try:
            kid = jwt.get_unverified_header(token).get("kid")
            if not isinstance(kid, str):
                raise AuthError("token has no key id")
            key = await self.jwks.key(kid)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                issuer=self.issuer,
                leeway=self.leeway_s,
                options={"require": ["exp", "iat", "iss", "sub"], "verify_aud": False},
            )
        except jwt.InvalidTokenError as exc:
            raise AuthError(str(exc)) from exc
        azp = claims.get("azp")
        if self.authorized_parties and azp is not None and azp not in self.authorized_parties:
            raise AuthError("token minted for another origin")
        return cast(str, claims["sub"])


def get_verifier(request: Request) -> TokenVerifier:
    verifier: TokenVerifier | None = getattr(request.app.state, "verifier", None)
    if verifier is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "authentication is not configured")
    return verifier


_bearer = HTTPBearer(auto_error=False)


async def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    verifier: Annotated[TokenVerifier, Depends(get_verifier)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "not signed in", headers={"WWW-Authenticate": "Bearer"}
    )
    if credentials is None:
        raise unauthorized
    try:
        subject = await verifier.subject(credentials.credentials)
    except AuthError as exc:
        logger.info("rejected token: %s", exc)
        raise unauthorized from exc
    stmt = insert(User).values(auth_subject=subject)
    stmt = stmt.on_conflict_do_update(
        index_elements=[User.auth_subject], set_={"last_seen_at": func.now()}
    ).returning(User)
    user = (await session.scalars(stmt, execution_options={"populate_existing": True})).one()
    await session.commit()
    return user


CurrentUser = Annotated[User, Depends(current_user)]

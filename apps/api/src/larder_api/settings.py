import base64
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from the environment (and `.env` when present)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://larder:larder@localhost:5432/larder"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = ["http://localhost:3000"]

    # Clerk: the instance's Frontend API URL, e.g. https://your-app.clerk.accounts.dev.
    # Session JWTs must carry it as `iss`; signing keys come from its JWKS endpoint.
    # If unset, it is derived from the publishable key (which encodes that URL).
    clerk_issuer: str | None = None
    clerk_publishable_key: str | None = None
    clerk_jwks_url: str | None = None  # default: {clerk_issuer}/.well-known/jwks.json
    # Origins allowed in the token's `azp` claim (defaults to cors_origins).
    clerk_authorized_parties: list[str] | None = None

    # Planning (docs/adr/0009-planning-contract.md). auto = CP-SAT, falling back to the greedy
    # baseline while solve() is unimplemented or when it finds no plan in time.
    planner: Literal["auto", "cpsat", "greedy"] = "auto"
    plan_time_limit_ms: int = 3_500
    plan_workers: int = 4
    plan_concurrency: int = 2  # plans solved at once per process
    plan_candidates: int = 40  # recipes per slot after the prefilter

    @property
    def issuer(self) -> str | None:
        if self.clerk_issuer:
            return self.clerk_issuer.rstrip("/")
        if self.clerk_publishable_key:
            return issuer_from_publishable_key(self.clerk_publishable_key)
        return None

    @property
    def jwks_url(self) -> str | None:
        if self.clerk_jwks_url:
            return self.clerk_jwks_url
        return f"{self.issuer}/.well-known/jwks.json" if self.issuer else None


def issuer_from_publishable_key(key: str) -> str:
    """`pk_test_<base64("my-app.clerk.accounts.dev$")>` -> `https://my-app.clerk.accounts.dev`."""
    encoded = key.split("_", 2)[-1]
    domain = base64.b64decode(encoded + "=" * (-len(encoded) % 4)).decode().rstrip("$")
    return f"https://{domain}"


@lru_cache
def get_settings() -> Settings:
    return Settings()

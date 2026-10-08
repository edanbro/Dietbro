from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from the environment (and `.env` when present)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://larder:larder@localhost:5432/larder"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = ["http://localhost:3000"]

    # Clerk: the instance's Frontend API URL, e.g. https://your-app.clerk.accounts.dev.
    # Session JWTs must carry it as `iss`; signing keys come from its JWKS endpoint.
    clerk_issuer: str | None = None
    clerk_jwks_url: str | None = None  # default: {clerk_issuer}/.well-known/jwks.json
    # Origins allowed in the token's `azp` claim (defaults to cors_origins).
    clerk_authorized_parties: list[str] | None = None

    @property
    def jwks_url(self) -> str | None:
        if self.clerk_jwks_url:
            return self.clerk_jwks_url
        return (
            f"{self.clerk_issuer.rstrip('/')}/.well-known/jwks.json" if self.clerk_issuer else None
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()

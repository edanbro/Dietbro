import base64
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator
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
    # baseline when it finds no plan in time.
    planner: Literal["auto", "cpsat", "greedy"] = "auto"
    plan_time_limit_ms: int = 3_500
    plan_workers: int = 4
    plan_concurrency: int = 2  # plans solved at once per process
    plan_candidates: int = 40  # recipes per slot after the prefilter

    # LLM layer (docs/adr/0013-llm-layer.md). Without a key (or with llm_mode=offline) the chat
    # still works: a rule-based parser and templated replies, same plan changes.
    anthropic_api_key: SecretStr | None = None
    llm_mode: Literal["auto", "offline"] = "auto"
    llm_chat_model: str = "claude-sonnet-5-5"  # the conversational agent
    llm_fast_model: str = "claude-haiku-5-5"  # small structured choices (which USDA food?)
    llm_chat_effort: Literal["low", "medium", "high"] = "low"
    llm_max_rounds: int = 6  # model responses per chat turn
    llm_timeout_s: float = 30.0  # per request (connect 5 s); the SDK retries once
    # Per-user limits (costs from llm_calls). Messages: 60 per rolling 24 h (HTTP 429), offline
    # turns included (they run the planner). Model budget: $1 per calendar month (UTC), paced -
    # the model is used while today's spend is under what's left of the month divided by the
    # days left - and at most $0.10 per turn; otherwise the turn runs offline.
    # Expiry reminders (Web Push, larder_api.reminders). Off unless both VAPID keys are set:
    # generate them with `uv run larder-vapid` and keep them in .env only.
    vapid_public_key: str | None = None  # base64url, uncompressed P-256 point (for browsers)
    vapid_private_key: SecretStr | None = None  # base64url raw private key
    vapid_subject: str = "mailto:admin@localhost"  # who push services contact about abuse
    reminder_hour: int = 9  # local time
    recap_hour: int = 18  # the weekly recap, Sundays, local time
    ahead_hour: int = 19  # the evening heads-up for tomorrow's meals, local time

    # Hosting without a separate worker (free tiers, larder_api.inline): pasted receipts are read
    # in the API process and periodic jobs run on a minute ticker; receipt photos are refused.
    worker_in_api: bool = False
    # The public demo account (larder_api.demo): its Clerk user id. Reset nightly, chat offline,
    # can't be deleted. The web app needs the same id (DEMO_CLERK_USER_ID) to sign visitors in.
    demo_auth_subject: str | None = None

    llm_monthly_cap_usd: float = 1.0
    llm_turn_cap_usd: float = 0.10
    llm_daily_messages: int = 60
    # A chat turn runs detached from the HTTP stream, under this deadline (and the turn lock
    # expires after deadline + 30 s).
    chat_turn_deadline_s: float = 90.0
    # Transcript epochs: replay the thread's current epoch only while its last message is newer
    # than this and the epoch is under the token estimate; otherwise start a new epoch.
    chat_epoch_idle_min: int = 30
    chat_epoch_max_tokens: int = 12_000
    replan_time_limit_ms: int = 1_000  # per planner run in a replan (at most 3 runs)

    # Pantry intake (docs/adr/0016-receipt-intake.md). The API stores the upload and enqueues
    # it on Redis (arq); the worker reads it (OCR for photos) and writes the lines.
    receipt_daily_uploads: int = 20  # per user per rolling 24 h, photos and text (HTTP 429)
    receipt_max_image_bytes: int = 8_000_000  # JPEG, PNG or WebP (HTTP 413 above)
    receipt_job_timeout_s: int = 120
    receipt_stale_after_min: int = 15  # queued/processing longer than this is marked failed
    ocr_max_side_px: int = 2_000  # photos are scaled down to this before OCR

    # Barcode lookups for products not imported yet (Open Food Facts product API). Off unless a
    # User-Agent is set: OFF asks for "AppName/Version (contact email)". Only the barcode is sent.
    off_user_agent: str | None = None
    off_base_url: str = "https://world.openfoodfacts.org"
    off_rate_per_min: int = 12  # all users together (OFF allows 15 product reads per minute)
    barcode_lookups_per_hour: int = 30  # per user, lookups that reach OFF

    # Rate limits (larder_api.ratelimit): on by default; a rule's limit can be changed by name,
    # e.g. RATE_LIMIT_OVERRIDES='{"import_read": 100}'. Behind our own proxies (Render, Fly...)
    # set TRUSTED_PROXY_HOPS to how many there are, so client addresses come from
    # X-Forwarded-For; otherwise the socket peer is used and the header ignored.
    rate_limits: bool = True
    rate_limit_overrides: dict[str, int] = {}
    trusted_proxy_hops: int = 0

    @field_validator(
        "anthropic_api_key",
        "clerk_issuer",
        "clerk_publishable_key",
        "clerk_jwks_url",
        "off_user_agent",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        """Compose passes optional variables as "" when they aren't set (`${VAR:-}`): treat that
        as unset, not as an empty key (the chat would try Claude without one)."""
        return None if isinstance(value, str) and not value.strip() else value

    @property
    def llm_enabled(self) -> bool:
        return self.llm_mode == "auto" and self.anthropic_api_key is not None

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

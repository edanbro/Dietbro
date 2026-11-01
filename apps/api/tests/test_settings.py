import re
from pathlib import Path

import pytest

from larder_api.changes.models import get_models
from larder_api.planning import CATALOG_TTL_S, CatalogCache
from larder_api.settings import Settings, issuer_from_publishable_key


@pytest.mark.parametrize(
    ("key", "issuer"),
    [
        (
            "pk_test_Zm9vLWJhci0xMi5jbGVyay5hY2NvdW50cy5kZXYk",
            "https://foo-bar-12.clerk.accounts.dev",
        ),
        ("pk_live_Y2xlcmsuZXhhbXBsZS5jb20k", "https://clerk.example.com"),
    ],
)
def test_issuer_from_publishable_key(key: str, issuer: str) -> None:
    assert issuer_from_publishable_key(key) == issuer


def test_explicit_issuer_wins() -> None:
    s = Settings(
        clerk_issuer="https://a.example/",
        clerk_publishable_key="pk_live_Y2xlcmsuZXhhbXBsZS5jb20k",
    )
    assert s.issuer == "https://a.example"
    assert s.jwks_url == "https://a.example/.well-known/jwks.json"


def test_no_clerk_config_means_no_auth() -> None:
    s = Settings(clerk_issuer=None, clerk_publishable_key=None)
    assert s.issuer is None
    assert s.jwks_url is None


def test_blank_anthropic_key_means_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    # compose.yaml passes `ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}`: "" when unset.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    s = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    assert s.anthropic_api_key is None
    assert not s.llm_enabled
    assert get_models(s).fast is None


def test_blank_clerk_values_are_unset() -> None:
    s = Settings(clerk_issuer="", clerk_publishable_key="  ", _env_file=None)  # pyright: ignore[reportCallIssue]
    assert s.issuer is None


def test_the_catalogue_is_kept_as_long_as_the_host_sets() -> None:
    assert Settings().catalog_ttl_s == CATALOG_TTL_S
    assert CatalogCache(Settings(catalog_ttl_s=86_400).catalog_ttl_s).ttl_s == 86_400


def test_the_blueprint_gives_a_slow_host_time_to_plan() -> None:
    """0.1 CPU needs 15 s to plan as well as 0.5 CPU does in 3.5 s (docs/deploy.md). Below that,
    plans cost twice as much and miss hard limits, with nothing to say so."""
    blueprint = (Path(__file__).parents[3] / "render.yaml").read_text(encoding="utf-8")
    assert re.search(r'key: PLAN_TIME_LIMIT_MS\s+value: "15000"', blueprint)
    assert re.search(r'key: REPLAN_TIME_LIMIT_MS\s+value: "3000"', blueprint)
    assert re.search(r'key: CATALOG_TTL_S\s+value: "86400"', blueprint)


def test_the_blueprint_starts_without_shell_quoting() -> None:
    """Render keeps quotes in dockerCommand literally, so a quoted command fails with status 127."""
    root = Path(__file__).parents[3]
    blueprint = (root / "render.yaml").read_text(encoding="utf-8")
    assert "dockerCommand: sh /app/start.sh" in blueprint
    assert (root / "apps/api/start.sh").is_file()

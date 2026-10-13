import pytest

from larder_api.chat.models import get_models
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
    assert get_models(s).offline_reason == "no_key"
    assert get_models(s).chat is None


def test_blank_clerk_values_are_unset() -> None:
    s = Settings(clerk_issuer="", clerk_publishable_key="  ", _env_file=None)  # pyright: ignore[reportCallIssue]
    assert s.issuer is None

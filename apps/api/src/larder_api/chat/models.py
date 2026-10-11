"""Model clients from settings, as a FastAPI dependency the tests override with fakes."""

from functools import lru_cache
from typing import Annotated

import anthropic
from fastapi import Depends

from larder_api.chat.scope import Models
from larder_api.settings import Settings, get_settings
from larder_llm.client import AnthropicChatModel, AnthropicStructuredModel


@lru_cache(maxsize=4)
def _client(api_key: str, timeout_s: float) -> anthropic.AsyncAnthropic:
    """One client (one connection pool) per process."""
    return anthropic.AsyncAnthropic(
        api_key=api_key, timeout=anthropic.Timeout(timeout_s, connect=5), max_retries=1
    )


def get_models(settings: Annotated[Settings, Depends(get_settings)]) -> Models:
    """Real Claude clients when `settings.llm_enabled`, else `Models(offline_reason="no_key")`.
    One `anthropic.AsyncAnthropic(api_key=..., timeout=Timeout(settings.llm_timeout_s,
    connect=5), max_retries=1)` per process (cached), shared by the chat (`llm_chat_model`,
    `llm_chat_effort`) and fast (`llm_fast_model`) clients. The per-user budget is applied by
    the gate (limits.budget), which may switch a turn offline. Tests override this."""
    key = settings.anthropic_api_key
    if not settings.llm_enabled or key is None:
        return Models(offline_reason="no_key")
    client = _client(key.get_secret_value(), settings.llm_timeout_s)
    return Models(
        chat=AnthropicChatModel(client, settings.llm_chat_model, effort=settings.llm_chat_effort),
        fast=AnthropicStructuredModel(client, settings.llm_fast_model),
    )

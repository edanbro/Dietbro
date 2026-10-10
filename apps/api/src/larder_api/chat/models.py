"""Model clients from settings, as a FastAPI dependency the tests override with fakes."""

from typing import Annotated

from fastapi import Depends

from larder_api.chat.scope import Models
from larder_api.settings import Settings, get_settings


def get_models(settings: Annotated[Settings, Depends(get_settings)]) -> Models:
    """Real Claude clients when `settings.llm_enabled`, else `Models(offline_reason="no_key")`.
    One `anthropic.AsyncAnthropic(api_key=..., timeout=Timeout(settings.llm_timeout_s,
    connect=5), max_retries=1)` per process (cached), shared by the chat (`llm_chat_model`,
    `llm_chat_effort`) and fast (`llm_fast_model`) clients. The per-user budget is applied by
    the gate (limits.budget), which may switch a turn offline. Tests override this."""
    raise NotImplementedError

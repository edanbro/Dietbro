"""Model clients from settings, as a FastAPI dependency the tests override with fakes."""

from typing import Annotated

from fastapi import Depends

from larder_api.chat.scope import Models
from larder_api.settings import Settings, get_settings


def get_models(settings: Annotated[Settings, Depends(get_settings)]) -> Models:
    """Real Claude clients when `settings.llm_enabled`, else offline `Models()`. One
    `anthropic.AsyncAnthropic(api_key=..., timeout=settings.llm_timeout_s)` per process
    (cached), shared by the chat (`llm_chat_model`, `llm_chat_effort`) and fast
    (`llm_fast_model`) clients. The per-user cost cap is applied later (limits.py), not here."""
    raise NotImplementedError

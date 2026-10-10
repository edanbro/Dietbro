"""What one chat turn's tools are bound to: the signed-in user, the database, the planner and
the models. Tool handlers receive this, never a user id from the model."""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from larder_api import planning
from larder_api.settings import Settings
from larder_db import models as db
from larder_llm.client import ChatModel, ModelCall, StructuredModel
from larder_llm.outcome import ReplanOutcome


@dataclass(frozen=True, slots=True)
class Models:
    """`None` everywhere = offline (no key, llm_mode=offline, or over the user's cost cap)."""

    chat: ChatModel | None = None
    fast: StructuredModel | None = None

    @property
    def online(self) -> bool:
        return self.chat is not None


@dataclass(slots=True)
class ChatScope:
    user: db.User
    today: date  # the user's local date for this turn
    thread_id: int
    message_id: int  # the user's chat message this turn answers
    raw_text: str  # the user's words (stored with each change request)
    sessionmaker: async_sessionmaker[AsyncSession]
    catalog: planning.CatalogCache
    planner: planning.Planner
    settings: Settings
    models: Models
    # Collected during the turn, persisted at the end:
    calls: list[ModelCall] = field(default_factory=list[ModelCall])  # -> llm_calls
    outcomes: list[ReplanOutcome] = field(default_factory=list[ReplanOutcome])  # -> plan events
    created_recipes: list[tuple[int, str]] = field(default_factory=list[tuple[int, str]])

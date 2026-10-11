"""The chat API under test (used by conftest's `chat` fixture and the test_chat* modules):
scripted (or no) models, a settable clock, settings that ignore the environment, the greedy
planner, and a ChatTurns task group of the test's own. Plans made with `make_plan(user, MON)` run
Monday 12 to Sunday 18 Oct 2026; it is Wednesday 14 Oct, 12:00 UTC."""

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Any

import anyio
import httpx

from larder_api import planning
from larder_api.chat.scope import Models
from larder_api.chat.tasks import ChatTurns
from larder_api.settings import Settings
from larder_llm.client import CallSink, ResetSink, TextSink, Turn
from larder_llm.fake import Script, ScriptedChatModel
from larder_llm.reply import OfflineReason

CHAT_NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
MON = date(2026, 10, 12)
TUE, WED, THU, FRI, SAT, SUN = (MON + timedelta(days=d) for d in range(1, 7))
CHAT_PLANNER: planning.Planner = partial(
    planning.run_planner, mode="greedy", time_limit_ms=2000, workers=1
)


def chat_settings(**overrides: Any) -> Settings:
    """Defaults from the code, never from the environment (no key, no .env): validating
    skips the settings sources."""
    return Settings.model_validate({"planner": "greedy"} | overrides)


def sse_events(body: str) -> list[dict[str, Any]]:
    """The `data:` payloads of a text/event-stream body (pings and blank lines skipped)."""
    return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]


@dataclass
class ChatEnv:
    turns: ChatTurns
    auth: Callable[[str], dict[str, str]]  # Authorization header for a user
    now: datetime = CHAT_NOW
    models: Models = field(default_factory=lambda: Models(offline_reason="no_key"))
    settings: Settings = field(default_factory=chat_settings)
    cache: planning.CatalogCache = field(default_factory=planning.CatalogCache)

    def clock(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)

    def online(self, *script: Script, model: str = "fake-chat") -> ScriptedChatModel:
        """Replies come from this strict scripted model from now on (reuse it across turns:
        it checks that each request extends the previous one)."""
        chat = ScriptedChatModel(list(script), model=model)
        self.models = Models(chat=chat)
        return chat

    def offline(self, reason: OfflineReason = "no_key") -> None:
        self.models = Models(offline_reason=reason)

    async def idle(self) -> None:
        """Wait for every running turn to finish (detached turns outlive their response)."""
        await self.turns.close()
        await self.turns.open()

    def body(
        self,
        text: str,
        *,
        client_id: uuid.UUID | None = None,
        today: date | None = None,
        local_time: str | None = "12:00",
        thread_id: int | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "text": text,
            "client_id": str(client_id or uuid.uuid4()),
            "today": (today or self.now.date()).isoformat(),
        }
        if local_time is not None:
            body["local_time"] = local_time
        if thread_id is not None:
            body["thread_id"] = thread_id
        return body

    async def send(
        self, api: httpx.AsyncClient, text: str, *, user: str = "user_a", **body: Any
    ) -> tuple[httpx.Response, list[dict[str, Any]]]:
        """POST /chat/messages -> (the response, its events in order)."""
        response = await api.post(
            "/chat/messages", json=self.body(text, **body), headers=self.auth(user)
        )
        return response, sse_events(response.text)


@dataclass
class Gated:
    """A chat model that holds each response until `gate` is set (`entered`: a request is
    waiting), to act while a turn is in flight."""

    model: ScriptedChatModel
    gate: anyio.Event = field(default_factory=anyio.Event)
    entered: anyio.Event = field(default_factory=anyio.Event)

    async def respond(
        self,
        *,
        system: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        on_text: TextSink,
        on_reset: ResetSink,
        on_call: CallSink,
    ) -> Turn:
        self.entered.set()
        await self.gate.wait()
        return await self.model.respond(
            system=system,
            tools=tools,
            messages=messages,
            on_text=on_text,
            on_reset=on_reset,
            on_call=on_call,
        )

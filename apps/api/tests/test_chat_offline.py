"""The chat without a model (no API key): the rule parser, the executor and templated replies,
end to end through POST /chat/messages, for each intent."""

from collections.abc import Awaitable, Callable, Coroutine
from datetime import date
from typing import Any

import httpx
import pytest
from chat_support import ChatEnv
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_db import models as db
from larder_db.engine import make_sessionmaker
from larder_llm.prompts import escape

NewUser = Callable[..., Awaitable[int]]
MakePlan = Callable[[int, date], Coroutine[Any, Any, int]]
MON = date(2026, 10, 12)
WED, THU = date(2026, 10, 14), date(2026, 10, 15)


@pytest.fixture
async def user(menu: dict[str, int], new_user: NewUser, make_plan: MakePlan) -> int:
    user_id = await new_user("user_a", allergens=["peanuts"])
    await make_plan(user_id, MON)
    return user_id


async def rows(engine: AsyncEngine, model: Any) -> list[Any]:
    async with make_sessionmaker(engine)() as session:
        return list(await session.scalars(select(model).order_by(model.id)))


async def versions(engine: AsyncEngine) -> int:
    async with make_sessionmaker(engine)() as session:
        return await session.scalar(select(func.count(db.MealPlan.id))) or 0


@pytest.mark.parametrize(
    ("text", "intent", "logged"),
    [
        ("skip dinner tonight", "skip", ("skipped", WED, "dinner")),
        ("had 2 slices of pizza for lunch", "ate_off_plan", ("off_plan", WED, "lunch")),
        ("craving something spicy tonight", "craving", None),
        ("swap Thursday's dinner", "swap", None),
    ],
)
async def test_each_intent_offline(
    api: httpx.AsyncClient,
    chat: ChatEnv,
    user: int,
    db_engine: AsyncEngine,
    text: str,
    intent: str,
    logged: tuple[str, date, str] | None,
) -> None:
    response, events = await chat.send(api, text)

    assert response.status_code == 200, response.text
    assert [e["type"] for e in events] == ["thread", "status", "outcome", "text", "done"]
    thread, _, outcome, reply, done = events
    assert (thread["mode"], thread["offline_reason"]) == ("offline", "no_key")
    assert [r["intent"] for r in outcome["results"]] == [intent]
    assert outcome["results"][0]["status"] == "applied", outcome["results"]
    assert outcome["plan_id"] is not None
    message = done["message"]
    assert message["text"] == reply["delta"]
    assert (message["mode"], message["offline_reason"]) == ("offline", "no_key")
    assert message["plan_id"] == outcome["plan_id"]
    assert message["attachments"] == [outcome]

    stored = await rows(db_engine, db.ChatMessage)
    assert [m.role for m in stored] == ["user", "assistant"]
    user_row, assistant_row = stored
    words = f"<user_message>{escape(text)}</user_message>"
    assert user_row.api_messages == [{"role": "user", "content": [{"type": "text", "text": words}]}]
    assert assistant_row.api_messages == [
        {"role": "assistant", "content": [{"type": "text", "text": message["text"]}]}
    ]
    assert assistant_row.attachments == [outcome]
    cravings = await rows(db_engine, db.Craving)
    assert [(c.intent, c.message_id, c.status) for c in cravings] == [
        (intent, user_row.id, "applied")
    ]
    logs = await rows(db_engine, db.MealLog)
    if logged is None:
        assert logs == []
    else:
        assert [(log.kind, log.eaten_on, log.slot) for log in logs] == [logged]
        assert logs[0].source == "offline"
    assert await versions(db_engine) == 2
    assert await rows(db_engine, db.LlmCall) == []


async def test_not_understood_offline_gets_help_and_changes_nothing(
    api: httpx.AsyncClient, chat: ChatEnv, user: int, db_engine: AsyncEngine
) -> None:
    response, events = await chat.send(api, "what's the weather like?")

    assert response.status_code == 200
    assert [e["type"] for e in events] == ["thread", "text", "done"]
    assert "skip dinner tonight" in events[-1]["message"]["text"]  # the help text
    assert await versions(db_engine) == 1
    assert await rows(db_engine, db.Craving) == []


async def test_the_simple_mode_note_comes_once(
    api: httpx.AsyncClient, chat: ChatEnv, user: int
) -> None:
    _, first = await chat.send(api, "skip dinner tonight")
    _, second = await chat.send(api, "skip lunch tomorrow")

    assert "Simple mode" in first[-1]["message"]["text"]
    assert "Simple mode" not in second[-1]["message"]["text"]

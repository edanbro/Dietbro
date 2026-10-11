"""What the model is given: the per-turn context block (the plan from today only, logged meals,
targets, allergies, expiring food), the read-only tools (the signed-in user's data only), and
the model clients chosen from settings."""

import json
from collections.abc import Awaitable, Callable, Coroutine
from datetime import date, timedelta
from typing import Any

import httpx
import pytest
from chat_support import MON, WED, ChatEnv
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_api.chat.models import get_models
from larder_api.settings import Settings
from larder_db import models as db
from larder_db.engine import make_sessionmaker
from larder_llm.client import AnthropicChatModel, AnthropicStructuredModel
from larder_llm.fake import Step, say, tool

NewUser = Callable[..., Awaitable[int]]
MakePlan = Callable[[int, date], Coroutine[Any, Any, int]]
Block = dict[str, Any]
BROCCOLI, CHICKEN, APPLE = 321900, 171447, 171688


@pytest.fixture
async def user(menu: dict[str, int], new_user: NewUser, make_plan: MakePlan) -> int:
    user_id = await new_user("user_a", allergens=["peanuts"])
    await make_plan(user_id, MON)
    return user_id


async def stock(engine: AsyncEngine, user_id: int, food_id: int, expires: date) -> None:
    async with make_sessionmaker(engine)() as session:
        session.add(
            db.PantryItem(
                user_id=user_id,
                food_id=food_id,
                grams=300,
                quantity=300,
                unit="g",
                expires_on=expires,
            )
        )
        await session.commit()


async def test_the_context_block_covers_today_onwards(
    api: httpx.AsyncClient, chat: ChatEnv, user: int, db_engine: AsyncEngine
) -> None:
    await stock(db_engine, user, BROCCOLI, WED + timedelta(days=2))
    await stock(db_engine, user, CHICKEN, WED + timedelta(days=12))  # not expiring soon
    _, offline = await chat.send(api, "skip dinner tonight")  # logged, offline
    assert offline[-1]["type"] == "done"
    model = chat.online(say("Noted."))

    await chat.send(api, "what's left this week?")

    context = model.requests[0]["messages"][-1]["content"][0]["text"]
    lines = context.splitlines()
    assert lines[0] == "<context>"
    assert lines[1] == "today: Wed 2026-10-14"
    days = [
        line[:9] for line in lines if line[:3] in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    ]
    assert days == ["Wed 10-14", "Thu 10-15", "Fri 10-16", "Sat 10-17", "Sun 10-18"]
    wednesday = next(line for line in lines if line.startswith("Wed 10-14"))
    assert "logged: dinner: skipped" in wednesday
    assert " D " not in wednesday  # the skipped dinner is no longer planned
    assert "targets: 1700-2300 kcal/day, floor 1200, protein >= 90 g/day" in lines
    assert "allergies (strict): Peanuts" in lines
    expiring = next(line for line in lines if line.startswith("expiring:"))
    assert "broccoli" in expiring
    assert "chicken" not in expiring
    assert lines[-1] == "</context>"
    # The offline turn before it is replayed too: the transcript starts with plain messages.
    replayed = model.requests[0]["messages"]
    assert [m["role"] for m in replayed] == ["user", "assistant", "user"]


def results(requests: list[dict[str, Any]]) -> list[Block]:
    return [
        block
        for message in requests[-1]["messages"]
        if message["role"] == "user" and isinstance(message["content"], list)
        for block in message["content"]
        if block["type"] == "tool_result"
    ]


async def test_read_only_tools_see_only_the_users_own_data(
    api: httpx.AsyncClient,
    chat: ChatEnv,
    user: int,
    new_user: NewUser,
    make_plan: MakePlan,
    db_engine: AsyncEngine,
) -> None:
    other = await new_user("user_b")
    their_plan = await make_plan(other, MON)
    await stock(db_engine, user, BROCCOLI, WED + timedelta(days=2))
    await stock(db_engine, other, APPLE, WED + timedelta(days=1))
    script: list[Step] = [
        tool("get_pantry", {}),
        tool("get_plan", {}),
        tool("explain_meal", {"when": {"date": WED.isoformat(), "slot": "dinner"}}),
        tool("explain_plan_diff", {}),
        tool("explain_plan_diff", {"plan_id": their_plan}),
        say("Here you go."),
    ]
    model = chat.online(*script)

    await chat.send(api, "tell me about my week")

    pantry, plan, meal, diff, theirs = results(model.requests)
    assert [i["food"] for i in json.loads(pantry["content"])["items"]] == ["broccoli"]
    assert json.loads(plan["content"])["plan_id"] != their_plan
    assert json.loads(meal["content"])["meals"][0]["slot"] == "dinner"
    assert "first version" in json.loads(diff["content"])["note"]
    assert theirs.get("is_error") is True
    assert all(not r.get("is_error") for r in (pantry, plan, meal, diff))


def test_without_a_key_the_chat_is_offline() -> None:
    models = get_models(Settings.model_validate({}))

    assert (models.chat, models.fast, models.offline_reason) == (None, None, "no_key")
    forced = Settings.model_validate({"anthropic_api_key": "k", "llm_mode": "offline"})
    assert get_models(forced).offline_reason == "no_key"


def test_with_a_key_both_models_share_one_client() -> None:
    settings = Settings.model_validate(
        {"anthropic_api_key": SecretStr("k"), "llm_chat_model": "claude-sonnet-5-5"}
    )

    first, second = get_models(settings), get_models(settings)

    assert isinstance(first.chat, AnthropicChatModel)
    assert isinstance(first.fast, AnthropicStructuredModel)
    assert isinstance(second.chat, AnthropicChatModel)
    assert (first.chat.model, first.chat.effort) == ("claude-sonnet-5-5", "low")
    assert first.chat.client is first.fast.client is second.chat.client
    assert first.offline_reason is None

"""Chat turns run detached (larder_api.chat.tasks.ChatTurns): a turn past its deadline is cut
off but still leaves a reply and frees the lock, and shutting down waits for running turns."""

from collections.abc import Awaitable, Callable, Coroutine
from datetime import date
from typing import Any

import anyio
import httpx
import pytest
from chat_support import MON, ChatEnv, Gated
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_api.chat import context, limits
from larder_api.chat.scope import Models
from larder_api.chat.service import FAILED
from larder_api.chat.tasks import TIMED_OUT, ChatTurns
from larder_db import models as db
from larder_db.engine import make_sessionmaker
from larder_llm.fake import ScriptedChatModel, say

NewUser = Callable[..., Awaitable[int]]
MakePlan = Callable[[int, date], Coroutine[Any, Any, int]]


@pytest.fixture
async def user(menu: dict[str, int], new_user: NewUser, make_plan: MakePlan) -> int:
    user_id = await new_user("user_a", allergens=["peanuts"])
    await make_plan(user_id, MON)
    return user_id


async def replace_turns(chat: ChatEnv, deadline_s: float) -> None:
    await chat.turns.close()
    chat.turns = ChatTurns(deadline_s=deadline_s)
    await chat.turns.open()


async def messages(engine: AsyncEngine) -> list[db.ChatMessage]:
    async with make_sessionmaker(engine)() as session:
        return list(await session.scalars(select(db.ChatMessage).order_by(db.ChatMessage.id)))


async def lock_of(engine: AsyncEngine, user_id: int) -> object:
    async with make_sessionmaker(engine)() as session:
        return await session.scalar(select(db.User.chat_turn_token).where(db.User.id == user_id))


async def test_a_turn_past_its_deadline_still_leaves_a_reply_and_frees_the_lock(
    api: httpx.AsyncClient,
    chat: ChatEnv,
    user: int,
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await replace_turns(chat, deadline_s=0.5)
    chat.models = Models(chat=ScriptedChatModel([say("too late")]))

    async def stuck(*_: object) -> None:  # outside the model, which has a deadline of its own
        await anyio.sleep_forever()

    monkeypatch.setattr(context, "turn_context", stuck)

    response, events = await chat.send(api, "skip dinner tonight")

    assert response.status_code == 200
    assert [e["type"] for e in events] == ["thread", "error"]
    assert events[-1]["message"] == TIMED_OUT
    user_row, reply = await messages(db_engine)
    assert (reply.role, reply.text) == ("assistant", FAILED)
    assert (user_row.api_messages, reply.api_messages) == ([], [])  # display-only
    assert await lock_of(db_engine, user) is None
    again, _ = await chat.send(api, "hello?")
    assert again.status_code == 200  # not busy


async def test_shutdown_waits_for_running_turns(
    api: httpx.AsyncClient, chat: ChatEnv, user: int, db_engine: AsyncEngine
) -> None:
    gated = Gated(ScriptedChatModel([say("Done in time.")]))
    chat.models = Models(chat=gated)
    closed = anyio.Event()
    events: list[dict[str, Any]] = []

    async def send() -> None:
        _, got = await chat.send(api, "hello")
        events.extend(got)

    async def shut_down() -> None:
        await chat.turns.close()
        closed.set()

    with anyio.fail_after(10):
        async with anyio.create_task_group() as tg:
            tg.start_soon(send)
            await gated.entered.wait()
            tg.start_soon(shut_down)
            await anyio.sleep(0.1)
            assert not closed.is_set()  # still waiting for the turn
            assert not chat.turns.accepting  # but taking no new ones
            gated.gate.set()

    assert events[-1]["type"] == "done"
    assert events[-1]["message"]["text"] == "Done in time."
    assert [m.role for m in await messages(db_engine)] == ["user", "assistant"]
    assert await lock_of(db_engine, user) is None


async def test_no_new_turns_while_shutting_down(
    api: httpx.AsyncClient, chat: ChatEnv, user: int, db_engine: AsyncEngine
) -> None:
    await chat.turns.close()

    response, _ = await chat.send(api, "hello")

    assert response.status_code == 503
    assert await messages(db_engine) == []  # refused before the gate stored anything
    assert await lock_of(db_engine, user) is None


async def test_a_lock_release_that_fails_is_logged_and_other_turns_carry_on(
    api: httpx.AsyncClient,
    chat: ChatEnv,
    user: int,
    new_user: NewUser,
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await new_user("user_b")
    real = limits.release_turn
    broken = True

    async def release_turn(*args: Any) -> None:
        if broken:
            raise RuntimeError("database went away")
        await real(*args)

    monkeypatch.setattr(limits, "release_turn", release_turn)

    response, events = await chat.send(api, "hello")
    await chat.idle()

    assert response.status_code == 200
    assert events[-1]["type"] == "done"  # the reply was stored; a failed release isn't an error
    assert [m.role for m in await messages(db_engine)] == ["user", "assistant"]
    broken = False
    again, other = await chat.send(api, "hello", user="user_b")
    assert again.status_code == 200
    assert other[-1]["type"] == "done"


async def test_a_stalled_model_gives_up_in_time_for_the_rule_parser(
    api: httpx.AsyncClient, chat: ChatEnv, user: int, db_engine: AsyncEngine
) -> None:
    await replace_turns(chat, deadline_s=5)
    chat.settings.chat_turn_deadline_s = 2  # the model gets half of it
    chat.models = Models(chat=Gated(ScriptedChatModel([say("too late")])))  # never answers

    response, events = await chat.send(api, "skip dinner tonight")

    assert response.status_code == 200
    done = events[-1]
    assert done["type"] == "done"
    assert (done["message"]["mode"], done["message"]["offline_reason"]) == (
        "offline",
        "model_error",
    )
    assert "outcome" in [e["type"] for e in events]  # the rule parser skipped dinner
    assert await lock_of(db_engine, user) is None

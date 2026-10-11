"""POST /chat/messages' gate and the thread endpoints: every refusal is a real HTTP error with a
JSON ChatProblem body, and none of them stores a message or keeps the turn lock."""

import uuid
from collections.abc import Awaitable, Callable, Coroutine
from datetime import date, datetime, timedelta
from typing import Any

import httpx
import pytest
from chat_support import ChatEnv
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_db import models as db
from larder_db.engine import make_sessionmaker
from larder_llm.fake import say

NewUser = Callable[..., Awaitable[int]]
Auth = Callable[..., dict[str, str]]
MakePlan = Callable[[int, date], Coroutine[Any, Any, int]]
MON = date(2026, 10, 12)


@pytest.fixture
async def user(menu: dict[str, int], new_user: NewUser, make_plan: MakePlan) -> int:
    user_id = await new_user("user_a", allergens=["peanuts"])
    await make_plan(user_id, MON)
    return user_id


async def count(engine: AsyncEngine, model: Any) -> int:
    async with make_sessionmaker(engine)() as session:
        return await session.scalar(select(func.count()).select_from(model)) or 0


async def lock_of(engine: AsyncEngine, user_id: int) -> uuid.UUID | None:
    async with make_sessionmaker(engine)() as session:
        return await session.scalar(select(db.User.chat_turn_token).where(db.User.id == user_id))


async def hold_lock(
    engine: AsyncEngine, user_id: int, started: datetime, message_id: int | None
) -> None:
    async with make_sessionmaker(engine)() as session, session.begin():
        await session.execute(
            update(db.User)
            .where(db.User.id == user_id)
            .values(
                chat_turn_token=uuid.uuid4(),
                chat_turn_started_at=started,
                chat_turn_message_id=message_id,
            )
        )


async def user_message(
    engine: AsyncEngine, user_id: int, thread_id: int, *, at: datetime, client_id: uuid.UUID
) -> int:
    async with make_sessionmaker(engine)() as session:
        row = db.ChatMessage(
            thread_id=thread_id,
            user_id=user_id,
            role="user",
            text="hello",
            client_id=client_id,
            today=at.date(),
            created_at=at,
        )
        session.add(row)
        await session.commit()
        return row.id


async def new_thread(engine: AsyncEngine, user_id: int, at: datetime) -> int:
    async with make_sessionmaker(engine)() as session:
        thread = db.ChatThread(user_id=user_id, updated_at=at)
        session.add(thread)
        await session.commit()
        return thread.id


def problem(response: httpx.Response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/json")
    body: dict[str, Any] = response.json()
    assert body["code"] == code
    assert isinstance(body["detail"], list)
    return body


async def test_an_offline_message_streams_thread_then_done(
    api: httpx.AsyncClient, chat: ChatEnv, user: int, db_engine: AsyncEngine
) -> None:
    response, events = await chat.send(api, "hello there")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert [e["type"] for e in events] == ["thread", "text", "done"]
    assert events[0]["mode"] == "offline"
    assert events[0]["offline_reason"] == "no_key"
    done = events[-1]
    assert done["messages_today"] == 1
    assert done["message"]["role"] == "assistant"
    assert done["message"]["text"] == events[1]["delta"]
    assert "Simple mode" in done["message"]["text"]  # the first reply says why
    assert await count(db_engine, db.ChatMessage) == 2
    assert await lock_of(db_engine, user) is None


@pytest.mark.parametrize("days", [-2, 2])
async def test_an_implausible_today_is_400_and_stores_nothing(
    api: httpx.AsyncClient, chat: ChatEnv, user: int, db_engine: AsyncEngine, days: int
) -> None:
    response, _ = await chat.send(api, "skip dinner", today=chat.now.date() + timedelta(days))

    problem(response, 400, "bad_today")
    assert await count(db_engine, db.ChatMessage) == 0
    assert await count(db_engine, db.ChatThread) == 0
    assert await lock_of(db_engine, user) is None


async def test_today_may_not_go_back_from_the_previous_message(
    api: httpx.AsyncClient, chat: ChatEnv, user: int, db_engine: AsyncEngine
) -> None:
    first, _ = await chat.send(api, "hello", today=chat.now.date() + timedelta(days=1))
    assert first.status_code == 200

    response, _ = await chat.send(api, "hello again")

    problem(response, 400, "bad_today")
    assert await count(db_engine, db.ChatMessage) == 2


async def test_another_users_thread_is_404(
    api: httpx.AsyncClient, chat: ChatEnv, user: int, new_user: NewUser, db_engine: AsyncEngine
) -> None:
    other = await new_user("user_b")
    theirs = await new_thread(db_engine, other, chat.now)

    response, _ = await chat.send(api, "hello", thread_id=theirs)

    problem(response, 404, "thread_not_found")
    assert await count(db_engine, db.ChatMessage) == 0
    assert await lock_of(db_engine, user) is None


async def test_a_resent_message_is_answered_once(
    api: httpx.AsyncClient, chat: ChatEnv, user: int, db_engine: AsyncEngine
) -> None:
    client_id = uuid.uuid4()
    first, events = await chat.send(api, "skip dinner tonight", client_id=client_id)
    assert first.status_code == 200
    message_id = events[0]["message_id"]

    again, _ = await chat.send(api, "skip dinner tonight", client_id=client_id)

    body = problem(again, 409, "duplicate")
    assert body["message_id"] == message_id
    assert await count(db_engine, db.ChatMessage) == 2
    assert await count(db_engine, db.MealLog) == 1
    assert await count(db_engine, db.Craving) == 1


async def test_while_a_turn_runs_new_messages_and_resends_are_busy(
    api: httpx.AsyncClient, chat: ChatEnv, auth: Auth, user: int, db_engine: AsyncEngine
) -> None:
    thread = await new_thread(db_engine, user, chat.now)
    client_id = uuid.uuid4()
    running = await user_message(db_engine, user, thread, at=chat.now, client_id=client_id)
    await hold_lock(db_engine, user, chat.now, running)

    resent, _ = await chat.send(api, "hello", client_id=client_id)
    other, _ = await chat.send(api, "something else")

    assert problem(resent, 409, "busy")["message_id"] == running
    assert problem(other, 409, "busy")["message_id"] == running
    assert await count(db_engine, db.ChatMessage) == 1
    got = await api.get("/chat/thread", headers=auth())
    assert got.status_code == 200, got.text
    assert got.json()["pending"]["message_id"] == running


async def test_a_stale_lock_is_taken_over(
    api: httpx.AsyncClient, chat: ChatEnv, user: int, db_engine: AsyncEngine
) -> None:
    stale = chat.now - timedelta(seconds=chat.settings.chat_turn_deadline_s + 31)
    await hold_lock(db_engine, user, stale, None)

    response, events = await chat.send(api, "hello")

    assert response.status_code == 200
    assert events[-1]["type"] == "done"
    assert await lock_of(db_engine, user) is None


async def test_sixty_messages_a_rolling_day_then_429_until_the_oldest_ages_out(
    api: httpx.AsyncClient, chat: ChatEnv, user: int, db_engine: AsyncEngine
) -> None:
    chat.settings.llm_daily_messages = 3
    thread = await new_thread(db_engine, user, chat.now)
    oldest = chat.now - timedelta(hours=23)
    for at in (chat.now - timedelta(hours=25), oldest, chat.now - timedelta(hours=2)):
        await user_message(db_engine, user, thread, at=at, client_id=uuid.uuid4())
    ok, events = await chat.send(api, "hello")
    assert ok.status_code == 200
    assert events[-1]["messages_today"] == 3

    response, _ = await chat.send(api, "hello again")

    body = problem(response, 429, "daily_limit")
    assert datetime.fromisoformat(body["retry_at"]) == oldest + timedelta(hours=24)
    assert await count(db_engine, db.ChatMessage) == 5
    assert await lock_of(db_engine, user) is None
    chat.advance(hours=1, minutes=1)  # the oldest of the day's messages ages out
    later, _ = await chat.send(api, "hello again")
    assert later.status_code == 200


async def test_thread_pages_back_with_before_id(
    api: httpx.AsyncClient, chat: ChatEnv, auth: Auth, user: int
) -> None:
    for text in ("one", "two", "three"):
        response, _ = await chat.send(api, text)
        assert response.status_code == 200

    latest = (await api.get("/chat/thread", params={"limit": 4}, headers=auth())).json()
    older = (
        await api.get(
            "/chat/thread",
            params={"limit": 4, "before_id": latest["messages"][0]["id"]},
            headers=auth(),
        )
    ).json()

    assert [m["role"] for m in latest["messages"]] == ["user", "assistant"] * 2
    assert latest["has_more"] is True
    assert [m["text"] for m in older["messages"]] == ["one", older["messages"][1]["text"]]
    assert older["has_more"] is False
    assert latest["messages_today"] == 3
    assert latest["daily_limit"] == chat.settings.llm_daily_messages
    assert (latest["llm_available"], latest["offline_reason"]) == (False, "no_key")
    assert latest["pending"] is None


async def test_a_new_thread_becomes_the_current_one(
    api: httpx.AsyncClient, chat: ChatEnv, auth: Auth, user: int
) -> None:
    first, events = await chat.send(api, "hello")
    assert first.status_code == 200

    created = await api.post("/chat/threads", headers=auth())
    current = (await api.get("/chat/thread", headers=auth())).json()

    assert created.status_code == 201
    assert created.json()["thread_id"] != events[0]["thread_id"]
    assert current["thread_id"] == created.json()["thread_id"]
    assert current["messages"] == []
    _, events = await chat.send(api, "hello again")
    assert events[0]["thread_id"] == created.json()["thread_id"]


async def test_no_thread_yet(api: httpx.AsyncClient, chat: ChatEnv, auth: Auth, user: int) -> None:
    thread = (await api.get("/chat/thread", headers=auth())).json()

    assert thread["thread_id"] is None
    assert thread["messages"] == []
    assert thread["messages_today"] == 0


async def test_online_availability_is_reported(
    api: httpx.AsyncClient, chat: ChatEnv, auth: Auth, user: int
) -> None:
    chat.online(say("hi"))

    thread = (await api.get("/chat/thread", headers=auth())).json()

    assert (thread["llm_available"], thread["offline_reason"], thread["llm_resets_at"]) == (
        True,
        None,
        None,
    )

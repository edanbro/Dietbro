"""The chat with a (scripted) model, end to end through POST /chat/messages: each intent, the
transcript stored and replayed append-only, epochs, failures before and after a write, refusals,
rejected replays, the budget and the per-turn cap, and a client that leaves mid-turn.

The scripted models are strict: every request must be a valid, append-only transcript (see
larder_llm.fake), so a turn that stores a broken or reordered transcript fails here."""

import json
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import anyio
import httpx
import pytest
from chat_support import FRI, MON, THU, WED, ChatEnv, Gated
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.types import Message, Scope

from larder_api.chat.scope import Models
from larder_api.chat.service import REFUSED
from larder_api.main import app
from larder_db import models as db
from larder_db.engine import make_sessionmaker
from larder_llm.agent import check_transcript
from larder_llm.fake import (
    ScriptedChatModel,
    Step,
    fail,
    fallback,
    refuse,
    reject,
    say,
    tool,
)

NewUser = Callable[..., Awaitable[int]]
MakePlan = Callable[[int, date], Coroutine[Any, Any, int]]
Block = dict[str, Any]
SONNET = "claude-sonnet-5-5"  # priced like the real chat model: 400 micro-dollars a request


@pytest.fixture
async def user(menu: dict[str, int], new_user: NewUser, make_plan: MakePlan) -> int:
    user_id = await new_user("user_a", allergens=["peanuts"])
    await make_plan(user_id, MON)
    return user_id


def when(on: date, slot: str) -> dict[str, str]:
    return {"date": on.isoformat(), "slot": slot}


def replan(*changes: dict[str, Any]) -> Step:
    return tool("request_replan", {"changes": list(changes)})


PIZZA_LUNCH = {
    "intent": "ate_off_plan",
    "when": when(WED, "lunch"),
    "description": "2 slices of pizza",
    "items": [{"name": "pizza", "quantity": "2 slices"}],
}
SKIP_DINNER = {"intent": "skip", "when": when(WED, "dinner"), "eating_elsewhere": False}


def last_result(messages: list[Block]) -> dict[str, Any]:
    """The JSON of the newest tool result the model was sent."""
    block = messages[-1]["content"][-1]
    assert block["type"] == "tool_result", block
    return json.loads(block["content"])


def craving_for_first_hit(on: date, slot: str) -> Callable[[list[Block]], Step]:
    def step(messages: list[Block]) -> Step:
        hits = last_result(messages)["recipes"]
        assert hits, "search_recipes found nothing"
        change = {"intent": "craving", "when": when(on, slot), "strength": "hard"}
        return replan(change | {"recipe_id": hits[0]["id"]})

    return step


def kinds(events: list[dict[str, Any]]) -> list[str]:
    """Event types in order, with runs of text deltas as one."""
    out: list[str] = []
    for event in events:
        if not (event["type"] == "text" and out and out[-1] == "text"):
            out.append(event["type"])
    return out


def text_of(events: list[dict[str, Any]]) -> str:
    """What the client shows: text deltas, cleared by each text_reset."""
    shown = ""
    for event in events:
        if event["type"] == "text":
            shown += event["delta"]
        elif event["type"] == "text_reset":
            shown = ""
    return shown


@dataclass
class Stored:
    messages: list[db.ChatMessage]
    cravings: list[db.Craving]
    logs: list[db.MealLog]
    calls: list[db.LlmCall]
    versions: int
    lock: uuid.UUID | None


async def stored(engine: AsyncEngine, user_id: int) -> Stored:
    async with make_sessionmaker(engine)() as session:

        async def all_of(model: Any) -> list[Any]:
            return list(await session.scalars(select(model).order_by(model.id)))

        versions = await session.scalar(select(func.count(db.MealPlan.id)))
        lock = await session.scalar(select(db.User.chat_turn_token).where(db.User.id == user_id))
        return Stored(
            messages=await all_of(db.ChatMessage),
            cravings=await all_of(db.Craving),
            logs=await all_of(db.MealLog),
            calls=await all_of(db.LlmCall),
            versions=versions or 0,
            lock=lock,
        )


def assert_replayable(rows: list[db.ChatMessage]) -> None:
    transcript = [m for row in rows for m in row.api_messages]
    assert check_transcript(transcript) == []


# --- each intent ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "script", "intent", "statuses", "logged"),
    [
        (
            "craving something spicy tonight",
            [
                tool("search_recipes", {"query": "spicy", "slot": "dinner"}),
                craving_for_first_hit(WED, "dinner"),
                say("Tonight's dinner is now something spicy."),
            ],
            "craving",
            ["Looking for recipes…", "Updating your plan…"],
            None,
        ),
        (
            "had 2 slices of pizza for lunch",
            [replan(PIZZA_LUNCH), say("Logged the pizza and rebalanced today.")],
            "ate_off_plan",
            ["Updating your plan…"],
            ("off_plan", WED, "lunch"),
        ),
        (
            "skip dinner tonight, not hungry",
            [replan(SKIP_DINNER), say("Skipped tonight's dinner.")],
            "skip",
            ["Updating your plan…"],
            ("skipped", WED, "dinner"),
        ),
        (
            "swap Thursday's dinner",
            [
                replan({"intent": "swap", "when": when(THU, "dinner")}),
                say("Thursday's dinner is swapped."),
            ],
            "swap",
            ["Updating your plan…"],
            None,
        ),
    ],
    ids=["craving", "ate_off_plan", "skip", "swap"],
)
async def test_each_intent_with_the_model(
    api: httpx.AsyncClient,
    chat: ChatEnv,
    user: int,
    db_engine: AsyncEngine,
    text: str,
    script: list[Step | Callable[[list[Block]], Step]],
    intent: str,
    statuses: list[str],
    logged: tuple[str, date, str] | None,
) -> None:
    model = chat.online(*script)

    response, events = await chat.send(api, text)

    assert response.status_code == 200, response.text
    assert kinds(events) == ["thread", *["status"] * len(statuses), "outcome", "text", "done"]
    assert [e["text"] for e in events if e["type"] == "status"] == statuses
    assert (events[0]["mode"], events[0]["offline_reason"]) == ("llm", None)
    outcome = next(e for e in events if e["type"] == "outcome")
    assert [(r["intent"], r["status"]) for r in outcome["results"]] == [(intent, "applied")]
    done = events[-1]["message"]
    assert done["text"] == text_of(events) == script_reply(script)
    assert (done["mode"], done["offline_reason"], done["plan_id"]) == (
        "llm",
        None,
        outcome["plan_id"],
    )
    assert done["attachments"] == [outcome]

    db_rows = await stored(db_engine, user)
    user_row, reply_row = db_rows.messages
    # The user row holds the request's user turn; the reply row everything the turn appended.
    assert user_row.api_messages == [model.requests[0]["messages"][-1]]
    assert reply_row.api_messages[:-1] == model.requests[-1]["messages"][1:]
    assert reply_row.api_messages[-1]["role"] == "assistant"
    assert_replayable(db_rows.messages)
    assert reply_row.attachments == [outcome]
    assert [(c.intent, c.status, c.message_id) for c in db_rows.cravings] == [
        (intent, "applied", user_row.id)
    ]
    assert [(log.kind, log.eaten_on, log.slot, log.source) for log in db_rows.logs] == (
        [(*logged, "chat")] if logged else []
    )
    assert len(db_rows.calls) == len(model.requests)
    assert db_rows.versions == 2
    assert db_rows.lock is None


def script_reply(script: list[Step | Callable[[list[Block]], Step]]) -> str:
    final = script[-1]
    assert isinstance(final, Step)
    return str(final.content[0]["text"])


async def test_a_created_recipe_can_go_straight_into_the_plan(
    api: httpx.AsyncClient, chat: ChatEnv, user: int, db_engine: AsyncEngine
) -> None:
    draft = {
        "name": "Chicken and broccoli bake",
        "slot": "dinner",
        "servings": 2,
        "ingredients": [
            {"name": "chicken", "quantity": "300 g"},
            {"name": "broccoli", "quantity": "300 g"},
            {"name": "rice", "quantity": "150 g"},
        ],
        "instructions": "Bake everything together for 30 minutes.",
    }

    def use_it(messages: list[Block]) -> Step:
        recipe_id = last_result(messages)["recipe_id"]
        change = {"intent": "craving", "when": when(FRI, "dinner"), "strength": "hard"}
        return replan(change | {"recipe_id": recipe_id})

    chat.online(tool("create_recipe", draft), use_it, say("Friday is your new bake."))

    _, events = await chat.send(api, "make me a chicken and broccoli bake for Friday")

    assert kinds(events) == ["thread", "status", "recipe", "status", "outcome", "text", "done"]
    recipe = next(e for e in events if e["type"] == "recipe")
    outcome = next(e for e in events if e["type"] == "outcome")
    assert outcome["results"][0]["status"] == "applied"
    assert outcome["results"][0]["recipe_id"] == recipe["recipe_id"]
    assert events[-1]["message"]["attachments"] == [recipe, outcome]
    async with make_sessionmaker(db_engine)() as session:
        row = await session.get(db.Recipe, recipe["recipe_id"])
        assert row is not None
        assert (row.owner_user_id, row.source) == (user, "generated")


async def test_questions_need_no_write(
    api: httpx.AsyncClient, chat: ChatEnv, user: int, db_engine: AsyncEngine
) -> None:
    def answer(messages: list[Block]) -> Step:
        plan = last_result(messages)
        assert plan["plan_id"]
        assert plan["days"][0]["date"].endswith(WED.isoformat())
        return say("Your plan runs to Sunday.")

    model = chat.online(tool("get_plan", {}), answer)

    _, events = await chat.send(api, "how long does my plan run?")

    assert kinds(events) == ["thread", "status", "text", "done"]
    assert events[-1]["message"]["attachments"] == []
    assert events[-1]["message"]["plan_id"] is None
    db_rows = await stored(db_engine, user)
    assert db_rows.versions == 1
    assert len(db_rows.calls) == len(model.requests) == 2


# --- the transcript ---------------------------------------------------------------------------


async def test_the_next_turn_replays_the_stored_transcript_exactly(
    api: httpx.AsyncClient, chat: ChatEnv, user: int, db_engine: AsyncEngine
) -> None:
    model = chat.online(replan(SKIP_DINNER), say("Skipped."), say("You're welcome!"))
    await chat.send(api, "skip dinner tonight")
    first_turn = [m for row in (await stored(db_engine, user)).messages for m in row.api_messages]

    chat.advance(minutes=5)
    _, events = await chat.send(api, "thanks")

    assert events[-1]["message"]["text"] == "You're welcome!"
    sent = model.requests[-1]["messages"]
    assert sent[: len(first_turn)] == first_turn  # the strict fake also checked it byte for byte
    assert len(sent) == len(first_turn) + 1
    assert "<user_message>thanks</user_message>" in json.dumps(sent[-1])
    db_rows = await stored(db_engine, user)
    assert {row.api_epoch for row in db_rows.messages} == {0}
    assert_replayable(db_rows.messages)


async def test_a_new_epoch_after_an_idle_gap(
    api: httpx.AsyncClient, chat: ChatEnv, user: int, db_engine: AsyncEngine
) -> None:
    model = chat.online(say("Hello!"), say("Hello again!"))
    await chat.send(api, "hi")

    chat.advance(minutes=chat.settings.chat_epoch_idle_min + 1)
    await chat.send(api, "hi again")

    assert len(model.requests[-1]["messages"]) == 1  # nothing replayed
    assert [row.api_epoch for row in (await stored(db_engine, user)).messages] == [0, 0, 1, 1]


async def test_a_new_epoch_when_the_transcript_gets_long(
    api: httpx.AsyncClient, chat: ChatEnv, user: int, db_engine: AsyncEngine
) -> None:
    chat.settings.chat_epoch_max_tokens = 100  # the first turn's context block alone is more
    model = chat.online(say("Hello!"), say("Hello again!"))
    await chat.send(api, "hi")

    await chat.send(api, "hi again")

    assert len(model.requests[-1]["messages"]) == 1
    assert [row.api_epoch for row in (await stored(db_engine, user)).messages] == [0, 0, 1, 1]


async def test_a_rejected_replay_retries_in_a_new_epoch(
    api: httpx.AsyncClient, chat: ChatEnv, user: int, db_engine: AsyncEngine
) -> None:
    model = chat.online(say("Hello!"), reject(), say("Hi again!"), say("Still here."))
    await chat.send(api, "hi")

    _, events = await chat.send(api, "hi again")
    _, later = await chat.send(api, "still there?")

    assert events[-1]["type"] == "done"
    assert events[-1]["message"]["text"] == "Hi again!"
    assert [len(r["messages"]) for r in model.requests] == [1, 3, 1, 3]
    db_rows = await stored(db_engine, user)
    assert [row.api_epoch for row in db_rows.messages] == [0, 0, 1, 1, 1, 1]
    assert len(db_rows.calls) == 4
    assert later[-1]["message"]["text"] == "Still here."


async def test_a_refused_turn_is_never_replayed(
    api: httpx.AsyncClient, chat: ChatEnv, user: int, db_engine: AsyncEngine
) -> None:
    model = chat.online(refuse(after_text="Sure, here is"), say("Hello!"))

    _, events = await chat.send(api, "something the model declines")

    assert kinds(events) == ["thread", "text", "text_reset", "text", "done"]
    assert text_of(events) == events[-1]["message"]["text"] == REFUSED
    refused_user, refused_reply = (await stored(db_engine, user)).messages
    assert (refused_user.api_messages, refused_reply.api_messages) == ([], [])

    await chat.send(api, "hi")

    assert len(model.requests[-1]["messages"]) == 1  # only the new user turn


async def test_a_refusal_before_any_text_still_resets_once(
    api: httpx.AsyncClient, chat: ChatEnv, user: int
) -> None:
    chat.online(refuse())

    _, events = await chat.send(api, "something the model declines")

    assert kinds(events) == ["thread", "text_reset", "text", "done"]
    assert events[-1]["message"]["text"] == REFUSED


async def test_a_server_side_fallback_retracts_the_declined_text(
    api: httpx.AsyncClient, chat: ChatEnv, user: int, db_engine: AsyncEngine
) -> None:
    model = chat.online(fallback("I won't", then=say("Here's your plan.")), say("Sure."))

    _, events = await chat.send(api, "tell me about my plan")
    await chat.send(api, "thanks")  # the stored response (fallback block included) replays

    assert kinds(events) == ["thread", "text", "text_reset", "text", "done"]
    assert text_of(events) == events[-1]["message"]["text"] == "Here's your plan."
    db_rows = await stored(db_engine, user)
    assert len(db_rows.calls) == len(model.requests) == 2
    assert_replayable(db_rows.messages)


# --- model failures: never repeat what was written ---------------------------------------------


async def test_a_failure_after_a_replan_summarises_instead_of_replanning(
    api: httpx.AsyncClient, chat: ChatEnv, user: int, db_engine: AsyncEngine
) -> None:
    model = chat.online(replan(PIZZA_LUNCH), fail())

    _, events = await chat.send(api, "had 2 slices of pizza for lunch")

    assert kinds(events) == ["thread", "status", "outcome", "text", "done"]
    done = events[-1]["message"]
    assert (done["mode"], done["offline_reason"]) == ("offline", "model_error")
    assert "pizza" in done["text"]
    db_rows = await stored(db_engine, user)
    assert db_rows.versions == 2
    assert len(db_rows.logs) == 1
    assert len(db_rows.cravings) == 1
    assert len(db_rows.calls) == len(model.requests) == 2
    assert [c.status for c in db_rows.calls] == ["ok", "error"]
    # The completed round (tool call + result) is kept, so the next turn knows what happened.
    assert [m["role"] for m in db_rows.messages[1].api_messages] == ["assistant", "user"]
    assert_replayable(db_rows.messages)


async def test_invalid_inputs_after_a_replan_summarise_instead_of_replanning(
    api: httpx.AsyncClient, chat: ChatEnv, user: int, db_engine: AsyncEngine
) -> None:
    model = chat.online(
        replan(PIZZA_LUNCH),
        tool("request_replan", {"changes": []}),
        tool("search_recipes", {"query": 3}),
    )

    _, events = await chat.send(api, "had 2 slices of pizza for lunch")

    assert kinds(events) == ["thread", "status", "outcome", "text", "done"]
    assert "pizza" in events[-1]["message"]["text"]
    db_rows = await stored(db_engine, user)
    assert (db_rows.versions, len(db_rows.logs)) == (2, 1)
    assert len(db_rows.calls) == len(model.requests) == 3
    assert_replayable(db_rows.messages)


async def test_a_failure_before_any_write_falls_back_to_the_rule_parser_once(
    api: httpx.AsyncClient, chat: ChatEnv, user: int, db_engine: AsyncEngine
) -> None:
    chat.online(fail(after_text="Let me"))

    _, events = await chat.send(api, "had 2 slices of pizza for lunch")

    assert kinds(events) == ["thread", "text", "text_reset", "status", "outcome", "text", "done"]
    done = events[-1]["message"]
    assert (done["mode"], done["offline_reason"]) == ("offline", "model_error")
    assert "AI assistant isn't responding" in done["text"]
    db_rows = await stored(db_engine, user)
    assert (db_rows.versions, len(db_rows.logs)) == (2, 1)
    assert db_rows.logs[0].source == "offline"
    assert [row.api_messages for row in db_rows.messages] == [[], []]  # never replayed


async def test_a_failure_with_no_text_resets_once_and_goes_offline(
    api: httpx.AsyncClient, chat: ChatEnv, user: int, db_engine: AsyncEngine
) -> None:
    chat.online(fail())

    _, events = await chat.send(api, "skip dinner tonight")

    assert kinds(events) == ["thread", "text_reset", "status", "outcome", "text", "done"]
    assert len((await stored(db_engine, user)).logs) == 1


# --- money ------------------------------------------------------------------------------------


async def spend(engine: AsyncEngine, user_id: int, micro_usd: int, at: datetime) -> None:
    async with make_sessionmaker(engine)() as session:
        session.add(
            db.LlmCall(
                user_id=user_id,
                purpose="chat",
                model=SONNET,
                input_tokens=1,
                output_tokens=1,
                cost_micro_usd=micro_usd,
                latency_ms=1,
                status="ok",
                created_at=at,
            )
        )
        await session.commit()


@pytest.mark.parametrize(
    ("spent", "resets_at"),
    [
        (1_000_000, datetime.fromisoformat("2026-11-01T00:00:00+00:00")),  # the month's cap
        (60_000, datetime.fromisoformat("2026-10-15T00:00:00+00:00")),  # today's share of it
    ],
    ids=["monthly", "paced"],
)
async def test_over_budget_the_turn_runs_offline(
    api: httpx.AsyncClient,
    chat: ChatEnv,
    auth: Callable[..., dict[str, str]],
    user: int,
    db_engine: AsyncEngine,
    spent: int,
    resets_at: datetime,
) -> None:
    await spend(db_engine, user, spent, chat.now - timedelta(hours=1))
    model = chat.online(say("never sent"))

    _, events = await chat.send(api, "skip dinner tonight")
    thread = (await api.get("/chat/thread", headers=auth())).json()

    assert (events[0]["mode"], events[0]["offline_reason"]) == ("offline", "budget")
    assert kinds(events) == ["thread", "status", "outcome", "text", "done"]
    assert "allowance" in events[-1]["message"]["text"]
    assert model.requests == []
    assert (thread["llm_available"], thread["offline_reason"]) == (False, "budget")
    assert datetime.fromisoformat(thread["llm_resets_at"]) == resets_at


async def test_the_per_turn_cap_stops_new_rounds(
    api: httpx.AsyncClient, chat: ChatEnv, user: int, db_engine: AsyncEngine
) -> None:
    chat.settings.llm_turn_cap_usd = 0.0003  # one Sonnet-priced request (400 µ$) passes it
    model = chat.online(replan(SKIP_DINNER), say("never sent"), model=SONNET)

    _, events = await chat.send(api, "skip dinner tonight")

    assert len(model.requests) == 1
    done = events[-1]["message"]
    assert (done["mode"], done["offline_reason"]) == ("offline", "budget")
    db_rows = await stored(db_engine, user)
    assert (db_rows.versions, len(db_rows.logs), len(db_rows.calls)) == (2, 1, 1)
    assert db_rows.calls[0].cost_micro_usd == 400


# --- resends and dropped connections ----------------------------------------------------------


async def test_resending_an_answered_message_runs_nothing_again(
    api: httpx.AsyncClient, chat: ChatEnv, user: int, db_engine: AsyncEngine
) -> None:
    model = chat.online(replan(SKIP_DINNER), say("Skipped."))
    client_id = uuid.uuid4()
    await chat.send(api, "skip dinner tonight", client_id=client_id)

    again, _ = await chat.send(api, "skip dinner tonight", client_id=client_id)

    assert again.status_code == 409
    assert again.json()["code"] == "duplicate"
    assert len(model.requests) == 2
    assert len((await stored(db_engine, user)).logs) == 1


async def post_and_leave(body: dict[str, Any], headers: dict[str, str]) -> list[bytes]:
    """POST /chat/messages straight to the ASGI app and disconnect once the `thread` event
    arrives, like a phone that locks its screen. Returns the body chunks received."""
    payload = json.dumps(body).encode()
    received: list[bytes] = []
    left = anyio.Event()
    requested = False

    async def receive() -> Message:
        nonlocal requested
        if not requested:
            requested = True
            return {"type": "http.request", "body": payload, "more_body": False}
        await left.wait()
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        if message["type"] == "http.response.start":
            assert message["status"] == 200
        elif message["type"] == "http.response.body":
            received.append(message.get("body", b""))
            if b'"type":"thread"' in received[-1]:
                left.set()

    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/chat/messages",
        "raw_path": b"/chat/messages",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"test"),
            (b"content-type", b"application/json"),
            *((k.lower().encode(), v.encode()) for k, v in headers.items()),
        ],
        "client": ("test", 1),
        "server": ("test", 80),
    }
    with anyio.fail_after(10):
        await app(scope, receive, send)
    return received


async def test_a_client_that_leaves_mid_turn_still_gets_its_reply_stored(
    chat: ChatEnv, api: httpx.AsyncClient, user: int, db_engine: AsyncEngine
) -> None:
    model = ScriptedChatModel([replan(SKIP_DINNER), say("Skipped tonight's dinner.")])
    gated = Gated(model)
    chat.models = Models(chat=gated)

    received = await post_and_leave(chat.body("skip dinner tonight"), chat.auth("user_a"))
    gated.gate.set()  # the model answers only once the client has gone
    await chat.idle()

    assert b'"type":"thread"' in b"".join(received)
    assert b'"type":"done"' not in b"".join(received)
    db_rows = await stored(db_engine, user)
    assert [row.role for row in db_rows.messages] == ["user", "assistant"]
    assert db_rows.messages[1].text == "Skipped tonight's dinner."
    assert (db_rows.versions, len(db_rows.logs)) == (2, 1)
    assert len(db_rows.calls) == len(model.requests) == 2
    assert db_rows.lock is None
    thread = (await api.get("/chat/thread", headers=chat.auth("user_a"))).json()
    assert thread["pending"] is None
    assert thread["messages"][-1]["attachments"][0]["type"] == "outcome"

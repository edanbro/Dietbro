"""The agent loop against scripted models: every stop path leaves a replayable transcript."""

import copy
from dataclasses import dataclass, field, replace
from typing import Any

import pytest
from pydantic import BaseModel

from larder_llm.agent import AgentResult, Handler, ToolOutcome, check_transcript, run_agent
from larder_llm.client import ChatModel, ModelCall
from larder_llm.fake import (
    Script,
    ScriptedChatModel,
    Step,
    fail,
    fallback,
    refuse,
    reject,
    say,
    think,
    tool,
    tools,
)
from larder_llm.schemas import ReplanInput, SearchRecipesInput
from larder_llm.tools import TOOLS

type Block = dict[str, Any]

SYSTEM: list[Block] = [{"type": "text", "text": "system", "cache_control": {"type": "ephemeral"}}]
USER: Block = {"role": "user", "content": [{"type": "text", "text": "skip dinner tonight"}]}
SKIP = {
    "changes": [
        {
            "intent": "skip",
            "when": {"date": "2026-10-14", "slot": "dinner"},
            "eating_elsewhere": False,
        }
    ]
}


@dataclass
class Recorder:
    """AgentEvents that keep a log and replay it like the web client (a reset clears all)."""

    log: list[tuple[Any, ...]] = field(default_factory=list[tuple[Any, ...]])

    async def text(self, delta: str) -> None:
        self.log.append(("text", delta))

    async def reset(self) -> None:
        self.log.append(("reset",))

    async def tool_started(self, name: str, tool_input: BaseModel) -> None:
        self.log.append(("start", name))

    async def tool_finished(self, name: str, outcome: ToolOutcome) -> None:
        self.log.append(("finish", name, outcome.is_error))

    async def call(self, call: ModelCall) -> None:
        self.log.append(("call", call.status))

    @property
    def shown(self) -> str:
        screen = ""
        for entry in self.log:
            if entry[0] == "text":
                screen += entry[1]
            elif entry[0] == "reset":
                screen = ""
        return screen

    def kinds(self) -> list[str]:
        return [e[0] for e in self.log if e[0] != "text"]


@dataclass
class Tools:
    """Handlers that record what ran, in order."""

    ran: list[tuple[str, BaseModel]] = field(default_factory=list[tuple[str, BaseModel]])
    broken: frozenset[str] = frozenset()

    def handlers(self) -> dict[str, Handler]:
        def make(name: str) -> Handler:
            async def handle(tool_input: BaseModel) -> ToolOutcome:
                self.ran.append((name, tool_input))
                if name in self.broken:
                    raise RuntimeError("database is down")
                return ToolOutcome(f'{{"tool": "{name}", "n": {len(self.ran)}}}')

            return handle

        return {d.name: make(d.name) for d in TOOLS}

    @property
    def names(self) -> list[str]:
        return [n for n, _ in self.ran]


async def run(
    script: list[Script],
    *,
    tools_: Tools | None = None,
    history: list[Block] | None = None,
    model: ChatModel | None = None,
    **kwargs: Any,
) -> tuple[AgentResult, Recorder, Tools, ScriptedChatModel]:
    chat = model if isinstance(model, ScriptedChatModel) else ScriptedChatModel(script)
    before = len(chat.requests)
    events = Recorder()
    handlers = tools_ or Tools()
    result = await run_agent(
        chat,
        system=SYSTEM,
        tools=TOOLS,
        history=history or [],
        user_message=USER,
        handlers=handlers.handlers(),
        events=events,
        **kwargs,
    )
    transcript = [*(history or []), USER, *result.messages]
    assert check_transcript(transcript) == []
    assert events.shown == result.text
    assert len(result.calls) == len(chat.requests) - before
    return result, events, handlers, chat


def roles(result: AgentResult) -> list[str]:
    return [m["role"] for m in result.messages]


def results_of(message: Block) -> list[Block]:
    return [b for b in message["content"] if b["type"] == "tool_result"]


async def test_a_plain_answer() -> None:
    result, events, _, chat = await run([say("Done - dinner is skipped.")])
    assert result.stop == "done"
    assert result.text == "Done - dinner is skipped."
    (message,) = result.messages
    assert message["role"] == "assistant"
    assert [b["type"] for b in message["content"]] == ["thinking", "text"]
    assert message["content"][0]["signature"].startswith("sig-")
    assert chat.requests[0]["messages"] == [USER]
    assert chat.requests[0]["tools"][0]["strict"] is True
    assert events.kinds() == ["call"]


async def test_a_tool_round_then_the_answer() -> None:
    result, events, ran, chat = await run(
        [tool("request_replan", SKIP), say("Skipped tonight's dinner.")]
    )
    assert result.stop == "done"
    assert roles(result) == ["assistant", "user", "assistant"]
    (answer,) = results_of(result.messages[1])
    assert answer["tool_use_id"] == result.messages[0]["content"][1]["id"]
    assert "is_error" not in answer
    assert ran.names == ["request_replan"]
    assert isinstance(ran.ran[0][1], ReplanInput)
    assert result.tools_used == ["request_replan"]
    assert result.writes == 1
    assert events.kinds() == ["call", "start", "finish", "call"]
    assert chat.requests[1]["messages"] == [USER, *result.messages[:2]]


async def test_parallel_calls_run_in_order_and_answer_in_one_message() -> None:
    step = tools(
        [("get_plan", {}), ("search_recipes", {"query": "spicy"}), ("request_replan", SKIP)]
    )
    result, _, ran, _ = await run([step, say("ok")])
    assert ran.names == ["get_plan", "search_recipes", "request_replan"]
    assert roles(result) == ["assistant", "user", "assistant"]
    answers = results_of(result.messages[1])
    assert result.messages[1]["content"] == answers  # nothing but tool results
    ids = [b["id"] for b in result.messages[0]["content"] if b["type"] == "tool_use"]
    assert [a["tool_use_id"] for a in answers] == ids
    assert [a["content"] for a in answers] == [
        '{"tool": "get_plan", "n": 1}',
        '{"tool": "search_recipes", "n": 2}',
        '{"tool": "request_replan", "n": 3}',
    ]


async def test_an_invalid_input_gets_one_correction() -> None:
    bad = tool("search_recipes", {"query": "spicy", "limit": 50})
    good = tool("search_recipes", {"query": "spicy", "limit": 5})
    result, _, ran, _ = await run([bad, good, say("Found some.")])
    assert result.stop == "done"
    (first,) = results_of(result.messages[1])
    assert first["is_error"] is True
    assert first["content"].startswith("Invalid input for search_recipes: limit: ")
    assert ran.names == ["search_recipes"]
    assert isinstance(ran.ran[0][1], SearchRecipesInput)


async def test_a_second_invalid_input_ends_the_turn() -> None:
    bad = tool("search_recipes", {"query": "spicy", "limit": 50})
    missing_intent = tool("request_replan", {"changes": [{"when": {"date": "2026-10-14"}}]})
    result, _, ran, chat = await run([bad, missing_intent])
    assert result.stop == "invalid"
    assert roles(result) == ["assistant", "user", "assistant", "user"]
    assert all(a["is_error"] for m in result.messages[1::2] for a in results_of(m))
    assert ran.names == []
    assert chat.script == []
    assert len(chat.requests) == 2


async def test_calls_after_the_second_invalid_one_are_not_run() -> None:
    bad = ("search_recipes", {"query": 1})
    step = tools([bad, bad, ("request_replan", SKIP)])
    result, _, ran, _ = await run([step])
    assert result.stop == "invalid"
    answers = results_of(result.messages[1])
    assert [a["is_error"] for a in answers] == [True, True, True]
    assert answers[2]["content"] == "Not run: the turn ended."
    assert ran.names == []
    assert result.writes == 0


async def test_unknown_tool_names_and_case_insensitive_matches() -> None:
    result, _, ran, _ = await run(
        [tool("get_weather", {}), tool("Get_Plan", {}), say("Here is your plan.")]
    )
    first, second = results_of(result.messages[1]), results_of(result.messages[3])
    assert first[0]["is_error"] is True
    assert first[0]["content"].startswith("Unknown tool 'get_weather'. The tools are: get_plan,")
    assert "is_error" not in second[0]
    assert ran.names == ["get_plan"]
    assert result.tools_used == ["get_plan"]
    assert result.stop == "done"


async def test_max_rounds_ends_after_the_tool_results() -> None:
    result, _, ran, chat = await run(
        [tool("get_plan", {}), tool("get_pantry", {}), say("never sent")], max_rounds=2
    )
    assert result.stop == "max_rounds"
    assert roles(result) == ["assistant", "user", "assistant", "user"]
    assert ran.names == ["get_plan", "get_pantry"]
    assert len(chat.requests) == 2


async def test_max_tokens_with_a_tool_call_is_dropped() -> None:
    cut = replace(
        tool("request_replan", SKIP, text="Let me change that."), stop_reason="max_tokens"
    )
    result, events, ran, _ = await run([cut])
    assert result.stop == "max_tokens"
    assert result.messages == []
    assert result.text == ""
    assert ran.names == []
    assert ("reset",) in events.log


async def test_max_tokens_with_text_only_is_kept() -> None:
    cut = replace(say("Your plan is"), stop_reason="max_tokens")
    result, _, _, _ = await run([cut])
    assert result.stop == "max_tokens"
    assert roles(result) == ["assistant"]
    assert result.text == "Your plan is"


async def test_a_response_cut_off_while_thinking_is_dropped() -> None:
    cut = Step(({"type": "thinking", "thinking": "", "signature": ""},), "max_tokens")
    result, _, _, _ = await run([cut])
    assert result.messages == []


async def test_a_refusal_is_never_kept() -> None:
    result, events, _, _ = await run([refuse("cyber", after_text="Sure, here is")])
    assert result.stop == "refusal"
    assert result.messages == []
    assert result.text == ""
    assert events.log[-1] == ("reset",)
    assert result.calls[0].status == "refusal"
    assert result.calls[0].error == "cyber"

    result, events, _, _ = await run([refuse()])
    assert result.stop == "refusal"
    assert ("reset",) not in events.log


async def test_a_refusal_after_a_tool_round_keeps_the_round() -> None:
    result, _, ran, _ = await run([tool("get_plan", {}, text="Checking."), refuse()])
    assert result.stop == "refusal"
    assert roles(result) == ["assistant", "user"]
    assert result.text == "Checking."
    assert ran.names == ["get_plan"]


async def test_pause_turn_is_dropped() -> None:
    paused = replace(say("Let me think"), stop_reason="pause_turn")
    result, _, _, _ = await run([paused])
    assert result.stop == "unavailable"
    assert result.messages == []
    assert result.text == ""


async def test_unavailable_after_a_write_keeps_the_completed_rounds() -> None:
    result, events, ran, _ = await run(
        [tool("request_replan", SKIP, text="On it."), fail("529 overloaded", after_text="Done, I")]
    )
    assert result.stop == "unavailable"
    assert roles(result) == ["assistant", "user"]
    assert result.writes == 1
    assert ran.names == ["request_replan"]
    assert result.text == "On it."
    assert [c.status for c in result.calls] == ["ok", "error"]
    # The failed response's text was retracted and the kept text sent again.
    assert events.log[-2:] == [("reset",), ("text", "On it.")]


async def test_rejected() -> None:
    result, _, _, _ = await run([reject()])
    assert result.stop == "rejected"
    assert result.messages == []
    assert result.calls[0].status == "error"


async def test_write_limits() -> None:
    step = tools([("request_replan", SKIP), ("request_replan", SKIP), ("get_plan", {})])
    result, _, ran, _ = await run([step, say("ok")], write_limits={"request_replan": 1})
    answers = results_of(result.messages[1])
    assert [a.get("is_error", False) for a in answers] == [False, True, False]
    assert answers[1]["content"] == (
        "Not run: at most 1 request_replan per message. Put all changes in one request_replan."
    )
    assert ran.names == ["request_replan", "get_plan"]
    assert result.writes == 1
    assert result.stop == "done"


async def test_a_handler_that_raises_gets_an_internal_error() -> None:
    broken = Tools(broken=frozenset({"get_pantry"}))
    result, events, _, _ = await run(
        [tool("get_pantry", {}), say("Sorry, I couldn't read your pantry.")], tools_=broken
    )
    (answer,) = results_of(result.messages[1])
    assert answer == {
        "type": "tool_result",
        "tool_use_id": answer["tool_use_id"],
        "content": "internal error",
        "is_error": True,
    }
    assert ("finish", "get_pantry", True) in events.log
    assert result.stop == "done"


async def test_a_fallback_retracts_the_declined_text() -> None:
    result, events, _, _ = await run([fallback("I can't hel", then=say("Here you go."))])
    assert result.stop == "done"
    assert result.text == "Here you go."
    kinds = [b["type"] for b in result.messages[0]["content"]]
    assert kinds == ["text", "fallback", "thinking", "text"]
    assert ("reset",) in events.log
    (call,) = result.calls
    assert call.model == "fake-chat-fallback"
    assert [m for m, _ in call.parts] == ["fake-chat", "fake-chat-fallback"]


async def test_texts_of_several_responses() -> None:
    result, _, _, _ = await run([tool("get_plan", {}, text="Checking."), say("All good.")])
    assert result.text == "Checking.\n\nAll good."

    result, events, _, _ = await run(
        [tool("get_plan", {}, text="Checking."), refuse(after_text="Well")]
    )
    assert result.text == "Checking."
    assert events.log[-2:] == [("reset",), ("text", "Checking.")]


async def test_inputs_are_not_mutated_and_turns_replay_append_only() -> None:
    chat = ScriptedChatModel([tool("get_plan", {}), say("First."), say("Second.")])
    first, _, _, _ = await run([], model=chat)
    history = [USER, *first.messages]
    frozen = copy.deepcopy(history)
    second, _, _, _ = await run([], model=chat, history=history)
    assert history == frozen
    assert second.text == "Second."
    assert chat.requests[2]["messages"] == [*frozen, USER]


async def test_the_strict_fake_catches_an_edited_history() -> None:
    chat = ScriptedChatModel([say("First."), say("Second.")])
    first, _, _, _ = await run([], model=chat)
    edited = copy.deepcopy([USER, *first.messages])
    edited[1]["content"][0]["thinking"] = "edited"
    with pytest.raises(AssertionError, match="append-only"):
        await run([], model=chat, history=edited)


async def test_a_refused_turn_may_be_left_out_of_the_next_request() -> None:
    chat = ScriptedChatModel([say("First."), refuse(), say("Third.")])
    first, _, _, _ = await run([], model=chat)
    history = [USER, *first.messages]
    refused, _, _, _ = await run([], model=chat, history=history)
    assert refused.stop == "refusal"
    third, _, _, _ = await run([], model=chat, history=history)  # without the refused turn
    assert third.text == "Third."


# --- check_transcript -------------------------------------------------------------------------


def assistant(*blocks: Block) -> Block:
    return {"role": "assistant", "content": list(blocks)}


def user(*blocks: Block) -> Block:
    return {"role": "user", "content": list(blocks)}


USE: Block = {"type": "tool_use", "id": "toolu_a", "name": "get_plan", "input": {}}
RESULT: Block = {"type": "tool_result", "tool_use_id": "toolu_a", "content": "{}"}
TEXT: Block = {"type": "text", "text": "hi"}


def test_check_transcript_accepts_a_good_one() -> None:
    good = [
        user(TEXT),
        assistant(think(), USE),
        user(RESULT),
        user(TEXT),  # the next turn after a turn that ended on tool results
        assistant(think(), TEXT),
        {"role": "user", "content": "plain text is fine"},
    ]
    assert check_transcript(good) == []
    assert check_transcript([]) == []


@pytest.mark.parametrize(
    ("messages", "problem"),
    [
        ([user(TEXT), assistant(USE)], "tool_use without a tool_result next"),
        ([user(TEXT), assistant(USE), user(TEXT)], "tool_use without a tool_result next"),
        ([assistant(TEXT), user(TEXT)], "must start with a user message"),
        ([user(TEXT), assistant(TEXT), assistant(TEXT)], "two assistant messages in a row"),
        (
            [user(TEXT), assistant({"type": "thinking", "thinking": "", "signature": ""}, TEXT)],
            "thinking block without a signature",
        ),
        ([user(TEXT), assistant()], "empty content"),
        ([user(TEXT), assistant(USE), user(TEXT, RESULT)], "tool_result blocks must come first"),
        ([user(RESULT)], "answers no tool_use"),
        (
            [user(TEXT), assistant(USE), user(RESULT), assistant(USE), user(RESULT)],
            "repeated tool_use id",
        ),
        ([user(TEXT), {"role": "system", "content": "x"}], "unexpected role"),
    ],
)
def test_check_transcript_finds_problems(messages: list[Block], problem: str) -> None:
    problems = check_transcript(messages)
    assert any(problem in p for p in problems), problems


# --- the fake itself --------------------------------------------------------------------------


async def test_fake_streams_chunks_that_join_to_the_text() -> None:
    text = "Thursday  is now:\n- Chilli con carne  "
    events = Recorder()
    chat = ScriptedChatModel([say(text)])
    result = await run_agent(
        chat, system=SYSTEM, tools=TOOLS, history=[], user_message=USER, handlers={}, events=events
    )
    deltas = [e[1] for e in events.log if e[0] == "text"]
    assert len(deltas) > 1
    assert "".join(deltas) == text == result.text


async def test_fake_tool_ids_stay_unique_when_a_step_repeats() -> None:
    step = tool("get_plan", {})
    result, _, _, _ = await run([step, step, say("ok")])
    ids = [b["id"] for m in result.messages for b in m["content"] if b["type"] == "tool_use"]
    assert len(ids) == len(set(ids)) == 2


async def test_fake_without_thinking() -> None:
    chat = ScriptedChatModel([say("hi")], thinking=False)
    result, _, _, _ = await run([], model=chat)
    assert [b["type"] for b in result.messages[0]["content"]] == ["text"]

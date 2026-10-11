"""One chat turn as a stream of events (larder_api.schemas.ChatEvent), run by chat.tasks.

    thread -> [status | text | text_reset | outcome | recipe]* -> done | error

1. Emit `thread` (with mode / offline_reason from the gate).
2. Online: history = the current epoch's api_messages (rows in id order, user rows first, rows
   with [] skipped); system = [SYSTEM_PROMPT block with cache_control]; tools = api_tools();
   user message = prompts.user_turn(context.turn_context(scope), text), stored on the user row
   before the model runs. run_agent with handlers.make_handlers(scope), max_rounds,
   write_limits {request_replan: 2, create_recipe: 3}; events: text -> `text`; reset ->
   `text_reset`; tool start -> `status` (fixed friendly wording per tool); call -> log_call
   (adds to scope.cost_micro_usd; past the turn cap no new round starts; a request still
   running at the model deadline - the turn deadline less MODEL_MARGIN_S, at least half of it -
   is cut off and counts as unavailable). Outcomes and created
   recipes are emitted by the handlers as `outcome` / `recipe` events as they happen.
   Ends:
   - done / max_rounds / max_tokens: reply = the agent's text (if empty, a templated summary of
     scope.outcomes).
   - refusal: `text_reset`, fixed reply ("I can't help with that one - I can change your plan
     or answer questions about it."); the user row's api_messages set to [] (never replayed).
   - rejected (400 on replay): start a new epoch and retry once with only the new user turn;
     a second rejection is treated as unavailable.
   - unavailable / invalid: if scope.wrote -> templated summary of scope.outcomes
     (reply.offline_reply(None, outcomes, ..., reason="model_error")), keep the completed
     rounds; else -> `text_reset` and the offline path below (reason "model_error", or
     "budget" past the turn cap) with no models at all (scope.models offline, so food matching
     never asks the fast model), the agent's messages discarded and the user row's
     api_messages set to [].
   check_transcript(user message + agent messages) must be clean before persisting; if not,
   log it and persist display-only (api_messages []), never a broken transcript.
3. Offline: rules.parse_rules(text, today) -> replan.apply_changes(source="offline") when it
   understood anything -> reply.offline_reply(parsed, outcomes, today, reason, announce=mode
   changed since the previous assistant row). Streamed as one `text` event. The user row stores
   a plain user message and the assistant row a plain assistant message (both replayable).
4. Persist the assistant ChatMessage (text, api_messages, mode, offline_reason, attachments =
   the outcome and recipe payloads, suggestions, plan_id = last version created) and
   thread.updated_at; emit `done` (stored message + messages_today). Unexpected exceptions:
   log, persist a display-only reply ("Something went wrong; your plan wasn't changed." - or
   the outcomes summary if scope.wrote), emit `error`. Always release the turn lock (a failed
   release is logged, not an error: the lock goes stale after the deadline).

Channels: `run_turn` yields `thread` first and `done` / `error` last; everything in between
goes out through `scope.emit` as it happens (agent text deltas, tool status lines, the
handlers' outcome and recipe cards), so the order the client sees is the order things happened.
A rejected retry, a refusal or a fallback first clears what was shown (`text_reset`).
"""

import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

import anyio
from pydantic import BaseModel, TypeAdapter
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from larder_api import planning
from larder_api.chat import context, limits, replan
from larder_api.chat.gate import PreparedTurn
from larder_api.chat.handlers import make_handlers
from larder_api.chat.scope import ChatScope, Emit, Models
from larder_api.schemas import (
    Attachment,
    ChatEvent,
    ChatMessageOut,
    DoneEvent,
    ErrorEvent,
    OutcomeEvent,
    RecipeEvent,
    StatusEvent,
    TextEvent,
    TextResetEvent,
    ThreadEvent,
)
from larder_api.settings import Settings
from larder_db import models as db
from larder_llm import prompts, rules
from larder_llm.agent import AgentResult, ToolOutcome, check_transcript, run_agent
from larder_llm.client import (
    AnthropicChatModel,
    CallSink,
    ChatModel,
    LLMUnavailable,
    ModelCall,
    ResetSink,
    TextSink,
    Turn,
)
from larder_llm.reply import OfflineReason, offline_reply
from larder_llm.tools import TOOLS

logger = logging.getLogger(__name__)

type Block = dict[str, Any]

SYSTEM: list[Block] = [
    {"type": "text", "text": prompts.SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
]
WRITE_LIMITS = {"request_replan": 2, "create_recipe": 3}
REFUSED = "I can't help with that one - I can change your plan or answer questions about it."
FAILED = "Something went wrong; your plan wasn't changed."
STATUS = {
    "get_plan": "Checking your plan…",
    "get_pantry": "Checking your pantry…",
    "search_recipes": "Looking for recipes…",
    "explain_meal": "Looking at that meal…",
    "request_replan": "Updating your plan…",
    "create_recipe": "Writing a recipe…",
    "explain_plan_diff": "Comparing plan versions…",
}
# The model must give up this long before the turn's hard deadline, so the turn can still
# reply from what was done and persist.
MODEL_MARGIN_S = 20.0

_attachments = TypeAdapter(list[Attachment])


def message_out(row: db.ChatMessage) -> ChatMessageOut:
    return ChatMessageOut.model_validate(
        {
            "id": row.id,
            "role": row.role,
            "text": row.text,
            "created_at": row.created_at,
            "plan_id": row.plan_id,
            "mode": row.mode,
            "offline_reason": row.offline_reason,
            "attachments": _attachments.validate_python(row.attachments or []),
            "suggestions": row.suggestions or [],
        }
    )


def make_scope(
    prepared: PreparedTurn,
    *,
    emit: Emit,
    sessionmaker: async_sessionmaker[AsyncSession],
    catalog: planning.CatalogCache,
    planner: planning.Planner,
    settings: Settings,
    now: datetime,
) -> ChatScope:
    """The scope a turn's tools are bound to; every model call it reports is logged at once
    and counted against the turn's cap."""

    async def not_yet(_: ModelCall) -> None:
        raise AssertionError("log_call is bound below")

    scope = ChatScope(
        user_id=prepared.user_id,
        today=prepared.today,
        local_time=prepared.local_time,
        now=now,
        thread_id=prepared.thread_id,
        message_id=prepared.message_id,
        raw_text=prepared.text,
        sessionmaker=sessionmaker,
        catalog=catalog,
        planner=planner,
        settings=settings,
        models=prepared.models,
        emit=emit,
        log_call=not_yet,
    )

    async def log_call(call: ModelCall) -> None:
        scope.cost_micro_usd += await limits.log_call(
            sessionmaker, prepared.user_id, prepared.thread_id, call
        )

    scope.log_call = log_call
    return scope


async def run_turn(prepared: PreparedTurn, scope: ChatScope) -> AsyncIterator[ChatEvent]:
    turn = _Turn(prepared, scope)
    try:
        yield turn.thread_event()
        last: ChatEvent
        try:
            last = await turn.run()
        except Exception:
            logger.exception("chat turn for message %s failed", prepared.message_id)
            last = await turn.fail()
        # Free the lock before the client hears `done`, so its next message isn't "busy".
        await turn.release()
        yield last
    except BaseException:  # cancelled (turn deadline, shutdown): still leave a reply behind
        with anyio.CancelScope(shield=True), anyio.move_on_after(5):
            await turn.fail()
        raise
    finally:
        await turn.release()


@dataclass(slots=True)
class _Capped:
    """Stops new model rounds once the turn's spend passes its cap, and cuts off a request
    still running at the model deadline (the SDK's timeout bounds each read and retry, not
    the whole request): the agent then ends as 'unavailable' and the turn replies from what
    was done, or falls back to the rule parser."""

    model: ChatModel
    scope: ChatScope
    cap_micro_usd: int
    deadline: float  # time.monotonic()
    tripped: bool = False

    async def respond(
        self,
        *,
        system: list[Block],
        tools: list[Block],
        messages: list[Block],
        on_text: TextSink,
        on_reset: ResetSink,
        on_call: CallSink,
    ) -> Turn:
        if self.scope.cost_micro_usd >= self.cap_micro_usd:
            self.tripped = True
            raise LLMUnavailable("the turn's model budget is spent")
        with anyio.move_on_after(self.deadline - time.monotonic()):
            return await self.model.respond(
                system=system,
                tools=tools,
                messages=messages,
                on_text=on_text,
                on_reset=on_reset,
                on_call=on_call,
            )
        raise LLMUnavailable("the model ran past the turn's deadline")


def _with_deadline(chat: ChatModel, deadline: float) -> ChatModel:
    """Claude clients bound requests by what's left of the turn (fakes have no clock)."""
    if isinstance(chat, AnthropicChatModel):
        return AnthropicChatModel(
            chat.client,
            chat.model,
            effort=chat.effort,
            max_tokens=chat.max_tokens,
            purpose=chat.purpose,
            deadline=deadline,
        )
    return chat


class _Events:
    """Agent progress -> SSE events and accounting."""

    def __init__(self, scope: ChatScope) -> None:
        self.scope = scope

    async def text(self, delta: str) -> None:
        await self.scope.emit(TextEvent(delta=delta))

    async def reset(self) -> None:
        await self.scope.emit(TextResetEvent())

    async def tool_started(self, name: str, tool_input: BaseModel) -> None:
        await self.scope.emit(StatusEvent(text=STATUS.get(name, "Working on it…")))

    async def tool_finished(self, name: str, outcome: ToolOutcome) -> None:
        return None

    async def call(self, call: ModelCall) -> None:
        await self.scope.log_call(call)


class _Turn:
    def __init__(self, prepared: PreparedTurn, scope: ChatScope) -> None:
        self.p = prepared
        self.scope = scope
        self.started = time.monotonic()
        self.epoch = prepared.epoch
        self.mode: Literal["llm", "offline"] = "llm" if prepared.models.online else "offline"
        self.offline_reason: OfflineReason | None = prepared.models.offline_reason
        self.reply = ""
        self.suggestions: tuple[str, ...] = ()
        self.user_api: list[Block] = []  # what the user row replays (its context + words)
        self.assistant_api: list[Block] = []  # what this turn added after it
        self.attachments: list[Block] = []  # outcome / recipe cards, in the order sent
        self.shown = ""  # reply text the client currently shows
        self.persisted = False
        self.released = False
        self.reset_sent = False  # a text_reset went out this turn
        deadline_s = scope.settings.chat_turn_deadline_s
        self.model_deadline = self.started + max(deadline_s - MODEL_MARGIN_S, deadline_s / 2)
        sink = scope.emit

        async def emit(event: object) -> None:
            self._record(event)
            await sink(event)

        scope.emit = emit

    def _record(self, event: object) -> None:
        if isinstance(event, TextEvent):
            self.shown += event.delta
        elif isinstance(event, TextResetEvent):
            self.shown = ""
            self.reset_sent = True
        elif isinstance(event, OutcomeEvent | RecipeEvent):
            self.attachments.append(event.model_dump(mode="json"))

    def thread_event(self) -> ThreadEvent:
        return ThreadEvent(
            thread_id=self.p.thread_id,
            message_id=self.p.message_id,
            mode=self.mode,
            offline_reason=self.offline_reason,
        )

    async def run(self) -> DoneEvent:
        chat = self.p.models.chat
        if chat is None:
            await self._offline(self.p.models.offline_reason or "no_key", replayable=True)
        else:
            await self._online(chat)
        return await self._persist()

    async def release(self) -> None:
        """Free the turn lock. A failure is logged, not raised: the reply is already stored,
        and the lock goes stale after the deadline."""
        if not self.released:
            self.released = True
            try:
                await limits.release_turn(
                    self.scope.sessionmaker, self.p.user_id, self.p.lock_token
                )
            except Exception:
                logger.exception("couldn't release the turn lock for message %s", self.p.message_id)

    # --- online -------------------------------------------------------------------------------

    async def _online(self, chat: ChatModel) -> None:
        ctx = await context.turn_context(self.scope)
        user_message: Block = dict(prompts.user_turn(ctx, self.p.text))
        self.user_api = [user_message]
        await self._store_user()
        history = [] if self.p.new_epoch else await self._history()
        model = _Capped(
            _with_deadline(chat, self.model_deadline),
            self.scope,
            self.p.turn_cap_micro_usd,
            self.model_deadline,
        )
        result = await self._agent(model, history, user_message)
        if result.stop == "rejected" and not self.scope.wrote:
            logger.warning("replay of thread %s rejected; new epoch", self.p.thread_id)
            await self._clear()
            self.epoch += 1
            await self._store_user()
            result = await self._agent(model, [], user_message)
        if result.stop == "rejected":
            result.stop = "unavailable"

        if result.stop == "refusal":
            await self._clear(always=True)
            summary = self._summary("model_error") if self.scope.wrote else ""
            await self._say(f"{REFUSED}\n{summary}" if summary else REFUSED)
            self.user_api = []
            return
        if result.stop in ("unavailable", "invalid"):
            reason: OfflineReason = "budget" if model.tripped else "model_error"
            await self._clear(always=not self.scope.wrote)
            if self.scope.wrote:
                announce = await self._announce(reason)
                await self._say(self._summary(reason, announce=announce))
                self.assistant_api = result.messages
                self.mode, self.offline_reason = "offline", reason
            else:
                self.user_api = []
                # Offline means no model at all: the fast one is spent or failing too.
                self.scope.models = Models(offline_reason=reason)
                await self._offline(reason, replayable=False)
            self._check_transcript()
            return
        # done / max_rounds / max_tokens
        if result.text.strip():
            self.reply = result.text
        else:
            await self._clear()
            await self._say(self._summary("model_error"))
        self.assistant_api = result.messages
        self._check_transcript()

    async def _agent(self, model: ChatModel, history: list[Block], user: Block) -> AgentResult:
        return await run_agent(
            model,
            system=SYSTEM,
            tools=TOOLS,
            history=history,
            user_message=user,
            handlers=make_handlers(self.scope),
            events=_Events(self.scope),
            max_rounds=self.scope.settings.llm_max_rounds,
            write_limits=WRITE_LIMITS,
        )

    async def _history(self) -> list[Block]:
        """The epoch's transcript so far: rows in id order from the first user row; rows that
        were never replayable ([]) are skipped."""
        async with self.scope.sessionmaker() as session:
            rows = await session.execute(
                select(db.ChatMessage.role, db.ChatMessage.api_messages)
                .where(
                    db.ChatMessage.thread_id == self.p.thread_id,
                    db.ChatMessage.api_epoch == self.epoch,
                    db.ChatMessage.id < self.p.message_id,
                )
                .order_by(db.ChatMessage.id)
            )
            messages: list[Block] = []
            for role, api in rows:
                if api and (messages or role == "user"):
                    messages += api
        return messages

    def _check_transcript(self) -> None:
        if not self.user_api:
            self.assistant_api = []
            return
        problems = check_transcript([*self.user_api, *self.assistant_api])
        if problems:
            logger.error(
                "turn for message %s left a broken transcript, stored display-only: %s",
                self.p.message_id,
                problems,
            )
            self.user_api, self.assistant_api = [], []

    # --- offline ------------------------------------------------------------------------------

    async def _offline(self, reason: OfflineReason, *, replayable: bool) -> None:
        parsed = rules.parse_rules(self.p.text, self.scope.today)
        if parsed.understood:
            await self.scope.emit(StatusEvent(text=STATUS["request_replan"]))
            outcome = await replan.apply_changes(self.scope, list(parsed.changes), source="offline")
            self.scope.outcomes.append(outcome)
            await self.scope.emit(OutcomeEvent.model_validate(outcome.model_dump()))
        reply = offline_reply(
            parsed,
            self.scope.outcomes,
            self.scope.today,
            reason=reason,
            announce=await self._announce(reason),
        )
        await self._say(reply.text)
        self.suggestions = reply.suggestions
        self.mode, self.offline_reason = "offline", reason
        if replayable:
            words = f"<user_message>{prompts.escape(self.p.text)}</user_message>"
            self.user_api = [{"role": "user", "content": [{"type": "text", "text": words}]}]
            self.assistant_api = [
                {"role": "assistant", "content": [{"type": "text", "text": reply.text}]}
            ]
        else:
            self.user_api, self.assistant_api = [], []

    async def _announce(self, reason: OfflineReason) -> bool:
        """Say why replies are simple once: when the previous reply wasn't offline for the same
        reason (or this is the thread's first reply)."""
        async with self.scope.sessionmaker() as session:
            previous = (
                await session.execute(
                    select(db.ChatMessage.mode, db.ChatMessage.offline_reason)
                    .where(
                        db.ChatMessage.thread_id == self.p.thread_id,
                        db.ChatMessage.role == "assistant",
                        db.ChatMessage.id < self.p.message_id,
                    )
                    .order_by(db.ChatMessage.id.desc())
                    .limit(1)
                )
            ).one_or_none()
        return previous is None or tuple(previous) != ("offline", reason)

    def _summary(self, reason: OfflineReason, *, announce: bool = False) -> str:
        """What this turn changed, in templated words (the model couldn't finish)."""
        return offline_reply(
            None, self.scope.outcomes, self.scope.today, reason=reason, announce=announce
        ).text

    # --- the client's text ------------------------------------------------------------------

    async def _clear(self, *, always: bool = False) -> None:
        """Clear the reply shown so far; `always`: also when nothing is shown, unless a reset
        already went out this turn (the client then needs exactly one)."""
        if self.shown or (always and not self.reset_sent):
            await self.scope.emit(TextResetEvent())

    async def _say(self, text: str) -> None:
        """The reply, as one text event after whatever is shown (normally nothing)."""
        self.reply = self.shown + text
        await self.scope.emit(TextEvent(delta=text))

    # --- persistence --------------------------------------------------------------------------

    def _now(self) -> datetime:
        return self.scope.now + timedelta(seconds=time.monotonic() - self.started)

    async def _store_user(self) -> None:
        async with self.scope.sessionmaker() as session, session.begin():
            await self._update_user(session)

    async def _update_user(self, session: AsyncSession) -> None:
        await session.execute(
            update(db.ChatMessage)
            .where(db.ChatMessage.id == self.p.message_id)
            .values(api_messages=self.user_api, api_epoch=self.epoch)
            .execution_options(synchronize_session=False)
        )

    def _plan_id(self) -> int | None:
        return next((o.plan_id for o in reversed(self.scope.outcomes) if o.plan_id), None)

    async def _persist(self) -> DoneEvent:
        now = self._now()
        async with self.scope.sessionmaker() as session, session.begin():
            await self._update_user(session)
            row = db.ChatMessage(
                thread_id=self.p.thread_id,
                user_id=self.p.user_id,
                role="assistant",
                text=self.reply,
                api_messages=self.assistant_api,
                api_epoch=self.epoch,
                mode=self.mode,
                offline_reason=self.offline_reason,
                attachments=self.attachments,
                suggestions=list(self.suggestions),
                plan_id=self._plan_id(),
                created_at=now,
            )
            session.add(row)
            await session.execute(
                update(db.ChatThread)
                .where(db.ChatThread.id == self.p.thread_id)
                .values(updated_at=now)
                .execution_options(synchronize_session=False)
            )
            await session.flush()
            out = message_out(row)
        self.persisted = True
        return DoneEvent(message=out, messages_today=self.p.messages_today)

    async def fail(self) -> ErrorEvent:
        """Leave a display-only reply for a turn that broke (or ran out of time): what was
        changed, if anything, else that nothing was."""
        text = self._summary("model_error") if self.scope.wrote else FAILED
        if not self.persisted:
            self.reply, self.suggestions = text, ()
            self.user_api, self.assistant_api = [], []
            try:
                await self._persist()
            except Exception:
                logger.exception("couldn't store the reply to message %s", self.p.message_id)
        return ErrorEvent(message=text)

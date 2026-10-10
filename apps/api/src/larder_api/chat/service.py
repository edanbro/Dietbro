"""One chat turn as a stream of events (larder_api.schemas.ChatEvent), run by chat.tasks.

    thread -> [status | text | text_reset | outcome | recipe]* -> done | error

1. Emit `thread` (with mode / offline_reason from the gate).
2. Online: history = the current epoch's api_messages (rows in id order, user rows first, rows
   with [] skipped); system = [SYSTEM_PROMPT block with cache_control]; tools = api_tools();
   user message = prompts.user_turn(context.turn_context(scope), text), stored on the user row
   before the model runs. run_agent with handlers.make_handlers(scope), max_rounds,
   write_limits {request_replan: 2, create_recipe: 3}; events: text -> `text`; reset ->
   `text_reset`; tool start -> `status` (fixed friendly wording per tool); call -> log_call
   (adds to scope.cost_micro_usd; past the turn cap no new round starts). Outcomes and created
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
     rounds; else -> `text_reset` and the offline path below (reason "model_error"), the
     agent's messages discarded and the user row's api_messages set to [].
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
   the outcomes summary if scope.wrote), emit `error`. Always release the turn lock.
"""

from collections.abc import AsyncIterator

from larder_api.chat.gate import PreparedTurn
from larder_api.chat.scope import ChatScope
from larder_api.schemas import ChatEvent


async def run_turn(prepared: PreparedTurn, scope: ChatScope) -> AsyncIterator[ChatEvent]:
    raise NotImplementedError
    yield  # pragma: no cover

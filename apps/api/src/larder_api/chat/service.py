"""One chat turn as a stream of events (larder_api.schemas.ChatEvent).

    thread -> [status | text | plan | recipe]* -> done | error

1. Store the user's message (new thread if none / requested), emit `thread`.
2. Online (Models.online and under the cost cap): replay the thread's last
   settings.chat_history_turns turns (ChatMessage.api_messages, in order), append the new user
   turn (larder_llm.prompts.user_turn with the context block), run larder_llm.agent.run_agent
   with handlers.make_handlers. Text deltas -> `text`; tool starts -> `status` (fixed, friendly
   wording per tool); each request_replan outcome with a new plan -> `plan`; each created
   recipe -> `recipe`.
   If the agent stops with "invalid" or raises LLMUnavailable before any text was streamed, run
   the offline path for this message instead; if text was already streamed, emit `error`.
   Refusal -> a short fixed reply ("I can't help with that one...").
3. Offline: larder_llm.rules.parse_rules(text, today) -> replan.apply_changes(source="offline")
   when anything was understood -> larder_llm.reply.offline_reply; streamed as one `text` event.
4. Persist: the assistant ChatMessage (text, api_messages = the agent's messages, or a plain
   assistant text message offline; mode; plan_id of the last plan created), llm_calls rows,
   thread.updated_at. Emit `done` with the stored message. Any unexpected exception -> log it,
   persist what is safe, emit `error` with a generic message.
"""

from collections.abc import AsyncIterator

from larder_api.chat.scope import ChatScope
from larder_api.schemas import ChatEvent


async def run_turn(scope: ChatScope) -> AsyncIterator[ChatEvent]:
    raise NotImplementedError
    yield  # pragma: no cover

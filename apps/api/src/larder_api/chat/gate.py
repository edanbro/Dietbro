"""Everything about a chat message that can fail runs here, as a dependency of
POST /chat/messages, so failures are real HTTP errors (inside the SSE generator they would
arrive as an empty 200 stream). In order, in one short transaction:

1. `today` within a day of the clock's UTC date, and not earlier than the `today` of the
   thread's previous user message -> else 400 bad_today.
2. thread: body.thread_id must be the user's (404 thread_not_found); omitted -> the latest
   thread, or a new one.
3. duplicate client_id for this user -> if its turn is still running, 409 busy with that
   message_id; if answered, 409 duplicate with the message id (the client then reloads the
   thread). No second turn either way.
4. turn lock (limits.acquire_turn with a fresh token) -> else 409 busy (+ the pending message id).
5. messages in the last 24 h >= llm_daily_messages -> release the lock, 429 daily_limit with
   retry_at.
6. mode: Models from get_models, then limits.budget -> online or offline (reason).
7. store the user's ChatMessage (text, client_id; api_messages filled by the turn), epoch =
   current epoch or a new one (last message older than chat_epoch_idle_min, or the epoch's
   stored api_messages estimated over chat_epoch_max_tokens at ~4 chars/token); set the lock's
   message id; commit.
Returns PreparedTurn; the turn task owns releasing the lock from here on.
"""

import uuid
from dataclasses import dataclass
from datetime import date, time

from larder_api.chat.scope import Models


@dataclass(frozen=True, slots=True)
class PreparedTurn:
    user_id: int
    thread_id: int
    message_id: int
    epoch: int
    new_epoch: bool
    lock_token: uuid.UUID
    text: str
    today: date
    local_time: time | None
    models: Models  # chat=None when offline for this turn (models.offline_reason says why)
    turn_cap_micro_usd: int
    messages_today: int  # including this one

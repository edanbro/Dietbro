# ADR-0013: The LLM layer - one agent with typed tools, a deterministic executor, an offline path

- Status: Proposed
- Date: 2026-10-10

## Context

M4 adds the chat (PLAN §7): the user reports cravings, off-plan food, skipped meals and swaps, and
asks about the plan; the app re-plans and explains. ADR-0002 fixes the principle (the LLM never
outputs the plan). This ADR fixes how the language layer is shaped, which models it uses, and
what happens without a model. Constraints: allergies are hard and must hold in tests with zero
violations; a per-user budget of about $1/month; CI has no API key; latency should feel like a
chat on a phone.

Options considered for the shape:

1. **LLM-only**: the model reads the plan and writes a new one. Rejected by ADR-0002; it is the
   M7 baseline.
2. **Router**: a cheap model (Haiku) classifies every message into typed intents; deterministic
   code executes them and templates the reply; a bigger model handles only questions. Cheapest,
   but two conversational paths, and templated replies to every common message.
3. **One agent with typed tools** (chosen): a single Sonnet agent loop per turn whose write tools
   take typed changes; a deterministic executor applies them through the planner and validator;
   a rule parser plus templated replies stand in when no model is available.

## Decision

- **Agent**: `claude-sonnet-5-5` at effort `low` (chat-style turns; PLAN §3 picks Sonnet for chat
  and replan reasoning), at most 6 model responses per turn, tools listed in DESIGN §9.2. The
  write tools (`request_replan`, `create_recipe`) take strict, Pydantic-generated schemas; their
  inputs are the PLAN §7 intent shape (`intent, when, tags, dish?, strength`). Pydantic
  re-validates server-side; one corrective retry, then the offline path.
- **Executor**: `larder_api.chat.replan` is the only code that changes a plan. It locks the past,
  encodes changes as locks / off-plan intake / candidate edits on the M3 planning contract
  (ADR-0009: `locked`, `extra`, `previous` already exist), runs the planner and the validator's
  outcome rules, and saves a new version. The model sees the diff it produced and explains it.
- **Fast model**: `claude-haiku-5-5` structured outputs only pick among candidates we supply
  (which USDA food is "Big Mac"?). PLAN's "Haiku for cheap parsing" is this: parsing food words
  into database ids, never free-form numbers. Nutrition is always computed from USDA data.
- **Offline path**: a rule parser (`larder_llm.rules`) covers the four intents in common
  phrasings; the same executor runs; replies are templated. Used without a key (CI, e2e,
  self-hosting), over the monthly cost cap, and when the model fails twice.
- **Transcript**: append-only. Each chat message stores the exact API messages it added (thinking
  blocks included) and is replayed as-is on the next turn; per-turn context (today, plan,
  allergies) goes in the user turn, never the system prompt. This keeps the tools + system prefix
  cacheable and replayed thinking valid; `block_binding: drop_block` covers system-prompt
  changes between deploys.
- **Requests**: streamed (`beta.messages.stream`), adaptive thinking (Sonnet 5.5 cannot disable
  it; `low` keeps it short), automatic prompt caching, server-side refusal fallback
  (`fallbacks: "default"`), `strict: true` tools without eager input streaming (inputs are under
  1 KB; we keep the server's schema guarantee). Refusals end the turn with a fixed reply.
- **Streaming to the client**: server-sent events over `POST /chat/messages` (FastAPI's
  `EventSourceResponse`; typed events in the OpenAPI schema); the browser reads them with
  `fetch` + a stream reader, since `EventSource` can't send the auth header.
- **No embeddings in the API**: recipe search matches the model's words against names, tags,
  cuisines and ingredients. The model does the semantic expansion ("spicy" -> chilli, curry);
  loading fastembed in the API would add ~200 MB and a model download for little gain here.
- **Limits and accounting**: every request -> `llm_calls` (tokens, list-price cost in
  micro-dollars, latency, status). 60 messages/user/day (HTTP 429), $1/user/month (then offline).
  One turn at a time per user (Redis lock).

## Consequences

- Plans changed from chat carry the same guarantees as plans from `POST /plans`: the validator
  gates both, and the tests assert it with adversarial scripted models.
- Every chat turn costs one Sonnet loop (est. 1-2 cents with caching). If M7/M9 numbers show
  that's too much, a Haiku pre-router (option 2) can be added in front without changing tools,
  executor or storage.
- The model can still say something unsafe in prose (suggest a dish it shouldn't). The system
  prompt forbids it and only tool-checked recipes can enter a plan; M7 evals measure it.
- Replays depend on stored transcripts: a thread is capped at its last 20 turns, older context is
  dropped (and its thinking blocks with it).
- CI and the e2e test exercise the offline path end to end; the model path is covered by scripted
  fakes and by `make llm-smoke` (manual, needs a key).

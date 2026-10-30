# ADR-0018: Remove the chat; keep typed changes, use the model only where typing beats tapping

- Status: Accepted (supersedes the conversational parts of ADR-0013 and ADR-0014's chat path)
- Date: 2026-10-30

## Context

M4 built a chat (ADR-0013): the user typed what changed ("skip dinner tonight", "had pizza for
lunch", "something spicy on Friday") and an agent with typed tools re-planned. M5 then gave the
plan screen the same changes as one-tap actions (ADR-0015): every meal's menu offers skip, swap
(with quick, pantry, favourite and cheaper filters), swap with another day, cook extra for
tomorrow and "had something else"; the diary logs exact foods. Looking at the app as a user:

- Every intent the chat handled has a faster, unambiguous control next to the meal it is about.
  Typing "skip Thursday's dinner" takes longer than two taps and can be misread.
- A blank text box doesn't say what it can do: the chat page needed a list of example phrases.
- Without a key it fell back to a rule parser and said so ("Simple replies: no AI key"), which
  made the product look less capable, not more.
- It was the only feature with a per-message model cost, right before hosting (M8) and beta
  users (M9), and `create_recipe` let a model draft recipes, against the product's pitch.
- It took one of six bottom-bar tabs while the diary, used every day, sat behind a header icon.

## Decision

- Remove the conversation: `POST /chat/messages`, threads and messages (tables dropped in
  migration 0027), the agent loop, tools, prompts, the offline rule parser, streaming, the chat
  page and its tab. The bottom bar becomes Plan, Shopping, Recipes, Pantry, Diary; the profile
  moves to the header (phone) and the rail's foot (desktop).
- Keep the contract that made the chat safe, because the screens already use it: typed changes
  (`larder_llm.schemas`), the executor and its safety gate (`larder_api.changes`, renamed from
  `chat`), `POST /plans/replan`, the per-user replan lock (renamed from the chat turn lock) and
  the model budget.
- Use a model only where language really beats taps, always filling typed inputs that the same
  deterministic code checks: turning a free-text description of a meal into foods and amounts
  for the diary, and choosing among database candidates when an ingredient name is ambiguous.
  The model never sees or writes the plan (ADR-0002 holds).

## Consequences

- One way to change the plan, on the screen where the plan is. Fewer moving parts to host: no
  detached turn tasks, no SSE, no transcript storage or epochs.
- The "LLM for language, solver for guarantees" split stays, with the language half smaller
  and placed where it saves the user work; its cost per user drops to a few structured calls.
- Chat history is not migrated (it held no state the plan needs: changes and logs live in
  `cravings` and `meal_logs`, which stay). Old `meal_logs.source` values "chat"/"offline" stay
  as history.
- The adversarial safety tests now attack `POST /plans/replan` and drafted recipes directly.

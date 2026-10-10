"""The per-turn context block (larder_llm.prompts.TurnContext) from the database: the current
plan from today to its end only (dates, meals with recipe ids, kcal per day, logged meals),
targets, allergies and avoided foods by name, diet, budget, and up to 8 pantry items expiring
within 5 days. Kept to about 400 tokens: every copy is replayed in later turns of the epoch."""

from larder_api.chat.scope import ChatScope
from larder_llm.prompts import TurnContext


async def turn_context(scope: ChatScope) -> TurnContext:
    raise NotImplementedError

"""The per-turn context block (larder_llm.prompts.TurnContext) from the database: the current
plan (dates, meals, kcal per day, meals logged off-plan), targets, allergies and avoided foods by
name, diet, budget, and up to 8 pantry items expiring within 5 days."""

from larder_api.chat.scope import ChatScope
from larder_llm.prompts import TurnContext


async def turn_context(scope: ChatScope) -> TurnContext:
    raise NotImplementedError

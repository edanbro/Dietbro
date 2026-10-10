"""Templated replies for the offline path: deterministic text from what the executor did.

Short and specific, the same shape the model is asked to use: one or two sentences, then the
changed meals ("Thu dinner: Lasagne -> Chilli con carne"). Mentions estimates as estimates, and
says plainly when nothing could be done and what the user can try instead.
"""

from datetime import date

from larder_llm.outcome import ReplanOutcome
from larder_llm.rules import RuleParse

__all__ = ["HELP_TEXT", "offline_reply"]

HELP_TEXT = (
    'I can change your plan when you tell me things like "skip dinner tonight", '
    '"had pizza for lunch", "craving something spicy on Friday" or "swap Thursday\'s dinner".'
)


def offline_reply(parsed: RuleParse, outcome: ReplanOutcome | None, today: date) -> str:
    """`outcome` is None when nothing was attempted (not understood, or no plan yet)."""
    raise NotImplementedError

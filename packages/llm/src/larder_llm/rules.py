"""Offline parser: plain-English chat messages -> typed changes, with no model.

Used when there is no API key, the user is over their LLM cap, or the model failed twice
(PLAN §7: "fall back to deterministic path"). It covers the four intents in their common
phrasings and says when it didn't understand, rather than guessing:

    "skip dinner tonight", "eating out on Friday", "not having lunch tomorrow"   -> Skip
    "had a pizza for lunch", "I ate 2 slices of cake today"                      -> AteOffPlan
    "craving something spicy tonight", "I want lasagne on Thursday"              -> Craving
    "swap Thursday's dinner", "change tomorrow's lunch to something with rice"   -> Swap

Dates resolve against `today` (the user's local date): today/tonight/tomorrow, weekday names
(the next such day, today included), "on the 14th". "Tonight" means dinner. A message with a
day but no meal for skip/swap/craving defaults to dinner only when it says "tonight"; otherwise
it is not understood (we don't guess which meal).
"""

from dataclasses import dataclass
from datetime import date

from larder_llm.schemas import AteOffPlan, Craving, Skip, Swap

__all__ = ["RuleParse", "parse_rules"]

type RuleChange = Craving | AteOffPlan | Skip | Swap


@dataclass(frozen=True, slots=True)
class RuleParse:
    changes: tuple[RuleChange, ...]
    understood: bool  # False: nothing actionable recognised; reply with what we can do


def parse_rules(text: str, today: date) -> RuleParse:
    raise NotImplementedError

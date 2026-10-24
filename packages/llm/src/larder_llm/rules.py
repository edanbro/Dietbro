"""Offline parser: plain-English chat messages -> typed changes, with no model.

Used when there is no API key, the user is over their LLM budget, or the model failed before any
change was applied (PLAN §7: "fall back to deterministic path"). It covers the four intents in
their common phrasings, splits a message into clauses (and / then / , / .), and reports the
clauses it didn't understand instead of guessing:

    "skip dinner tonight", "not having lunch tomorrow", "eating out on Friday"   -> Skip
    "had a pizza for lunch", "ate 2 slices of cake yesterday", "had a curry last night"
                                                                                 -> AteOffPlan
    "craving something spicy tonight", "I want lasagne on Thursday"              -> Craving
    "swap Thursday's dinner", "change tomorrow's lunch to something with rice"   -> Swap

Dates resolve against `today` (the user's local date): today / tonight / this morning /
tomorrow / yesterday / last night, weekday names and "on the 14th". A weekday means the most
recent such day (today included) for past tense and logged food (had, ate, grabbed, was), the
next such day (today included) otherwise. Meals: breakfast (brekkie), lunch, dinner (tea,
supper, tonight), snack; a missing meal is left as `slot=None` (the executor decides and says
what it assumed). eating_elsewhere is true only for eat-out phrases (eating out, out for dinner,
at a friend's / mum's, restaurant, takeaway), false otherwise (not hungry, fasting, skipping).
Questions ("should I skip dinner?") and negations ("I'm not skipping lunch", "don't change
Friday") produce no change. Craving strength is soft unless the user insists ("I really want",
"must have"). Every HELP_TEXT example parses.
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta

from larder_core.meals import Slot
from larder_llm.schemas import (
    MAX_CHANGES,
    MAX_TEXT,
    AteOffPlan,
    Craving,
    OffPlanItem,
    Skip,
    Swap,
    When,
)

__all__ = ["RuleChange", "RuleParse", "parse_rules"]

type RuleChange = Craving | AteOffPlan | Skip | Swap


@dataclass(frozen=True, slots=True)
class RuleParse:
    changes: tuple[RuleChange, ...]
    unparsed: tuple[str, ...]  # clauses that weren't understood (verbatim)
    # Complete phrases this parser would understand, offered as tap-to-send chips when a clause
    # was ambiguous ("skip Friday lunch", "skip Friday dinner"); each must parse.
    suggestions: tuple[str, ...] = ()

    @property
    def understood(self) -> bool:
        return bool(self.changes)


# "What can I make with spinach?", "any recipes using leftover chicken", "ideas for dinner":
# a question about recipes, not a change.
_RECIPE_QUESTION = re.compile(
    r"^\s*(?:(?:so|ok|okay|hey|hi)[\s,]+)?(?:"
    r"(?:what|which)\s+(?:else\s+)?(?:can|could|should|shall)\s+(?:i|we)\s+(?:make|cook|do)"
    r"|(?:any|got\s+any|some)?\s*(?:recipes?|ideas?|suggestions?)"
    r"|(?:what|which)\s+recipes?(?=\s+(?:use|uses|have|has|with))"
    r")\b(?:\s+(?:with|using|from|for|that\s+uses?|use|uses|have|has)\s+(?P<what>.+?))?"
    r"(?:\s+(?:tonight|today|tomorrow|this\s+week|for\s+(?:breakfast|lunch|dinner|tea|supper)))?"
    r"[\s?.!]*$",
    re.IGNORECASE,
)
_QUESTION_TAIL = re.compile(
    r"\s+(?:before\s+(?:it|they)\s+go(?:es)?\s+off|before\s+.*|tonight|today|tomorrow|"
    r"this\s+week|for\s+(?:breakfast|lunch|dinner|tea|supper))\b.*$",
    re.IGNORECASE,
)
_LEFTOVER_WORDS = re.compile(
    r"\b(?:the|some|my|leftover|left\s+over|what's\s+left\s+of)\s+", re.IGNORECASE
)


def recipe_question(text: str) -> str | None:
    """A question about what to cook: the foods it names ("spinach and milk"), "" for none
    ("what can I make?": from the pantry), or None when it isn't one."""
    m = _RECIPE_QUESTION.match(text.replace("\u2019", "'"))
    if m is None:
        return None
    what = _QUESTION_TAIL.sub("", m.group("what") or "").strip()
    what = _LEFTOVER_WORDS.sub("", what).strip(" ,.")
    if re.fullmatch(
        r"(?:breakfast|lunch|dinner|tea|supper|pantry|what\s+i\s+have)?", what, re.IGNORECASE
    ):
        return ""
    return what[:80]


def parse_rules(text: str, today: date) -> RuleParse:
    """The changes in the order they were said; clauses it can't read are reported verbatim,
    never guessed. At most MAX_CHANGES changes (later clauses are reported as not understood)."""
    changes: list[RuleChange] = []
    vague: set[int] = set()  # indexes of skips from clauses that named no day or meal
    unparsed: list[str] = []
    for clause in _clauses(text):
        if _NOISE.match(clause.text):
            continue
        got = _parse_clause(clause.text, clause.question, today)
        if got is None:
            unparsed.append(clause.verbatim)
            continue
        new, explicit = got
        last = changes[-1] if changes else None
        if not explicit and len(new) == 1 and isinstance(new[0], Skip) and isinstance(last, Skip):
            # "skip dinner tonight, eating at my mum's": the second clause explains the first.
            if new[0].eating_elsewhere:
                changes[-1] = last.model_copy(update={"eating_elsewhere": True})
            continue
        if (
            explicit
            and isinstance(last, Skip)
            and len(changes) - 1 in vague
            and all(isinstance(c, Skip) and c.when.date == last.when.date for c in new)
        ):
            # "not hungry, skip lunch": the second clause says which meal the first meant.
            changes.pop()
            vague.discard(len(changes))
            if last.eating_elsewhere:
                new = [c.model_copy(update={"eating_elsewhere": True}) for c in new]
        fresh = [c for c in new if c not in changes]
        if len(changes) + len(fresh) > MAX_CHANGES:
            unparsed.append(clause.verbatim)
            continue
        if not explicit and len(fresh) == 1 and isinstance(fresh[0], Skip):
            vague.add(len(changes))
        changes += fresh
    suggestions = [s for c in changes if c.when.slot is None for s in _suggest(c, today)]
    return RuleParse(tuple(changes), tuple(unparsed), tuple(dict.fromkeys(suggestions)))


# --- vocabulary -------------------------------------------------------------------------------

_I = re.IGNORECASE
_SLOT_WORDS: dict[str, Slot] = {
    "breakfast": Slot.BREAKFAST,
    "brekkie": Slot.BREAKFAST,
    "brekky": Slot.BREAKFAST,
    "lunch": Slot.LUNCH,
    "lunchtime": Slot.LUNCH,
    "dinner": Slot.DINNER,
    "supper": Slot.DINNER,
    "tea": Slot.DINNER,
    "teatime": Slot.DINNER,
    "snack": Slot.SNACK,
    "snacks": Slot.SNACK,
}
_SLOTS = r"breakfast|brekkie|brekky|lunchtime|lunch|dinner|supper|teatime|snacks?"
_SLOT_RE = re.compile(
    rf"(?:\b(?:for|at|over|with)\s+)?(?:\b(?:my|our|the|your|a)\s+)?\b(?P<slot>{_SLOTS})\b"
    # "tea" is a meal only where a meal fits ("for tea", "skip tea", "Friday's tea").
    r"|(?:\b(?:for|at|skip|skipping|skipped|miss|missing|missed|my|our|no)\s+|(?<='s)\s+)"
    r"(?P<tea>tea)\b"
    r"|\b(?P<tea2>tea)(?=\s+(?:tonight|tomorrow|today|on\b|time\b))",
    _I,
)
_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "tues": 1,
    "wednesday": 2,
    "weds": 2,
    "thursday": 3,
    "thurs": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_PARTS = {
    "night": Slot.DINNER,
    "evening": Slot.DINNER,
    "morning": Slot.BREAKFAST,
    "lunchtime": Slot.LUNCH,
}
_RELATIVE: tuple[tuple[re.Pattern[str], int, Slot | None], ...] = tuple(
    (re.compile(pattern, _I), offset, slot)
    for pattern, offset, slot in (
        (r"\b(?:last\s+night|yesterday\s+(?:evening|night))\b", -1, Slot.DINNER),
        (r"\byesterday\s+morning\b", -1, Slot.BREAKFAST),
        (r"\byesterday(?:'s)?\b", -1, None),
        (r"\btomorrow\s+(?:night|evening)\b", 1, Slot.DINNER),
        (r"\btomorrow\s+morning\b", 1, Slot.BREAKFAST),
        (r"\btomorrow(?:'s)?\b", 1, None),
        (r"\b(?:tonight(?:'s)?|this\s+evening)\b", 0, Slot.DINNER),
        (r"\bthis\s+morning\b", 0, Slot.BREAKFAST),
        (r"\b(?:today(?:'s)?|this\s+afternoon|earlier(?:\s+today)?|just\s+now)\b", 0, None),
    )
)
_WEEKDAY_RE = re.compile(
    r"\b(?:(?P<mod>on|this|next|last|coming|for)\s+)?"
    rf"(?P<day>{'|'.join(_WEEKDAYS)})(?:'s)?"
    r"(?:\s+(?P<part>night|evening|morning|lunchtime))?\b",
    _I,
)
_DAY_OF_MONTH_RE = re.compile(
    r"\b(?:on\s+|for\s+)?(?:the\s+(?P<a>\d{1,2})(?:st|nd|rd|th)?|(?P<b>\d{1,2})(?:st|nd|rd|th))\b",
    _I,
)

_NEG = r"(?:\bnot|n't|\bnever|\bcannot)"
# Negations that are themselves a skip: "not having lunch", "won't be home for dinner".
_SKIP_NEG = re.compile(
    rf"{_NEG}\s+(?:be\s+|going\s+to\s+(?:be\s+)?|gonna\s+(?:be\s+)?)?"
    r"(?:having|have|eating|eat|need|needing|want|wanting|home\s+for|in\s+for|around\s+for|"
    r"there\s+for|back\s+for)\s+(?:any\s+|my\s+|the\s+|a\s+|for\s+)?"
    rf"(?:{_SLOTS}|tea)\b"
    r"|\bnot\s+(?:very\s+|really\s+|that\s+|too\s+)?hungry\b"
    rf"|{_NEG}\s+(?:be\s+)?eating\b(?!\s+(?:out|a|an|the|any|some)\b)",
    _I,
)
# Any other negated request means "leave it": "I'm not skipping lunch", "don't change Friday".
_NEG_OTHER = re.compile(
    rf"{_NEG}\s+(?:\w+\s+){{0,2}}?(?:skip\w*|chang\w*|swap\w*|replac\w*|switch\w*|want\w*|"
    r"fancy\w*|eat\w*|ate|had|have|having|crav\w*|need\w*|in\s+the\s+mood|feel\w*\s+like|"
    r"keen)\b|\bno\s+(?:need|changes?|swaps?)\b",
    _I,
)
_SWAP = re.compile(
    r"\b(?:swap\w*|switch\w*|chang(?:e|ing)|replac(?:e|ing)|substitut\w*)\b"
    r"|\bsomething\s+(?:else|different)\b"
    rf"|\b(?:different|another)\s+(?:meal|dish|recipe|{_SLOTS})\b",
    _I,
)
_ATE = re.compile(
    r"\b(?:had|ate|eaten|grabbed|snacked\s+on|devoured|scoffed|polished\s+off|having)\b"
    r"(?!\s+(?:to|out|home|back)\b)",
    _I,
)
_ELSEWHERE = re.compile(
    r"\b(?:eat(?:ing)?|ate|eaten|dine|dining|dined|going|go|went|be|been)\s+out\b"
    rf"|\bout\s+for\s+(?:{_SLOTS}|tea)\b|\b(?:{_SLOTS})\s+out\b"
    r"|\bout\s+(?:tonight|tomorrow|today)\b"
    r"|\b(?:at|to|round|over\s+at)\s+(?:a\s+|my\s+|our\s+|the\s+|his\s+|her\s+)?"
    r"(?:friend|friends|mate|mates|mum|mom|mam|mother|dad|father|parents|nan|nana|gran|granny|"
    r"grandma|grandad|grandparents|sister|brother|aunt|auntie|uncle|cousin|in-laws|boyfriend|"
    r"girlfriend|partner|neighbour|neighbor|neighbours|neighbors|boss|colleague)(?:'s|s'|s)?\b"
    r"|\brestaurant\b|\btake-?aways?\b|\btake-?outs?\b|\bpub\b|\bcanteen\b"
    r"|\bwork\s+(?:do|party|lunch|dinner)\b|\bdinner\s+party\b|\bbarbecue\b|\bbbq\b"
    r"|\bwedding\b",
    _I,
)
_HOST = re.compile(r"\bat\s+[A-Z][a-z]+(?:'s|s')(?=\s|$)")  # "dinner at Sarah's"
# A meal disliked by name only ("I don't like tonight's dinner", the time and meal masked): swap.
_DISLIKE = re.compile(
    rf"(?:{_NEG}\s+(?:really\s+)?(?:like|fancy|want)|\b(?:hate|dislike))\b"
    r"[\s,.!]*(?:the|my|this|that)?[\s,.!]*(?:one|meal)?[\s,.!]*$",
    _I,
)
# "skip all my meals on Saturday", "eating out all day": every main meal of the day.
_ALL_DAY = re.compile(
    r"\b(?:all\s+(?:my\s+|the\s+|of\s+my\s+)?meals|(?:all|the\s+whole|whole)\s+day|every\s+meal)\b",
    _I,
)
# "make Friday dinner pasta", "make tomorrow's lunch something light": a wish, firmly put.
_MAKE = re.compile(r"^\s*(?:let's\s+)?make\b", _I)
# A wish without a verb: "something vegetarian on Friday", "anything with rice tomorrow".
_BARE_WISH = re.compile(r"^\s*(?:something|anything)\b", _I)
_SKIP = re.compile(
    r"\bskip\w*|\bfasting\b|\bfast\s+(?:today|tomorrow|tonight|on)\b"
    rf"|\bmiss(?:ing|ed)?\s+(?:my\s+|a\s+)?(?:{_SLOTS}|meal|tea)\b|\bno\s+(?:{_SLOTS}|tea)\b",
    _I,
)
_CRAVE = re.compile(
    r"\bcrav(?:e|es|ed|ing)\b|\bfancy(?:ing)?\b|\bwant(?:s|ing)?\b|\bwanna\b"
    r"|\bwould\s+(?:like|love)\b|'d\s+(?:like|love)\b|\bin\s+the\s+mood\s+for\b"
    r"|\bfeel(?:ing)?\s+like\b|\bmust\s+have\b|\bneeds?\b|\bdying\s+for\b"
    r"|\bdesperate\s+for\b|\bcould\s+(?:really\s+)?(?:go\s+for|do\s+with)\b"
    r"|\b(?:can|could|may)\s+(?:i|we)\s+(?:have|get)\b|\blet's\s+have\b"
    r"|\bhave\s+to\s+have\b|\bhankering\s+for\b",
    _I,
)
_HARD = re.compile(
    r"\breally\s+(?:want|need|fancy|crave|craving)\b|\bmust\s+have\b|\bneeds?\b"
    r"|\bdying\s+for\b|\bdesperate\s+for\b|\binsist\w*|\bdefinitely\s+want\b"
    r"|\bhave\s+to\s+have\b",
    _I,
)
_PAST = re.compile(
    r"\b(?:had|ate|eaten|grabbed|snacked|devoured|scoffed|polished|skipped|missed|did|didn't|"
    r"was|were|went|dined|ordered)\b",
    _I,
)
_QUESTION = re.compile(
    r"^(?:should|shall|what|what's|whats|why|how|which|where|who|when|"
    r"is\s+(?:it|there|that|this)|are\s+(?:there|they|you|we)|do\s+(?:i|you|we)|does|"
    r"did\s+(?:i|you)|am\s+i|will\s+(?:i|it|the)|would\s+(?:it|that))\b",
    _I,
)
_REQUEST = re.compile(
    r"^(?:(?:please|pls|can\s+you|could\s+you|would\s+you|will\s+you|can\s+we|could\s+we)"
    r"\b[\s,]*)+",
    _I,
)
_ASK_FOR = re.compile(r"^(?:can|could|may)\s+(?:i|we)\s+(?:have|get)\b", _I)
_FILLER = re.compile(
    r"^(?:(?:and|then|but|so|also|oh|ok|okay|well|hey|hi|actually|um|right|yeah|plus)\b[\s,]*)+",
    _I,
)
# Starts a clause of its own when splitting ("had pizza, and can Friday be veggie?").
_ASKS = re.compile(
    r"^(?:can|could|would|will|is|are|do|does|did|should|shall|may|what|what's|why|how|which|"
    r"where|who|when)\b",
    _I,
)
_NOISE = re.compile(
    r"^(?:hi|hello|hey|hiya|thanks|thank\s+you|cheers|ok|okay|please|pls|yes|cool|great|"
    r"good\s+(?:morning|evening|afternoon)|change\s+of\s+plans?)"
    r"(?:\s+(?:there|again|so\s+much|very\s+much|all))?$",
    _I,
)
_CHANGE_OF_PLAN = re.compile(r"\bchange\s+of\s+plans?\b", _I)
_ANY_CUE = (_SKIP_NEG, _NEG_OTHER, _SWAP, _ATE, _ELSEWHERE, _HOST, _SKIP, _CRAVE, _MAKE)

_ARTICLE = re.compile(r"^(?:a|an|some|the|my)\s+", _I)
_TRAILING = re.compile(
    r"(?:\s+(?:for|on|at|in|to|with|please|too|today|me|then|and|as\s+well|again|instead))+$", _I
)
_QUANTITY = re.compile(
    r"^(?:(?P<num>\d+(?:[.,]\d+)?|an?|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"half(?:\s+an?)?|a\s+couple\s+of|couple\s+of|a\s+few|some)\s*)?"
    r"(?:(?P<unit>kg|g|grams?|ml|l|litres?|liters?|oz|slices?|pieces?|bowls?|cups?|mugs?|"
    r"glasses?|pints?|cans?|bottles?|portions?|servings?|plates?|bags?|bars?|scoops?|packets?|"
    r"packs?|squares?|handfuls?|spoonfuls?|tbsp|tsp|tablespoons?|teaspoons?|rashers?|sticks?|"
    r"tubs?|boxes?|bites?)\b\s*(?:of\s+)?)?"
    r"(?:(?P<size>small|medium|large|regular)\s+)?(?P<name>.+)$",
    _I,
)
_NUMBERS = {
    "a": "1",
    "an": "1",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "half": "0.5",
    "half a": "0.5",
    "half an": "0.5",
    "a couple of": "2",
    "couple of": "2",
    "a few": "a few",
}


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


_SIZES = _words("big large small huge massive light late early proper nice good decent")
_QUALITIES = _words(
    "spicy hot mild light healthy healthier quick easy simple hearty comforting comfort sweet "
    "savoury savory fresh cheap vegetarian veggie vegan low-carb high-protein protein filling "
    "warm warming cold creamy cheesy crispy italian indian chinese mexican thai japanese asian "
    "mediterranean greek french spanish korean vietnamese british american different new meaty "
    "meat-free plant-based gluten-free dairy-free"
)


# --- clauses ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Clause:
    text: str
    question: bool  # the sentence it ends ended with "?"

    @property
    def verbatim(self) -> str:
        return self.text + ("?" if self.question else "")


_SENTENCE_RE = re.compile(r"(?:[^.!?;\n]|\.(?=\d))+[.!?;]*")
_SEPARATOR_RE = re.compile(
    r"\s*,\s*(?:(?:and|then|but|so|also)\s+)?|\s+(?:and|then|but|so|also|plus|&)\s+(?:then\s+)?",
    _I,
)


def _clauses(text: str) -> list[_Clause]:
    """Sentences, then clauses at commas and conjunctions - but only where the next part says
    something on its own ("had pizza and chips" stays one clause, "skip lunch and dinner" too)."""
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    out: list[_Clause] = []
    for sentence in _SENTENCE_RE.finditer(text):
        raw = sentence.group(0)
        body = raw.strip().rstrip(".!?;").strip()
        if not body:
            continue
        texts: list[str] = []
        seps: list[str] = []
        pos = 0
        for sep in _SEPARATOR_RE.finditer(body):
            texts.append(body[pos : sep.start()])
            seps.append(sep.group(0))
            pos = sep.end()
        texts.append(body[pos:])
        merged = [("", texts[0])]  # (separator before, clause)
        for sep, piece in zip(seps, texts[1:], strict=True):
            if _has_cue(piece):
                merged.append((sep, piece))
            else:
                merged[-1] = (merged[-1][0], merged[-1][1] + sep + piece)
        if len(merged) > 1 and not _has_cue(merged[0][1]):
            # A leading part without a cue ("tomorrow, skip lunch") belongs to the next clause.
            merged[:2] = [("", merged[0][1] + merged[1][0] + merged[1][1])]
        question = raw.rstrip().endswith("?")
        for j, (_, clause) in enumerate(merged):
            if clause.strip():
                out.append(_Clause(clause.strip(), question and j == len(merged) - 1))
    return out


def _has_cue(text: str) -> bool:
    text = _FILLER.sub("", text.strip())
    return bool(_ASKS.match(text)) or any(p.search(text) for p in _ANY_CUE)


# --- one clause -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Time:
    start: int
    end: int
    day: date
    slot: Slot | None


def _parse_clause(text: str, question: bool, today: date) -> tuple[list[RuleChange], bool] | None:
    """The clause's changes and whether it named a day or meal; None if not understood."""
    s = _FILLER.sub("", text)
    request = _REQUEST.match(s)
    s = _REQUEST.sub("", s)
    if (question and not request and not _ASK_FOR.match(s)) or _QUESTION.match(s):
        return None
    s = _CHANGE_OF_PLAN.sub(lambda m: " " * len(m.group(0)), s)
    past = bool(_PAST.search(s))
    times = _find_times(s, today, past=past)
    slot_spans = [(m.start(), m.end(), _slot_of(m)) for m in _SLOT_RE.finditer(s)]
    masked = _mask(s, [(t.start, t.end) for t in times] + [(a, b) for a, b, _ in slot_spans])
    explicit = bool(times or slot_spans)
    days = list(dict.fromkeys(t.day for t in times)) or [today]
    slots: list[Slot | None] = list(dict.fromkeys(sl for _, _, sl in slot_spans))
    if not slots:
        slots = [next((t.slot for t in times if t.slot is not None), None)]
    # Skips over a whole day: each main meal of each day named.
    whole_day = not slot_spans and bool(_ALL_DAY.search(s))
    skip_whens = (
        [When(date=d, slot=sl) for d in days for sl in (Slot.BREAKFAST, Slot.LUNCH, Slot.DINNER)]
        if whole_day
        else _whens(days, slots)
    )

    if _SKIP_NEG.search(s):
        return [_skip(w, False) for w in skip_whens], explicit or whole_day
    if explicit and _DISLIKE.search(masked):
        return [Swap(intent="swap", when=w) for w in _whens(days, slots)], explicit
    if _NEG_OTHER.search(s):
        return None
    if m := _SWAP.search(s):
        if not explicit:
            return None
        dish, tags = _wish(_target(masked[m.end() :]))
        return [
            Swap(intent="swap", when=w, dish=dish, tags=tags) for w in _whens(days, slots)
        ], explicit
    if (m := _ATE.search(s)) and (food := _food(masked[m.end() :])):
        when = When(date=days[0], slot=slots[0])
        return [_ate_off_plan(when, food)], explicit
    if _ELSEWHERE.search(s) or _HOST.search(s):
        return [_skip(w, True) for w in skip_whens], explicit or whole_day
    if _SKIP.search(s):
        return [_skip(w, False) for w in skip_whens], explicit or whole_day
    if (m := _MAKE.search(masked)) and explicit:
        dish, tags = _wish(_object(masked[m.end() :]))
        if dish or tags:
            when = When(date=days[0], slot=slots[0])
            craving = Craving(intent="craving", when=when, dish=dish, tags=tags, strength="hard")
            return [craving], explicit
    if _BARE_WISH.match(masked) and not _CRAVE.search(s):
        dish, tags = _wish(_object(masked))
        if tags:
            when = When(date=days[0], slot=slots[0])
            craving = Craving(intent="craving", when=when, dish=dish, tags=tags, strength="soft")
            return [craving], explicit
    if m := _CRAVE.search(s):
        dish, tags = _wish(_object(masked[m.end() :]))
        if dish or tags:
            strength = "hard" if _HARD.search(s) else "soft"
            when = When(date=days[0], slot=slots[0])
            craving = Craving(intent="craving", when=when, dish=dish, tags=tags, strength=strength)
            return [craving], explicit
    return None


def _skip(when: When, elsewhere: bool) -> Skip:
    return Skip(intent="skip", when=when, eating_elsewhere=elsewhere)


def _whens(days: list[date], slots: list[Slot | None]) -> list[When]:
    """Every named day with every named meal ("skip lunch and dinner tomorrow"); with several
    of each, paired in order ("skip dinner tonight and lunch tomorrow")."""
    if len(days) > 1 and len(slots) > 1:
        return [When(date=d, slot=s) for d, s in zip(days, slots, strict=False)]
    return [When(date=d, slot=s) for d in days for s in slots]


def _slot_of(m: re.Match[str]) -> Slot:
    word = (m.group("slot") or m.group("tea") or m.group("tea2")).lower()
    return _SLOT_WORDS[word]


def _mask(s: str, spans: list[tuple[int, int]]) -> str:
    chars = list(s)
    for a, b in spans:
        chars[a:b] = " " * (b - a)
    return "".join(chars)


# --- dates ------------------------------------------------------------------------------------


def _find_times(s: str, today: date, *, past: bool) -> list[_Time]:
    found: list[_Time] = []

    def free(a: int, b: int) -> bool:
        return all(b <= t.start or a >= t.end for t in found)

    for pattern, offset, slot in _RELATIVE:
        for m in pattern.finditer(s):
            if free(m.start(), m.end()):
                found.append(_Time(m.start(), m.end(), today + timedelta(days=offset), slot))
    for m in _WEEKDAY_RE.finditer(s):
        if free(m.start(), m.end()):
            day = _weekday(today, _WEEKDAYS[m.group("day").lower()], m.group("mod"), past=past)
            part = m.group("part")
            found.append(_Time(m.start(), m.end(), day, _PARTS[part.lower()] if part else None))
    for m in _DAY_OF_MONTH_RE.finditer(s):
        day = _day_of_month(today, int(m.group("a") or m.group("b")), past=past)
        if day is not None and free(m.start(), m.end()):
            found.append(_Time(m.start(), m.end(), day, None))
    return sorted(found, key=lambda t: t.start)


def _weekday(today: date, target: int, mod: str | None, *, past: bool) -> date:
    """Most recent such day (today included) for the past tense, else the next one; "next" and
    "last" exclude today."""
    ahead = (target - today.weekday()) % 7
    back = (today.weekday() - target) % 7
    mod = (mod or "").lower()
    if mod == "next":
        return today + timedelta(days=ahead or 7)
    if mod == "last":
        return today - timedelta(days=back or 7)
    return today - timedelta(days=back) if past else today + timedelta(days=ahead)


def _day_of_month(today: date, n: int, *, past: bool) -> date | None:
    year, month = today.year, today.month
    if past and n > today.day:
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    elif not past and n < today.day:
        year, month = (year, month + 1) if month < 12 else (year + 1, 1)
    try:
        return date(year, month, n)
    except ValueError:
        return None


# --- what was eaten or wanted -----------------------------------------------------------------


def _squash(text: str) -> str:
    return " ".join(text.split())


def _object(rest: str) -> str:
    p = _squash(rest)
    p = re.sub(r"^(?:(?:to\s+(?:have|eat|try|get|cook)|for|on|having|eating)\s+)+", "", p, flags=_I)
    return _TRAILING.sub("", p).strip()


def _target(rest: str) -> str:
    """What a swap should become: the words after for / to / with ("swap it for a curry")."""
    m = re.search(r"\b(?:for|to|with|into)\s+(\S.*)$", _squash(rest), _I)
    return _object(m.group(1)) if m else ""


def _food(rest: str) -> str | None:
    p = _squash(rest)
    p = re.sub(r"(?:^|\s+)(?:at|from)\s+.*$", "", p, flags=_I)  # where, not what
    p = re.sub(r"^(?:(?:just|already|also|out|then|for|on)\s+)+", "", p, flags=_I)
    if re.match(r"^(?:with\b|out$)", p, _I):  # "had lunch with friends"
        return None
    p = _TRAILING.sub("", p).strip()
    if all(w in _SIZES for w in _ARTICLE.sub("", p).lower().split()):  # "had a big lunch"
        return None
    return p


def _ate_off_plan(when: When, food: str) -> AteOffPlan:
    parts = re.split(r"\s*,\s*|\s+and\s+|\s+with\s+|\s+plus\s+|\s*&\s*", food, flags=_I)
    items = [item for part in parts if (item := _item(part)) is not None]
    return AteOffPlan(
        intent="ate_off_plan",
        when=when,
        description=_ARTICLE.sub("", food)[:MAX_TEXT],
        items=items[:10],
    )


def _item(text: str) -> OffPlanItem | None:
    m = _QUANTITY.match(text.strip())
    if m is None:
        return None
    name = m.group("name").strip()[:120]
    if not name:
        return None
    num_raw = (m.group("num") or "").lower()
    num = _NUMBERS.get(re.sub(r"\s+", " ", num_raw), num_raw.replace(",", ".")) or None
    unit, size = m.group("unit"), m.group("size")
    if unit:
        quantity = f"{num or '1'} {unit.lower()}"
    elif size:
        quantity = f"{num or '1'} {size.lower()}"
    elif num and num_raw not in ("a", "an", "some"):
        quantity = num
    else:
        quantity = None
    return OffPlanItem(name=name, quantity=quantity[:40] if quantity else None)


def _wish(phrase: str) -> tuple[str | None, list[str]]:
    """A named dish, or qualities ("something spicy", "spicy food", "something with rice")."""
    p = _ARTICLE.sub("", phrase.strip())
    if not p:
        return None, []
    m = re.match(r"^(?:something|anything)\b\s*(.*)$", p, _I)
    if m:
        return None, _tags(m.group(1))
    bare = re.sub(r"\s+(?:food|meal|dish|stuff)$", "", p, flags=_I)
    words = [w for w in re.split(r"[\s,/]+|\band\b|\bor\b", bare.lower()) if w]
    if words and all(w in _QUALITIES for w in words):
        return None, _tags(bare)
    return p[:120], []


def _tags(text: str) -> list[str]:
    out: list[str] = []
    for part in re.split(r"\s*(?:,|\band\b|\bor\b|/)\s*", text, flags=_I):
        t = part.strip().lower()
        t = re.sub(
            r"^(?:(?:with|that's|thats|that\s+is|a\s+bit|bit|really|very|quite|nice\s+and|nice|"
            r"more|kind\s+of|sort\s+of|like|a|an|some)\s+)+",
            "",
            t,
        )
        t = re.sub(r"\s+(?:food|meal|dish|stuff)$", "", t).strip()[:40]
        if t and t not in out:
            out.append(t)
    return out[:8]


# --- suggestions ------------------------------------------------------------------------------


def _suggest(change: RuleChange, today: date) -> list[str]:
    """For a skip or swap without a meal: the same request for lunch and for dinner."""
    day = change.when.date
    before = day < today
    if isinstance(change, Skip):
        if change.eating_elsewhere:
            verb, verb_for = (
                ("ate out", "ate out for") if before else ("eating out", "eating out for")
            )
        else:
            verb = verb_for = "skipped" if before else "skip"
    elif isinstance(change, Swap):
        verb = verb_for = "swap"
    else:
        return []
    out: list[str] = []
    for slot in ("lunch", "dinner"):
        delta = (day - today).days
        if delta in (-1, 0, 1):
            word = {-1: "yesterday", 0: "today", 1: "tomorrow"}[delta]
            out.append(f"{verb_for} {slot} {word}")
        elif 1 < delta <= 6:
            out.append(f"{verb} {day:%A} {slot}")
        else:
            out.append(f"{verb_for} {slot} on the {_ordinal(day.day)}")
    return out


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"

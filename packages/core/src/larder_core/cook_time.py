"""How long a recipe takes, estimated from its method (no source gives times we can trust).

A method that states its total ("Ready in: 45min", "Total time: 1 hour") is taken at its word.
Otherwise the method is split into steps (one per line) and each step into sentences. A
sentence that names a time ("simmer for 20-25 minutes", "a few minutes", "half an hour")
takes the longest one it names (the longer end of a range, so nothing comes out underdone);
"overnight" counts as 8 hours, unless the sentence says not to. Without a time, a sentence
takes what its cooking implies ("bake" half an hour, "until tender" ten minutes: IMPLIED) or
its length as hands-on work (about 12 words a minute), whichever is longer. A heading ("Make
the sauce:") or another way of doing a step ("Alternatively, ...") takes nothing, and a tip
for another situation ("If you don't have ...", to the end of its step) only its reading; a
step at least a minute. The total is rounded to 5 minutes, at least 5.

It's a guide, shown as "about": methods rarely say how long the chopping takes.
The web's meal-prep timeline (apps/web/src/lib/prep.ts) reads timers the same way.
"""

import re

# Amounts written as words: "a minute", "a few minutes", "two hours".
_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30,
    "forty": 40, "forty-five": 45, "a couple of": 2, "a couple": 2, "a few": 3, "several": 4,
}  # fmt: skip
_AMOUNT = r"\d+(?:[.,]\d+)?½?|½|" + "|".join(
    re.escape(w) for w in sorted(_WORDS, key=len, reverse=True)
)
# "20 minutes", "1-2 hours", "30 to 40 mins", "1½ hours", "45 secs", "a few minutes"
_TIME = re.compile(
    rf"(?<![\w-])({_AMOUNT})(?:\s*(?:-|\u2013|to)\s*(\d+(?:[.,]\d+)?))?\s*"
    r"(seconds?|secs?|minutes?|mins?|hours?|hrs?)\b",
    re.IGNORECASE,
)
_UNIT_SECONDS = {"second": 1, "sec": 1, "minute": 60, "min": 60, "hour": 3600, "hr": 3600}
_HALF_HOUR = re.compile(r"\bhalf an hour\b", re.IGNORECASE)
_OVERNIGHT = re.compile(r"\bovernight\b", re.IGNORECASE)
# "Chill for at least an hour, or overnight": overnight is allowed, not needed.
_OPTIONAL_OVERNIGHT = re.compile(r"\bor overnight\b", re.IGNORECASE)
# "Alternatively, soak them overnight": another way of doing a step, not another step.
_ALTERNATIVE = re.compile(r"^\s*(?:alternatively|or)\b", re.IGNORECASE)
_NEGATED = re.compile(r"\b(?:do not|don't|never|not)\b", re.IGNORECASE)
# "If you don't have leftover rice, cook some. Let it dry for 2 hours.": a tip for another
# situation, to the end of its step; its sentences count as reading, not as waiting.
_CONDITIONAL = re.compile(
    r"^\s*(?:if you (?:don't|don\u2019t|do not|can't|can\u2019t|cannot) have|otherwise)\b",
    re.IGNORECASE,
)
# A method that says how long it all takes: "Ready in: 45min", "Total time 1 hour".
_STATED_TOTAL = re.compile(r"\b(?:ready in|total time)\s*:?\s*", re.IGNORECASE)
# What cooking implies when a sentence names no time: (pattern, seconds); the longest wins.
IMPLIED: tuple[tuple[re.Pattern[str], int], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), minutes * 60)
    for pattern, minutes in (
        (r"\b(?:slow[- ]cook|braise|stew)\b", 90),
        (r"\b(?:roast|bake)\b", 30),
        (r"\bsimmer", 15),
        (r"\buntil\b.*\b(?:tender|soft|softened|absorbed|thickened|reduced)\b", 10),
        (r"(?<!to the )(?<!to a )\bboil\b", 10),  # boiling something, not bringing to the boil
        (r"\bgrill\b", 10),
        (r"\buntil\b.*\b(?:golden|browned|crisp|crispy|cooked|set|wilted)\b", 6),
        (r"\bfry\b", 5),
        (r"\bto (?:the|a) boil\b", 5),
        (r"\b(?:chop|slice|dice|shred|grate|peel|mince|julienne)", 3),
    )
)
# "STEP 1", "Step 2:", "3. " or "4) " at the start of a line (lib/cooking.ts NUMBERING).
_NUMBERING = re.compile(r"^(?:step\s*\d+\s*[.):-]?\s*|\d{1,2}[.)]\s+)", re.IGNORECASE)
# A sentence ends at . ! or ? followed by a space and a capital (so "1.5 kg" stays whole).
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")

WORDS_PER_MINUTE = 12
MIN_STEP_SECONDS = 60
MAX_TIMER_SECONDS = 12 * 3600
OVERNIGHT_SECONDS = 8 * 3600
MAX_MINUTES = 3 * 24 * 60  # a long method is "days", not a precise number


def steps(instructions: str) -> list[str]:
    """The method as steps: one per line, without "STEP 1" headings and "1." numbers."""
    out: list[str] = []
    for line in re.split(r"\r?\n+", instructions):
        step = _NUMBERING.sub("", line.strip()).strip()
        if step:
            out.append(step)
    return out


def timer_seconds(text: str) -> list[int]:
    """The times a piece of method names, in seconds (1 s to 12 h each)."""
    out: list[int] = []
    if _HALF_HOUR.search(text):
        out.append(1800)
        text = _HALF_HOUR.sub(" ", text)  # not also "an hour"
    for m in _TIME.finditer(text):
        unit = m.group(3).lower().rstrip("s")
        raw = (m.group(2) or m.group(1)).lower()
        seconds = round(_amount(raw) * _UNIT_SECONDS[unit])
        if 1 <= seconds <= MAX_TIMER_SECONDS:
            out.append(seconds)
    return out


def _amount(raw: str) -> float:
    if raw in _WORDS:
        return _WORDS[raw]
    half = raw.endswith("½")
    whole = raw.removesuffix("½")
    return (float(whole.replace(",", ".")) if whole else 0) + (0.5 if half else 0)


def _heading(text: str) -> bool:
    return text.rstrip().endswith(":")


def _overnight(sentence: str) -> bool:
    """The sentence needs overnight: it says so, not as an option, and not as a warning."""
    return (
        bool(_OVERNIGHT.search(sentence))
        and not _NEGATED.search(sentence)
        and not _OPTIONAL_OVERNIGHT.search(sentence)
    )


def _sentence_seconds(sentence: str) -> int:
    if _heading(sentence) or _ALTERNATIVE.search(sentence):
        return 0  # a heading is timed by the steps under it
    times = timer_seconds(sentence)
    if _overnight(sentence):
        times.append(OVERNIGHT_SECONDS)
    if times:
        return max(times)
    implied = max((s for pattern, s in IMPLIED if pattern.search(sentence)), default=0)
    return max(implied, round(len(sentence.split()) / WORDS_PER_MINUTE * 60))


def cook_minutes(instructions: str) -> int | None:
    """About how many minutes the recipe takes start to finish (5 to MAX_MINUTES), or None
    without a method."""
    method = steps(instructions)
    if not method:
        return None
    if stated := _stated_total(instructions):
        total = stated
    else:
        total = sum(_step_seconds(step) for step in method)
    return min(MAX_MINUTES, max(5, round(total / 300) * 5))


def _stated_total(instructions: str) -> int | None:
    """The total the method states ("Ready in: 45min"), in seconds."""
    for m in _STATED_TOTAL.finditer(instructions):
        # "1 hour 10 mins" adds up; the line ends the total.
        line = instructions[m.end() :].splitlines()[0][:24]
        if times := timer_seconds(line):
            return sum(times)
    return None


def _step_seconds(step: str) -> int:
    seconds = 0
    conditional = False
    for sentence in _SENTENCE.split(step):
        conditional = conditional or bool(_CONDITIONAL.search(sentence))
        if conditional:
            seconds += round(len(sentence.split()) / WORDS_PER_MINUTE * 60)
        else:
            seconds += _sentence_seconds(sentence)
    if not seconds and _heading(step):
        return 0
    return max(MIN_STEP_SECONDS, seconds)


# Waits that start well before cooking: marinating, soaking, chilling, proving and the like
# ("rest" and "leave" are left out: "the rest of the stock", "leave to simmer").
_AHEAD = re.compile(
    r"\b(?:marinat|soak|chill|refrigerat|prove|proof|strain|steep|brine|cure|freez)",
    re.IGNORECASE,
)
AHEAD_SECONDS = 2 * 3600
MAX_AHEAD_CHARS = 200


def ahead_steps(instructions: str) -> list[str]:
    """The sentences of the method that need starting well before the meal: a wait of at least
    two hours, or overnight, for marinating, soaking, chilling, proving and the like. Tips
    for another situation, alternatives and headings don't count."""
    out: list[str] = []
    for step in steps(instructions):
        conditional = False
        for sentence in _SENTENCE.split(step):
            conditional = conditional or bool(_CONDITIONAL.search(sentence))
            if conditional or _heading(sentence) or _ALTERNATIVE.search(sentence):
                continue
            if not _AHEAD.search(sentence):
                continue
            if _overnight(sentence) or max(timer_seconds(sentence), default=0) >= AHEAD_SECONDS:
                text = sentence.strip()
                out.append(
                    text if len(text) <= MAX_AHEAD_CHARS else text[: MAX_AHEAD_CHARS - 1] + "…"
                )
    return out

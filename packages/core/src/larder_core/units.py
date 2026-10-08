"""Units and recipe measure parsing.

All quantities are stored as grams. Volumes convert to grams through a food's density and counts
("2 cloves", "1 large") through its portion weights; both live with the food data, so this
module only parses measures and converts within a dimension.

Conventions (documented in docs/DESIGN.md §6): metric spoons and a 240 ml cup (US nutrition
labelling); imperial pint, since the seed recipes are mostly British.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction


class Dimension(StrEnum):
    MASS = "mass"
    VOLUME = "volume"
    COUNT = "count"


# Factor to the dimension's base unit: grams for mass, millilitres for volume.
MASS_UNITS: dict[str, float] = {
    "mg": 0.001,
    "g": 1.0,
    "kg": 1000.0,
    "oz": 28.349523125,
    "lb": 453.59237,
}
VOLUME_UNITS: dict[str, float] = {
    "ml": 1.0,
    "cl": 10.0,
    "dl": 100.0,
    "l": 1000.0,
    "tsp": 5.0,
    "tbsp": 15.0,
    "cup": 240.0,
    "fl_oz": 29.5735295625,
    "pint": 568.26125,
    "quart": 946.352946,
}
# Units whose weight depends on the food (resolved via USDA portions / curated defaults).
COUNT_UNITS: frozenset[str] = frozenset(
    {
        "bag",
        "ball",
        "bottle",
        "breast",
        "bulb",
        "bunch",
        "can",
        "carton",
        "clove",
        "cube",
        "fillet",
        "head",
        "jar",
        "juice",
        "leaf",
        "leg",
        "packet",
        "piece",
        "pod",
        "pot",
        "rasher",
        "sheet",
        "slice",
        "sprig",
        "stalk",
        "stick",
        "thigh",
        "tub",
        "zest",
    }
)
SIZES: frozenset[str] = frozenset({"small", "medium", "large"})

_ALIASES: dict[str, str] = {
    # mass
    "milligram": "mg",
    "gram": "g",
    "gr": "g",
    "gm": "g",
    "kilo": "kg",
    "kilogram": "kg",
    "ounce": "oz",
    "pound": "lb",
    "lbs": "lb",
    # volume
    "millilitre": "ml",
    "milliliter": "ml",
    "mls": "ml",
    "litre": "l",
    "liter": "l",
    "ltr": "l",
    "teaspoon": "tsp",
    "tspn": "tsp",
    "t": "tsp",
    "tablespoon": "tbsp",
    "tbs": "tbsp",
    "tbl": "tbsp",
    "tbls": "tbsp",
    "tblsp": "tbsp",
    "tblspn": "tbsp",
    "tbsps": "tbsp",
    "c": "cup",
    "pt": "pint",
    "qt": "quart",
    # count
    "tin": "can",
    "pack": "packet",
    "package": "packet",
    "pkg": "packet",
    "leave": "leaf",
    "leaves": "leaf",
    "loaf": "piece",
    "pc": "piece",
    "pcs": "piece",
    "strip": "slice",
    "stem": "stalk",
    "rib": "stalk",
    "sticks": "stick",
}
_SIZE_ALIASES: dict[str, str] = {"big": "large", "med": "medium", "jumbo": "large"}

# Vague measures as a fixed equivalent per unit of the phrase ("2 pinches" = 2/16 tsp).
_VAGUE: dict[str, tuple[float, str]] = {
    "pinch": (1 / 16, "tsp"),
    "dash": (1 / 8, "tsp"),
    "splash": (1, "tbsp"),
    "drizzle": (1, "tbsp"),
    "sprinkle": (1, "tsp"),
    "dusting": (1, "tsp"),
    "garnish": (1, "tsp"),
    "to taste": (1 / 4, "tsp"),
    "to serve": (1, "tsp"),
    "for frying": (1, "tbsp"),
    "knob": (15, "g"),
    "handful": (30, "g"),
    "drop": (0.01, "tsp"),
}
_VAGUE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^pinch(es)?\b"), "pinch"),
    (re.compile(r"^dash(es)?\b"), "dash"),
    (re.compile(r"^splash(es)?\b"), "splash"),
    (re.compile(r"^drizzle"), "drizzle"),
    (re.compile(r"^s[a-z]*nk(le|ling|ing)"), "sprinkle"),  # sprinkle, sprinkling, sprinking...
    (re.compile(r"^dust"), "dusting"),
    (re.compile(r"^(to )?garnish|^for garnish"), "garnish"),
    (re.compile(r"^(to|for) taste|^as (needed|required)|^season"), "to taste"),
    (re.compile(r"^(to|for) serv"), "to serve"),
    (re.compile(r"^(for )?(deep )?fry"), "for frying"),
    (re.compile(r"^(to|for) (glaze|glazing|brush|greas|drizzl)|^top(ping)?\b"), "garnish"),
    (re.compile(r"^knobs?\b"), "knob"),
    (re.compile(r"^handful"), "handful"),
    (re.compile(r"^drops?\b"), "drop"),
]

_UNICODE_FRACTIONS = {
    "½": "1/2",
    "⅓": "1/3",
    "⅔": "2/3",
    "¼": "1/4",
    "¾": "3/4",
    "⅕": "1/5",
    "⅛": "1/8",
    "⅜": "3/8",
    "⅝": "5/8",
    "⅞": "7/8",
}
_WORD_QUANTITIES = {"a": 1.0, "an": 1.0, "one": 1.0, "half": 0.5, "two": 2.0, "three": 3.0}

_NUMBER = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:[.,]\d+)?|\.\d+)"
_QUANTITY_RE = re.compile(rf"^(?P<a>{_NUMBER})(?:\s*(?:-|\u2013|to)\s*(?P<b>{_NUMBER}))?")
_CONTAINER_RE = re.compile(
    rf"^(?P<n>{_NUMBER})?\s*(?:x\s*|\(\s*)?(?P<q>{_NUMBER})\s*(?P<u>g|kg|ml|l)\b\s*\)?\s*"
    r"(?:tins?|cans?|packs?|packets?|jars?|bags?|tubs?|bottles?|cartons?|pots?|blocks?)\b"
)
_OF_RE = re.compile(
    r"^(?:(?:finely\s+)?grated\s+|the\s+)?(?P<u>juice|zest|rind)(?:\s+and\s+\w+)?\s+of\s+(?P<q>.+)$"
)
# Preparation words that may sit between a quantity and its unit ("5 chopped cloves").
_PREP_WORDS: frozenset[str] = frozenset(
    {
        "chopped",
        "crushed",
        "cubed",
        "diced",
        "finely",
        "freshly",
        "grated",
        "halved",
        "heaped",
        "level",
        "minced",
        "peeled",
        "roughly",
        "rounded",
        "sliced",
        "thinly",
        "whole",
    }
)


@dataclass(frozen=True, slots=True)
class Measure:
    """A parsed recipe measure: `quantity` of `unit` (None = a whole item, e.g. "2" eggs)."""

    quantity: float
    unit: str | None
    size: str | None = None
    vague: bool = False

    @property
    def dimension(self) -> Dimension:
        if self.unit in MASS_UNITS:
            return Dimension.MASS
        if self.unit in VOLUME_UNITS:
            return Dimension.VOLUME
        return Dimension.COUNT


def canonical_unit(word: str) -> str | None:
    """Map a spelling ("Tablespoons", "tbs", "lbs") to a canonical unit, or None."""
    w = word.strip().lower().rstrip(".")
    for candidate in (w, *_singulars(w)):
        if candidate in MASS_UNITS or candidate in VOLUME_UNITS or candidate in COUNT_UNITS:
            return candidate
        if candidate in _ALIASES:
            return _ALIASES[candidate]
    return None


def convert(quantity: float, from_unit: str, to_unit: str) -> float:
    """Convert within one dimension (mass↔mass or volume↔volume)."""
    for table in (MASS_UNITS, VOLUME_UNITS):
        if from_unit in table and to_unit in table:
            return quantity * table[from_unit] / table[to_unit]
    raise ValueError(f"cannot convert {from_unit} to {to_unit}: mass and volume need a density")


def parse_quantity(text: str) -> float | None:
    """Parse "2", "1.5", "1 1/2", "½", "2-3" (midpoint). None if no leading number."""
    match = _QUANTITY_RE.match(_normalise(text))
    if not match:
        return None
    a = _number(match["a"])
    b = _number(match["b"]) if match["b"] else None
    if a is None:
        return None
    return a if b is None else (a + b) / 2


def parse_measure(text: str) -> Measure:
    """Parse a free-text recipe measure ("1½ cups", "2 x 400g tins", "pinch", "Juice of 1")."""
    s = _normalise(text)

    if container := _CONTAINER_RE.match(s):
        count = _number(container["n"]) if container["n"] else 1.0
        inner = _number(container["q"])
        if count is not None and inner is not None:
            return Measure(count * inner, container["u"])

    if of := _OF_RE.match(s):
        q = parse_quantity(of["q"]) or _WORD_QUANTITIES.get(of["q"].split()[0], 1.0)
        return Measure(q, "zest" if of["u"] == "rind" else of["u"])

    quantity, rest = _take_quantity(s)
    rest = rest.lstrip(" -")

    for pattern, key in _VAGUE_PATTERNS:
        if pattern.match(rest):
            per, unit = _VAGUE[key]
            return Measure((quantity or 1.0) * per, unit, vague=True)

    tokens = [t for t in re.split(r"[\s,()]+", rest) if t]
    size: str | None = None
    unit: str | None = None
    for i, token in enumerate(tokens[:4]):
        if token == "/":
            break
        if token in _PREP_WORDS or token == "and":
            continue
        if token in SIZES or token in _SIZE_ALIASES:
            size = _SIZE_ALIASES.get(token, token)
            continue
        if token in ("fl", "fluid") and i + 1 < len(tokens) and tokens[i + 1].startswith("o"):
            unit = "fl_oz"
            break
        if (u := canonical_unit(token)) is not None:
            unit = u
        break

    if quantity is None and unit is None:
        return Measure(1.0, None, size=size, vague=True)
    return Measure(quantity if quantity is not None else 1.0, unit, size=size)


# --- helpers ----------------------------------------------------------------------------------


def _normalise(text: str) -> str:
    s = text.strip().lower().replace("\u00d7", "x")  # multiplication sign
    for char, frac in _UNICODE_FRACTIONS.items():
        s = re.sub(rf"(\d)\s*{char}", rf"\1 {frac}", s)
        s = s.replace(char, frac)
    s = re.sub(r"(?<=\d)(?=[a-z])", " ", s)  # 800g -> 800 g
    s = re.sub(r"(?<=[a-z])/", " / ", s)  # 200 g/7 oz -> 200 g / 7 oz
    return re.sub(r"\s+", " ", s)


def _take_quantity(s: str) -> tuple[float | None, str]:
    if match := _QUANTITY_RE.match(s):
        a = _number(match["a"])
        b = _number(match["b"]) if match["b"] else None
        if a is not None:
            return (a if b is None else (a + b) / 2), s[match.end() :]
    first, _, rest = s.partition(" ")
    if first in _WORD_QUANTITIES:
        return _WORD_QUANTITIES[first], rest
    return None, s


def _number(token: str) -> float | None:
    total = 0.0
    for part in token.replace(",", ".").split():
        if "/" in part:
            num, den = part.split("/", 1)
            if not num or not den or int(den) == 0:
                return None
            total += float(Fraction(int(num), int(den)))
        else:
            total += float(part)
    return total


def _singulars(word: str) -> list[str]:
    """Candidate singular forms, most likely first ("cloves" -> clove; "leaves" -> leaf)."""
    if not word.endswith("s") or word.endswith("ss"):
        return []
    out = [word[:-1]]
    if word.endswith("es"):
        out.append(word[:-2])
    if word.endswith("ves"):
        out.append(word[:-3] + "f")
    return out

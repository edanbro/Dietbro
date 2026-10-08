"""Rule-based ingredient name normalisation: the first, cheapest stage of matching.

"Freshly Chopped Parsley" -> "parsley"; "Red Onions" -> "red onion". Synonyms (coriander /
cilantro, aubergine / eggplant) are not handled here; the alias table maps them to foods.
"""

import re
import unicodedata

# Words that describe size, freshness or preparation, never which food it is.
_DESCRIPTORS = frozenset(
    {
        "beaten",
        "boneless",
        "chilled",
        "cubed",
        "deseeded",
        "drained",
        "halved",
        "melted",
        "quartered",
        "rinsed",
        "sifted",
        "softened",
        "whisked",
        "chopped",
        "crushed",
        "diced",
        "finely",
        "free-range",
        "fresh",
        "freshly",
        "large",
        "medium",
        "minced",
        "organic",
        "peeled",
        "roughly",
        "skinless",
        "sliced",
        "small",
        "thinly",
    }
)
# Already singular, or a plural that names the food ("molasses").
_KEEP_S = frozenset(
    {
        "asparagus",
        "brussels",
        "couscous",
        "citrus",
        "hummus",
        "molasses",
        "octopus",
        "swiss",
        "grits",
        "schnapps",
        "harissa",
    }
)
_IRREGULAR = {
    "leaves": "leaf",
    "loaves": "loaf",
    "halves": "half",
    "chillies": "chilli",
    "chilies": "chili",
    "cookies": "cookie",
    "brownies": "brownie",
    "pies": "pie",
    "veggies": "veggie",
}


# "can of chickpeas", "tin of tomatoes": the container is a quantity, not part of the name.
_CONTAINER_OF = re.compile(
    r"^(?:a\s+)?(?:cans?|tins?|jars?|packs?|packets?|bags?|bunch(?:es)?)\s+of\s+"
)


def normalise_name(raw: str) -> str:
    s = _strip_accents(raw).lower()
    s = re.sub(r"[()\[\]]", " ", s)
    s = re.sub(r"[^a-z0-9&'\- ]+", " ", s)
    s = _CONTAINER_OF.sub("", s.strip())
    words = [w for w in s.split() if w not in _DESCRIPTORS]
    if words:
        words[-1] = singular(words[-1])
    return " ".join(words)


def singular(word: str) -> str:
    if word in _KEEP_S or len(word) <= 3 or not word.endswith("s") or word.endswith("ss"):
        return word
    if word in _IRREGULAR:
        return _IRREGULAR[word]
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith(("oes", "ches", "shes", "xes", "sses")):
        return word[:-2]
    if word.endswith("us"):
        return word
    return word[:-1]


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))

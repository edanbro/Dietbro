"""Vocabulary bridges between how people write food names (British and Irish English, recipe
wording) and how USDA describes foods.

`SYNONYMS`/`rewrite` feed the ingredient resolver (byte-stable: changing them re-resolves
recipes). `SEARCH_SYNONYMS` only widens type-ahead food search.
"""

import re

__all__ = ["SEARCH_SYNONYMS", "SYNONYMS", "rewrite", "search_terms"]

# British / recipe vocabulary -> USDA vocabulary, applied before retrieval (longest first).
SYNONYMS: dict[str, str] = {
    "aubergine": "eggplant",
    "egg plant": "eggplant",
    "courgette": "zucchini",
    "king prawn": "shrimp",
    "prawn": "shrimp",
    "beetroot": "beets",
    "rocket": "arugula",
    "swede": "rutabaga",
    "sweetcorn": "sweet corn kernels",
    "stock cube": "bouillon dry",
    "stock": "soup stock",
    "mince": "ground",
    "minced": "ground",
    "double cream": "heavy whipping cream",
    "single cream": "light cream",
    "icing sugar": "powdered sugar",
    "caster sugar": "granulated sugar",
    "bicarbonate of soda": "baking soda",
    "plain flour": "wheat flour all-purpose",
    "cornflour": "cornstarch",
    "corn flour": "cornstarch",
    "chilli flake": "red pepper cayenne spice",
    "chilli powder": "chili powder spice",
    "chilli": "hot chili pepper",
    "filo": "phyllo dough",
    "treacle": "molasses",
    "passata": "tomato puree canned",
    "tinned": "canned",
    "yoghurt": "yogurt",
    "rapeseed": "canola",
    "groundnut": "peanut",
    "ground nut": "peanut",
    "soya": "soy",
    "spring onion": "scallions",
    "coriander leaf": "cilantro",
    "sultana": "raisins",
    "mangetout": "snow peas",
    "gammon": "ham",
    "black pudding": "blood sausage",
    "kipper": "herring smoked",
}
_SYNONYM_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in sorted(SYNONYMS, key=len, reverse=True)) + r")\b"
)


def rewrite(name: str) -> str:
    """Apply SYNONYMS to a normalised name ("baby aubergine" -> "baby eggplant")."""
    return _SYNONYM_RE.sub(lambda m: SYNONYMS[m.group(1)], name)


# Search only: grocery words whose USDA wording differs. CoFID foods carry many British names
# themselves; these help the USDA generics show up too.
SEARCH_SYNONYMS: dict[str, str] = {
    "crisps": "potato chips",
    "crisp": "potato chips",
    "rasher": "bacon",
    "rashers": "bacon",
    "porridge": "oats",
    "coriander": "cilantro",
    "pak choi": "bok choy",
    "biscuit": "cookies",
    "biscuits": "cookies",
    "semi skimmed": "reduced fat milk",
    "skimmed milk": "nonfat milk",
    "jam": "jams and preserves",
    "minced beef": "ground beef",
    "chips": "french fries",
    "sweets": "candies",
    "fizzy drink": "carbonated beverage",
}
_SEARCH_RE = re.compile(
    r"\b("
    + "|".join(re.escape(k) for k in sorted(SEARCH_SYNONYMS | SYNONYMS, key=len, reverse=True))
    + r")\b"
)


def search_terms(query: str) -> str:
    """A search query in USDA vocabulary ("crisps" -> "potato chips"); the query itself when no
    synonym applies."""
    table = SYNONYMS | SEARCH_SYNONYMS
    return " ".join(_SEARCH_RE.sub(lambda m: table[m.group(1)], query.casefold()).split())

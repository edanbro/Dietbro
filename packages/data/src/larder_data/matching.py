"""Ingredient name -> USDA food.

Pipeline (docs/DESIGN.md §6): normalise (text.py) -> curated alias table -> hybrid retrieval
(pgvector nearest neighbours + lexical word match) -> rerank -> accept above a threshold.
Below the threshold the name stays unresolved; an LLM tiebreak plugs in here in M4.
"""

import re
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from larder_core.names import singular

type Method = Literal["alias", "embedding", "unmatched"]

# Not ingredients: prepared dishes and brand/restaurant items.
EXCLUDED_CATEGORIES = (
    "Baby Foods",
    "Fast Foods",
    "Restaurant Foods",
    "Meals, Entrees, and Side Dishes",
    "American Indian/Alaska Native Foods",
)
ACCEPT_THRESHOLD = 0.88
VECTOR_CANDIDATES = 30
LEXICAL_CANDIDATES = 30

# Processing states: penalised unless the ingredient name asks for them.
_STATE_WORDS = frozenset(
    {
        "baked",
        "boiled",
        "braised",
        "breaded",
        "canned",
        "cooked",
        "dehydrated",
        "dried",
        "fried",
        "frozen",
        "grilled",
        "imitation",
        "meatless",
        "microwaved",
        "mix",
        "pickled",
        "prepared",
        "roasted",
        "sauteed",
        "smoked",
        "stewed",
        "substitute",
        "sweetened",
        "toasted",
    }
)
# Words that turn an ingredient into a different product ("Bread, egg", "Oil, nutmeg butter").
_PRODUCT_WORDS = frozenset(
    {
        "bread",
        "cake",
        "candies",
        "cookie",
        "cookies",
        "cracker",
        "crackers",
        "dessert",
        "drink",
        "flavored",
        "muffin",
        "pie",
        "pudding",
        "salad",
        "sandwich",
        "snack",
        "snacks",
        "soup",
        "spread",
    }
)


# Things made *from* an ingredient: "Flour, almond", "Oil, walnut", "Lemon juice".
_DERIVED_WORDS = frozenset(
    {
        "bran",
        "butter",
        "extract",
        "flour",
        "greens",
        "juice",
        "leaf",
        "leave",
        "milk",
        "oil",
        "paste",
        "powder",
        "puree",
        "sauce",
        "shake",
        "spread",
        "sprouted",
        "stalk",
        "syrup",
        "vinegar",
        "water",
        "yogurt",
    }
)
# Variants that change the nutrition; penalised unless asked for ("full fat" != "fat free").
_VARIANT_WORDS = frozenset({"free", "light", "lite", "low", "nonfat", "reduced", "unsweetened"})
# USDA's wording for "the ordinary one".
_GENERIC_PHRASES = ("all commercial varieties", "year round average", "mixed species", "all types")

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


@dataclass(frozen=True, slots=True)
class Candidate:
    food_id: int
    description: str
    category: str | None
    similarity: float  # cosine similarity of name and description embeddings
    has_macros: bool
    portions: int
    kcal: float | None = None


@dataclass(frozen=True, slots=True)
class Match:
    food_id: int | None
    method: Method
    score: float | None = None


def tokens(s: str) -> list[str]:
    return [singular(t) for t in re.findall(r"[a-z]+", s.lower())]


def score(query: str, c: Candidate) -> float:
    """Rerank score: embedding similarity adjusted by lexical evidence and data usefulness."""
    q = set(tokens(query))
    d = tokens(c.description)
    dset = set(d)
    coverage = len(q & dset) / len(q) if q else 0.0
    s = c.similarity + 0.15 * coverage
    # The head noun of a USDA description comes first ("Onions, raw" -> onion).
    if d and d[0] in q:
        s += 0.04
    s -= 0.05 * len((dset & _STATE_WORDS) - q)
    s -= 0.08 * len((dset & _PRODUCT_WORDS) - q)
    s -= 0.08 * len((dset & _DERIVED_WORDS) - q)
    s -= 0.05 * len((dset & _VARIANT_WORDS) - q)
    if any(phrase in c.description.lower() for phrase in _GENERIC_PHRASES):
        s += 0.03
    if re.search(r"\b[A-Z]{3,}\b", c.description):  # branded item ("SMART SOUP", "NESTLE")
        s -= 0.1
    if "raw" in dset or "fresh" in dset:
        # Raw is the default form, unless the name asks for a processed one ("dried cherries").
        s += -0.05 if q & _STATE_WORDS else 0.02
    if not c.has_macros:
        s -= 0.1
    if c.portions:
        s += 0.01
    s -= 0.002 * max(0, len(d) - len(q) - 2)  # prefer the plainer description
    return s


def best(query: str, candidates: list[Candidate]) -> tuple[Candidate, float] | None:
    scored = [(c, score(query, c)) for c in candidates]
    return max(scored, key=lambda cs: (cs[1], -cs[0].food_id)) if scored else None


_CANDIDATES_SQL = text(
    """
    WITH vec AS (
        SELECT e.food_id, 1 - (e.embedding <=> CAST(:q AS vector)) AS similarity
        FROM food_embeddings e JOIN foods f ON f.id = e.food_id
        WHERE NOT (coalesce(f.category, '') = ANY(:excluded))
        ORDER BY e.embedding <=> CAST(:q AS vector)
        LIMIT :k_vec
    ),
    lex AS (
        SELECT f.id AS food_id, 1 - (e.embedding <=> CAST(:q AS vector)) AS similarity
        FROM foods f JOIN food_embeddings e ON e.food_id = f.id
        WHERE NOT (coalesce(f.category, '') = ANY(:excluded)) AND f.description ~* :pattern
        LIMIT :k_lex
    ),
    cand AS (SELECT * FROM vec UNION SELECT * FROM lex)
    SELECT f.id, f.description, f.category, cand.similarity,
           (f.kcal IS NOT NULL AND f.protein_g IS NOT NULL AND f.fat_g IS NOT NULL
            AND f.carbs_g IS NOT NULL) AS has_macros,
           (SELECT count(*) FROM food_portions p WHERE p.food_id = f.id) AS portions,
           f.kcal
    FROM cand JOIN foods f ON f.id = cand.food_id
    """
)


async def candidates(session: AsyncSession, query: str, vector: list[float]) -> list[Candidate]:
    words = [re.escape(w) for w in tokens(query) if len(w) >= 3]
    # Every query word must appear (as a word prefix, so "onion" matches "Onions").
    pattern = "".join(f"(?=.*\\m{w})" for w in words) if words else "^$"
    rows = await session.execute(
        _CANDIDATES_SQL,
        {
            "q": str(vector),
            "excluded": list(EXCLUDED_CATEGORIES),
            "pattern": pattern,
            "k_vec": VECTOR_CANDIDATES,
            "k_lex": LEXICAL_CANDIDATES,
        },
    )
    return [Candidate(r[0], r[1], r[2], float(r[3]), bool(r[4]), int(r[5]), r[6]) for r in rows]


async def rank(
    session: AsyncSession, name: str, vector: list[float]
) -> tuple[Candidate, float] | None:
    """Best food for a normalised name; `vector` must embed `rewrite(name)`."""
    query = rewrite(name)
    return best(query, await candidates(session, query, vector))

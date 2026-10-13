"""Rules for linking a regional or branded food to the generic food it counts as (shared by
the batch linker, larder_data.generics, and the API's on-demand linking of products).

- Names to try in the reviewed vocabularies (exact recipe aliases, the receipt vocabulary):
  the name as written and CoFID's "Head, qualifier" turned round ("Milk, semi-skimmed" ->
  "semi-skimmed milk"); the head alone only when the rest says how it's sold ("Black pudding,
  raw"), never which kind ("Milk, skimmed" is not "milk").
- Plausibility: reviewed names need energy within half (UK back bacon is leaner than US bacon
  and still counts as bacon); automatic matches need the same category when both are known and
  energy, protein and fat close per 100 g.
"""

from dataclasses import dataclass
from functools import cache

from larder_core.aliases import load_alias_rows
from larder_core.names import normalise_name
from larder_core.receipts import load_receipt_foods

__all__ = ["Facts", "close", "name_endings", "name_forms", "plausible", "vocabulary"]

_AS_SOLD = frozenset(
    {
        "raw",
        "average",
        "fresh",
        "unfortified",
        "fortified",
        "dried",
        "dry",
        "uncooked",
        "flesh only",
        "retail",
        "chilled",
        "frozen",
        "whole",
        "loose",
        "fresh or frozen",
    }
)


@dataclass(frozen=True, slots=True)
class Facts:
    category: str | None
    kcal: float | None
    protein_g: float | None
    fat_g: float | None


def name_forms(description: str, brand: str | None = None) -> list[str]:
    """Normalised names to look up, most specific first (brand words removed)."""
    parts = [p.strip() for p in description.split(",") if p.strip()]
    forms = [description]
    if len(parts) >= 2:
        forms.append(f"{parts[1]} {parts[0]}")
        if all(p.casefold() in _AS_SOLD for p in parts[1:]):
            forms.append(parts[0])
    drop: set[str] = set(normalise_name(brand).split()) if brand else set()
    out: list[str] = []
    for form in forms:
        text = " ".join(w for w in normalise_name(form).split() if w not in drop)
        if text and text not in out:
            out.append(text)
    return out


def name_endings(name: str) -> list[str]:
    """A product name's endings, longest first: English names end with the food ("pure irish
    butter" -> "irish butter", "butter"). Matches on these must also agree on the category."""
    words = name.split()
    return [" ".join(words[i:]) for i in range(1, len(words))]


@cache
def vocabulary() -> dict[str, int]:
    """Reviewed names of the same food -> FDC id (alias approximations are stand-ins: left
    out)."""
    exact = {a.name: a.fdc_id for a in load_alias_rows() if not a.approximation}
    return exact | load_receipt_foods()


def close(a: float | None, b: float | None, *, absolute: float, relative: float) -> bool:
    """Unknown values don't veto; known ones must be within max(absolute, relative * larger)."""
    if a is None or b is None:
        return True
    return abs(a - b) <= max(absolute, relative * max(a, b))


def plausible(food: Facts, generic: Facts, *, reviewed: bool, same_category: bool = False) -> bool:
    """`reviewed`: the generic came from a reviewed name; `same_category`: also require the
    categories to agree when both are known (for partial names like a product's ending)."""
    categories_differ = bool(
        food.category and generic.category and food.category != generic.category
    )
    if reviewed:
        if same_category and categories_differ:
            return False
        return close(food.kcal, generic.kcal, absolute=50, relative=0.5)
    if categories_differ:
        return False
    return (
        close(food.kcal, generic.kcal, absolute=25, relative=0.2)
        and close(food.protein_g, generic.protein_g, absolute=3, relative=0.25)
        and close(food.fat_g, generic.fat_g, absolute=3, relative=0.25)
    )

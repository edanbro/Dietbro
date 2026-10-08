"""Parsed measure + a food's USDA portions -> grams.

Mass converts directly. Volume uses the food's density (median g/ml across its volume
portions), else a per-category default. Counts ("2 cloves", "1 large", "3") use the matching
portion weight; small tables cover containers and pieces USDA doesn't weigh (a 400 g tin, a
bay leaf). Returns None when nothing applies, so the line stays unresolved rather than guessed.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

from larder_core.units import MASS_UNITS, SIZES, VOLUME_UNITS, Dimension, Measure, convert


@dataclass(frozen=True, slots=True)
class Portion:
    amount: float
    unit: str
    qualifier: str | None
    grams: float

    @property
    def per_unit(self) -> float:
        return self.grams / self.amount


# Juice / zest yield per fruit (g).
JUICE_G = {"lemon": 30.0, "lime": 20.0, "orange": 85.0, "grapefruit": 120.0}
ZEST_G = {"lemon": 2.0, "lime": 1.0, "orange": 3.0, "grapefruit": 4.0}
# Count units USDA rarely weighs. UK tins are 400 g; a stock cube is 10 g.
COUNT_DEFAULT_G = {
    "bag": 200.0,
    "ball": 125.0,
    "bottle": 500.0,
    "bulb": 50.0,
    "bunch": 30.0,
    "can": 400.0,
    "carton": 500.0,
    "clove": 3.0,
    "cube": 10.0,
    "head": 300.0,
    "jar": 300.0,
    "leaf": 0.5,
    "packet": 200.0,
    "pod": 3.0,
    "pot": 150.0,
    "rasher": 25.0,
    "sheet": 20.0,
    "slice": 25.0,
    "sprig": 1.0,
    "stalk": 40.0,
    "stick": 5.0,
    "tub": 250.0,
}
# One "piece" of foods USDA weighs only by volume (keyword in the ingredient name -> grams).
PIECE_G = {
    "bay leaf": 0.2,
    "cardamom": 0.2,
    "cinnamon stick": 3.0,
    "clove": 0.1,  # the spice; garlic cloves are weighed by USDA portions
    "star anise": 1.0,
    "vanilla pod": 3.0,
    "lemongrass": 15.0,
    "shallot": 30.0,
    "chilli": 5.0,
    "chili": 5.0,
    "prawn": 15.0,
    "shrimp": 15.0,
    "drumstick": 110.0,
    "pork chop": 200.0,
    "lamb leg": 2000.0,
    "butternut squash": 1000.0,
    "thyme": 1.0,
    "rosemary": 1.0,
    "sage": 1.0,
    "parsley": 1.0,
    "coriander": 1.0,
    "mint": 1.0,
    "basil": 1.0,
    "dill": 1.0,
}
# g/ml for foods without volume portions, by USDA category; otherwise water.
CATEGORY_DENSITY = {
    "Fats and Oils": 0.92,
    "Cereal Grains and Pasta": 0.6,
    "Nut and Seed Products": 0.6,
    "Spices and Herbs": 0.5,
    "Baked Products": 0.4,
}
DEFAULT_DENSITY = 1.0
# Portion units that are packaging or servings, not "one of the thing".
_NOT_EACH = frozenset(
    {"serving", "nlea", "packet", "container", "bag", "jar", "can", "bottle", "box", "oz", "lb"}
)


def density(portions: Sequence[Portion]) -> float | None:
    """Grams per millilitre, from the food's volume portions (median)."""
    values = [
        p.grams / convert(p.amount, p.unit, "ml")
        for p in portions
        if p.unit in VOLUME_UNITS and p.amount > 0
    ]
    return median(values) if values else None


def grams_for(
    measure: Measure, portions: Sequence[Portion], name: str, category: str | None = None
) -> float | None:
    if measure.vague and measure.unit is None:
        # "Sugar: ''", "Rice: steamed": an unstated small amount, taken as a tablespoon.
        measure = Measure(measure.quantity, "tbsp", vague=True)
    q = measure.quantity
    if measure.dimension is Dimension.MASS:
        assert measure.unit is not None
        return convert(q, measure.unit, "g")
    if measure.dimension is Dimension.VOLUME:
        assert measure.unit is not None
        d = density(portions) or CATEGORY_DENSITY.get(category or "", DEFAULT_DENSITY)
        return convert(q, measure.unit, "ml") * d

    unit = measure.unit
    if unit in ("juice", "zest"):
        table = JUICE_G if unit == "juice" else ZEST_G
        return q * next((g for fruit, g in table.items() if fruit in name), table["lemon"])

    if unit is not None:
        same = [p.per_unit for p in portions if p.unit == unit]
        if same:
            return q * median(same)
        return q * COUNT_DEFAULT_G[unit] if unit in COUNT_DEFAULT_G else None

    each = each_weight(portions, measure.size, name)
    if each is None:
        each = next((g for key, g in PIECE_G.items() if key in name), None)
    return None if each is None else q * each


def count_portions(portions: Sequence[Portion]) -> list[Portion]:
    """Portions that weigh "one of the thing" (clove, large, fruit), not volumes or packaging."""
    return [
        p
        for p in portions
        if p.unit not in VOLUME_UNITS and p.unit not in MASS_UNITS and p.unit not in _NOT_EACH
    ]


def each_weight(portions: Sequence[Portion], size: str | None, name: str) -> float | None:
    """Weight of "one" of the food, e.g. one medium onion, one large egg, one garlic clove."""
    each = count_portions(portions)
    if not each:
        return None

    def size_of(p: Portion) -> str | None:
        if p.unit in SIZES:
            return p.unit
        first = (p.qualifier or "").split(" ", 1)[0]
        return first if first in SIZES else None

    if size is not None:
        sized = [p.per_unit for p in each if size_of(p) == size]
        if sized:
            return median(sized)
    for wanted in ("medium", None, "large", "small"):
        matches = [p.per_unit for p in each if size_of(p) == wanted]
        if wanted is None:
            # Unsized "each" portions; for garlic and similar, a clove is the natural unit.
            matches = [p.per_unit for p in each if size_of(p) is None]
            if "garlic" not in name:
                non_clove = [p.per_unit for p in each if size_of(p) is None and p.unit != "clove"]
                matches = non_clove or matches
        if matches:
            return median(matches)
    return None

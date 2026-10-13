"""Open Food Facts products (https://world.openfoodfacts.org, data under the ODbL): parsing a
product from the bulk CSV export or the product API into what we store, barcode normalisation
and the allergen tag mapping. Pure: no I/O.

Crowdsourced data is checked before it's kept: a product needs a name and plausible energy per
100 g, macros above 100 g/100 g are dropped. Declared allergens and "may contain" traces are
mapped to the 14 EU/UK allergens; tags we don't know are read as words (tag_text) so nothing a
label declares is lost.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, cast

from larder_core.allergens import Allergen
from larder_core.regions import REGIONS
from larder_core.tagging import tag_text

__all__ = [
    "COUNTRY_TAGS",
    "OffProduct",
    "allergens_from_tags",
    "country_tags",
    "normalise_barcode",
    "parse_product",
]

MAX_KCAL_PER_100G = 900  # pure fat is ~900
_KJ_PER_KCAL = 4.184

# en:<country name> -> ISO code, for the countries the app supports.
COUNTRY_TAGS: dict[str, str] = {
    "en:" + r.name.casefold().replace(" ", "-"): r.country for r in REGIONS.values()
}


def country_tags(countries: Iterable[str]) -> set[str]:
    """ISO codes -> OFF country tags ({"IE"} -> {"en:ireland"})."""
    wanted = {c.upper() for c in countries}
    return {tag for tag, code in COUNTRY_TAGS.items() if code in wanted}


_ALLERGEN_TAGS: dict[str, frozenset[Allergen]] = {
    tag: frozenset(allergens)
    for tags, allergens in (
        (("gluten", "wheat", "rye", "barley", "oats", "spelt", "kamut"), {Allergen.GLUTEN}),
        (("milk", "lactose", "dairy"), {Allergen.MILK}),
        (("eggs", "egg"), {Allergen.EGGS}),
        (("fish",), {Allergen.FISH}),
        (("crustaceans", "crustacean"), {Allergen.CRUSTACEANS}),
        (("molluscs", "mollusc"), {Allergen.MOLLUSCS}),
        (("shellfish",), {Allergen.CRUSTACEANS, Allergen.MOLLUSCS}),
        (("peanuts", "peanut"), {Allergen.PEANUTS}),
        (
            (
                "nuts",
                "tree-nuts",
                "almonds",
                "hazelnuts",
                "walnuts",
                "cashew-nuts",
                "cashews",
                "pecan-nuts",
                "pecans",
                "brazil-nuts",
                "pistachio-nuts",
                "pistachios",
                "macadamia-nuts",
                "queensland-nuts",
            ),
            {Allergen.TREE_NUTS},
        ),
        (("soybeans", "soybean", "soy", "soya"), {Allergen.SOY}),
        (("sesame-seeds", "sesame"), {Allergen.SESAME}),
        (("celery",), {Allergen.CELERY}),
        (("mustard",), {Allergen.MUSTARD}),
        (("lupin", "lupine"), {Allergen.LUPIN}),
        (
            ("sulphur-dioxide-and-sulphites", "sulphites", "sulfites", "sulphur-dioxide"),
            {Allergen.SULPHITES},
        ),
    )
    for tag in tags
}


def allergens_from_tags(tags: Iterable[str]) -> frozenset[Allergen]:
    """OFF allergen/trace tags ("en:milk", "en:sulphur-dioxide-and-sulphites", "fr:lait") -> our
    allergens. An unknown tag is read as words, so a declared "en:cashew-butter" still counts."""
    found: set[Allergen] = set()
    for tag in tags:
        name = tag.split(":", 1)[-1].strip().casefold()
        if not name:
            continue
        if name in _ALLERGEN_TAGS:
            found |= _ALLERGEN_TAGS[name]
        else:
            found |= tag_text(name.replace("-", " ")).allergens
    return frozenset(found)


@dataclass(frozen=True, slots=True)
class OffProduct:
    code: str  # as OFF has it (source_id)
    barcode: str | None  # normalised GTIN, when the code is one
    name: str
    brand: str | None
    countries: tuple[str, ...]  # ISO codes we support
    categories: tuple[str, ...]  # OFF tags, most general first (as OFF lists them)
    allergens: frozenset[Allergen]
    traces: frozenset[Allergen]
    ingredients: str | None
    kcal: float
    protein_g: float | None = None
    fat_g: float | None = None
    carbs_g: float | None = None
    fiber_g: float | None = None
    sugars_g: float | None = None
    sat_fat_g: float | None = None
    sodium_mg: float | None = None
    serving_g: float | None = None  # one serving, when the label gives it in g or ml
    packet_g: float | None = None  # the whole pack
    portions: tuple[tuple[str, float], ...] = field(default=())  # (unit, grams)


def normalise_barcode(code: str) -> str | None:
    """A GTIN as stored: digits only, UPC-A (12) and GTIN-14 with a leading 0 as EAN-13, with
    a valid check digit; None when `code` isn't a GTIN (OFF has some internal codes)."""
    digits = "".join(c for c in code if c.isdigit())
    if len(digits) == 14 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 12:
        digits = "0" + digits
    if len(digits) not in (8, 13, 14) or not _check_digit_ok(digits):
        return None
    return digits


def _check_digit_ok(digits: str) -> bool:
    body, check = digits[:-1], int(digits[-1])
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def parse_product(fields: Mapping[str, Any], countries: Iterable[str] = ()) -> OffProduct | None:
    """A product from a CSV export row (all strings, tags comma-separated) or the product API
    (`nutriments` dict, tag lists). None when it lacks a name or plausible energy. `countries`
    limits the stored countries (empty: every supported one)."""
    code = _text(fields.get("code"))
    name = next(
        (
            n
            for key in (
                "product_name",
                "product_name_en",
                "abbreviated_product_name",
                "generic_name",
            )
            if (n := _text(fields.get(key)))
        ),
        None,
    )
    if not code or not name or len(code) > 32:
        return None
    nutriments: Any = fields.get("nutriments")
    nut = cast(Mapping[str, Any], nutriments) if isinstance(nutriments, Mapping) else fields

    kcal = _number(nut.get("energy-kcal_100g"))
    if kcal is None:
        kj = _number(nut.get("energy-kj_100g")) or _number(nut.get("energy_100g"))
        kcal = kj / _KJ_PER_KCAL if kj is not None else None
    if kcal is None or not 0 <= kcal <= MAX_KCAL_PER_100G:
        return None

    sodium = _grams(nut.get("sodium_100g"))
    if sodium is None and (salt := _grams(nut.get("salt_100g"))) is not None:
        sodium = salt * 0.4  # salt is 40% sodium
    wanted = {c.upper() for c in countries}
    sold_in = tuple(
        sorted(
            {
                COUNTRY_TAGS[t]
                for t in _tags(fields.get("countries_tags"))
                if t in COUNTRY_TAGS and (not wanted or COUNTRY_TAGS[t] in wanted)
            }
        )
    )
    allergen_tags = _tags(fields.get("allergens_tags")) or _tags(fields.get("allergens"))
    serving = _number(fields.get("serving_quantity"))
    packet = _number(fields.get("product_quantity"))
    portions: list[tuple[str, float]] = []
    if packet is not None and 0 < packet <= 50_000:
        portions.append(("packet", packet))
    if serving is not None and 0 < serving <= 5_000:
        portions.append(("serving", serving))
    brand = _text(fields.get("brands"))
    return OffProduct(
        code=code,
        barcode=normalise_barcode(code),
        name=name,
        brand=brand.split(",")[0].strip() if brand else None,
        countries=sold_in,
        categories=_tags(fields.get("categories_tags")),
        allergens=allergens_from_tags(allergen_tags),
        traces=allergens_from_tags(_tags(fields.get("traces_tags"))),
        ingredients=_text(fields.get("ingredients_text_en"))
        or _text(fields.get("ingredients_text")),
        kcal=round(kcal, 1),
        protein_g=_grams(nut.get("proteins_100g")),
        fat_g=_grams(nut.get("fat_100g")),
        carbs_g=_grams(nut.get("carbohydrates_100g")),
        fiber_g=_grams(nut.get("fiber_100g")),
        sugars_g=_grams(nut.get("sugars_100g")),
        sat_fat_g=_grams(nut.get("saturated-fat_100g")),
        sodium_mg=round(sodium * 1000, 1) if sodium is not None else None,
        serving_g=serving if serving and 0 < serving <= 5_000 else None,
        packet_g=packet if packet and 0 < packet <= 50_000 else None,
        portions=tuple(portions),
    )


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n == n and abs(n) != float("inf") else None  # not NaN or infinite


def _grams(value: Any) -> float | None:
    """A per-100 g amount, dropped when impossible (negative or over 100 g)."""
    n = _number(value)
    return round(n, 2) if n is not None and 0 <= n <= 100 else None


def _tags(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    items: list[Any] = (
        list(cast(Iterable[Any], value))
        if isinstance(value, list | tuple)
        else str(value).split(",")
    )
    return tuple(t for t in (str(i).strip().casefold() for i in items) if t)

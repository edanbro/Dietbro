"""Supermarket receipt text -> item lines (receipt intake, docs/adr/0016). Pure: no I/O.

`parse_receipt(text)` reads text as printed (pasted, or OCR output joined into lines) and keeps
lines that look like items: a product name and a price. It drops everything else - store
headers, totals, VAT/tax, payment and change, loyalty points, multibuy and member savings
(negative prices), carrier bags - by keyword and shape, never by position. Follow-on lines
complete the item above them: `2 @ 0.46` / `2 x 0.55` set its count, `0.352 kg @ £1.10/kg`
gives a loose item its weight (or a name printed alone on the line above its price).

`clean_name` turns a product name into words the food matcher knows: item codes, tax flags,
store brands and marketing words go ("TSC", "GV", "ESS", "LOOSE", "BRITISH"); size and count
tokens are read ("500G", "1.5KG", "4PT", "2 GAL", "4X420G", "6PK", "12CT", "1 DOZ", "EGGS 6");
a small curated table expands receipt abbreviations (SKMD -> skimmed, CHKN BRST -> chicken
breast, TOMS -> tomatoes) and brands that name a food (Warburtons -> bread); words are made
singular. `match_names` gives the phrases to try against the alias tables, longest first;
`load_receipt_foods` is the receipt vocabulary checked before the recipe alias table
(data/receipt_foods.csv: shop names like "semi skimmed", "chopped tomato" -> the tinned food).

`estimate_amount` turns an item's size into the pantry's quantity, unit and grams with the
matched food's USDA portions (larder_core.quantities): metric sizes are kept as printed,
imperial ones converted (oz/lb -> g, pints/gallons -> ml); piece counts use the food's count
portion ("6 large" eggs); with no size it is one typical portion, flagged approximate.
"""

import csv
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, replace
from functools import cache
from importlib import resources
from statistics import median

from larder_core.names import singular
from larder_core.quantities import (
    COUNT_DEFAULT_G,
    PART_UNITS,
    Portion,
    count_portions,
    grams_for,
)
from larder_core.shelf_life import Storage
from larder_core.units import MASS_UNITS, SIZES, VOLUME_UNITS, Measure, convert

GALLON_ML = 3785.411784
TYPICAL_G = 100.0  # one "portion" of a food USDA gives no portions for
MAX_COUNT = 24  # a leading/trailing number above this is a code or a size, not a count


@dataclass(frozen=True, slots=True)
class ReceiptItem:
    """One product line. Total = count x pieces x size (any of them may be absent)."""

    raw: str  # as printed; a follow-on quantity/weight line is appended after " | "
    name: str  # cleaned words for matching ("chicken breast fillet")
    count: float = 1.0  # how many were bought: "2 x", "2 @ 0.46", a quantity column
    pieces: float | None = None  # items in one pack: "6PK", "12CT", "4X420G"
    size: Measure | None = None  # mass or volume of one (pack's) item: 650 g, 4 pint
    grade: str | None = None  # small | medium | large, when printed (eggs)
    price_minor: int | None = None  # pence / cents
    storage: Storage | None = None  # frozen / tinned per the receipt


@dataclass(frozen=True, slots=True)
class Amount:
    """What goes in the pantry: `quantity` `unit` (a unit the pantry accepts for the food)
    weighing `grams`; `approx` when the size was not on the receipt."""

    quantity: float
    unit: str
    grams: float
    approx: bool


# --- vocabulary -------------------------------------------------------------------------------

# Receipt abbreviations -> words (applied per token, lowercase). Curated from UK (Tesco,
# Sainsbury's, Asda, Morrisons, Waitrose, Co-op) and US (Walmart, Kroger, Costco) receipts.
ABBREVIATIONS: dict[str, str] = {
    "skmd": "skimmed",
    "skm": "skimmed",
    "chkn": "chicken",
    "chk": "chicken",
    "ckn": "chicken",
    "brst": "breast",
    "bst": "breast",
    "fllt": "fillet",
    "fllts": "fillets",
    "flt": "fillet",
    "flts": "fillets",
    "thgh": "thigh",
    "thghs": "thighs",
    "tom": "tomato",
    "toms": "tomatoes",
    "pot": "potato",
    "pots": "potatoes",
    "swt": "sweet",
    "yog": "yogurt",
    "yogh": "yogurt",
    "yoghurt": "yogurt",
    "yoghurts": "yogurts",
    "ygt": "yogurt",
    "grk": "greek",
    "nat": "natural",
    "brd": "bread",
    "wmeal": "wholemeal",
    "whlml": "wholemeal",
    "wht": "white",
    "brwn": "brown",
    "chs": "cheese",
    "chse": "cheese",
    "ched": "cheddar",
    "chedd": "cheddar",
    "chdr": "cheddar",
    "mat": "mature",
    "matr": "mature",
    "shrp": "sharp",
    "shrd": "shredded",
    "mozz": "mozzarella",
    "btr": "butter",
    "bttr": "butter",
    "sltd": "salted",
    "unsltd": "unsalted",
    "veg": "vegetable",
    "carr": "carrot",
    "crrt": "carrot",
    "ons": "onions",
    "onio": "onion",
    "mush": "mushroom",
    "mshrm": "mushroom",
    "mshrms": "mushrooms",
    "broc": "broccoli",
    "brocc": "broccoli",
    "ban": "banana",
    "bans": "bananas",
    "bnna": "banana",
    "appl": "apple",
    "strawb": "strawberries",
    "strwb": "strawberries",
    "strwbry": "strawberries",
    "rasp": "raspberries",
    "blueb": "blueberries",
    "avo": "avocado",
    "avoc": "avocado",
    "oj": "orange juice",
    "jce": "juice",
    "orng": "orange",
    "crm": "cream",
    "dbl": "double",
    "sgl": "single",
    "saus": "sausages",
    "ssge": "sausage",
    "ssgs": "sausages",
    "bcn": "bacon",
    "smkd": "smoked",
    "unsmkd": "unsmoked",
    "salm": "salmon",
    "spag": "spaghetti",
    "pst": "pasta",
    "rce": "rice",
    "bsmti": "basmati",
    "grnd": "ground",
    "grd": "ground",
    "bf": "beef",
    "mnc": "mince",
    "pnt": "peanut",
    "pb": "peanut butter",
    "cuc": "cucumber",
    "cucmbr": "cucumber",
    "lett": "lettuce",
    "ltce": "lettuce",
    "ppr": "pepper",
    "pepp": "pepper",
    "grn": "green",
    "spnch": "spinach",
    "grlc": "garlic",
    "gngr": "ginger",
    "lmn": "lemon",
    "lmns": "lemons",
    "flr": "flour",
    "sgr": "sugar",
    "gran": "granulated",
    "porr": "porridge",
    "bns": "beans",
    "bkd": "baked",
    "froz": "frozen",
    "frz": "frozen",
    "frzn": "frozen",
}
# Brands that name the food when the product name doesn't ("WARBURTONS WHOLEMEAL 800G").
BRAND_FOODS: dict[str, str] = {
    "warburtons": "bread",
    "hovis": "bread",
    "kingsmill": "bread",
    "lurpak": "butter",
    "anchor": "butter",
    "muller": "yogurt",
    "quaker": "oats",
    # Irish brands
    "kerrygold": "butter",
    "avonmore": "milk",
    "brennans": "bread",
    "clonakilty": "black pudding",
    "glenisk": "yogurt",
}
# Store brands, tax flags and marketing words: never which food it is.
NOISE: frozenset[str] = frozenset(
    {
        # store brands and ranges
        "tesco",
        "tsc",
        "js",
        "sainsbury's",
        "sainsburys",
        "asda",
        "morrisons",
        "co",
        "op",
        "coop",
        "waitrose",
        "wr",
        "ess",
        "essential",
        "essentials",
        "m&s",
        "aldi",
        "lidl",
        "gv",
        "kro",
        "kroger",
        "ks",
        "kirkland",
        # Irish shops
        "dunnes",
        "stores",
        "supervalu",
        "centra",
        "spar",
        "eurospar",
        "londis",
        "mace",
        "daybreak",
        "gg",
        "finest",
        "everyday",
        "value",
        "great",
        "signature",
        "grower's",
        "growers",
        "selection",
        "heinz",
        "nf",
        "kf",
        # marketing and handling
        "organic",
        "org",
        "british",
        "irish",
        "todays",
        "fresh",
        "loose",
        "ripe",
        "free",
        "range",
        "fr",
        "classic",
        "lean",
        "pack",
        "pk",
        "bag",
        "tray",
        "net",
        "each",
        "ea",
        "extra",
        "premium",
        "smooth",
        "soft",
        "sliced",
        "thick",
        "hass",
        "florets",
        "salad",
        "boneless",
        "bnls",
        "skinless",
        "sknls",
        "wild",
        "ct",
        "doz",
        "dozen",
    }
)
_GRADES: dict[str, str] = {
    "lge": "large",
    "lrg": "large",
    "lg": "large",
    "large": "large",
    "med": "medium",
    "medium": "medium",
    "sml": "small",
    "small": "small",
}
_SIZE_UNITS: dict[str, str] = {
    "g": "g",
    "gm": "g",
    "gms": "g",
    "kg": "kg",
    "ml": "ml",
    "cl": "cl",
    "l": "l",
    "lt": "l",
    "ltr": "l",
    "litre": "l",
    "litres": "l",
    "oz": "oz",
    "lb": "lb",
    "lbs": "lb",
    "pt": "pint",
    "pts": "pint",
    "pint": "pint",
    "pints": "pint",
    "gal": "gal",
    "gallon": "gal",
    "gallons": "gal",
}
# Count portions that are not "one of the thing" (a garlic bulb is not a clove).
_NOT_ONE = PART_UNITS | {"clove", "leaf", "sprig"}
_UNIT_RE = "|".join(sorted(_SIZE_UNITS, key=len, reverse=True))

_JUNK = re.compile(
    r"\b(?:sub[\s-]?total|total|balance|due|vat|tax|card|visa|master\s?card|amex|debit|credit|"
    r"contactless|change|cash|tender|tend|saving|savings|saved|multibuy|promotion|promo|"
    r"discount|clubcard|nectar|points|coupon|voucher|refund|deposit|delivery|charge|charged|"
    r"amount|approved|auth|price|reward|rewards|rollback|carrier|bag for life|items|thank|"
    r"tel|www|order|loyalty|offer|deal|rounding|paid|payment|receipt|member|transaction|"
    r"redcard|store|cashier|operator)\b"
)
_PRICE = re.compile(
    r"(?:^|\s)(?P<neg>-)?\s?[£$€]?\s?(?P<amount>\d{1,5}[.,]\d{2})(?P<neg2>-)?"
    r"(?:\s+[A-Za-z*]{1,2})?\s*$"
)
_WEIGHT = re.compile(
    r"^(?P<w>\d+(?:[.,]\d+)?)\s*(?P<u>kg|g|lbs?)\s*@\s*[£$€]?\s*\d+(?:[.,]\d+)?\s*/\s*"
    r"(?:kg|lb)\b"
)
_QUANTITY = re.compile(r"^(?P<n>\d{1,3})\s*[x@]\s*[£$€]?\s*\d+[.,]\d{2}\b")
_TOKEN = re.compile(r"[a-z][a-z&']*")


@cache
def load_receipt_foods() -> dict[str, int]:
    """Hand-reviewed grocery names -> FDC id, for names the recipe alias table lacks or maps to
    a different form than shops sell (tinned beans, UK milk grades)."""
    path = resources.files("larder_core") / "data" / "receipt_foods.csv"
    with path.open(encoding="utf-8") as f:
        return {r["name"]: int(r["fdc_id"]) for r in csv.DictReader(f)}


# --- lines ------------------------------------------------------------------------------------


def parse_receipt(text: str) -> list[ReceiptItem]:
    """Item lines of a receipt, in order. Never raises."""
    items: list[ReceiptItem] = []
    pending: str | None = None  # a name printed without a price (its weight line follows)
    last = -1  # index of the item a follow-on line may complete
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split())
        if not line:
            continue
        lower = _ocr_fixes(_fold(line).lower())
        if weight := _WEIGHT.match(lower):
            size = Measure(_float(weight["w"]), _SIZE_UNITS[weight["u"]])
            if pending is not None:
                item = _item(pending, pending, _PRICE.search(lower))
                if item is not None and size.quantity > 0:
                    items.append(replace(item, raw=f"{item.raw} | {line}", size=size))
                    last = len(items) - 1
                pending = None
            elif last >= 0 and items[last].size is None and size.quantity > 0:
                items[last] = replace(items[last], size=size, raw=f"{items[last].raw} | {line}")
                last = -1
            continue
        if quantity := _QUANTITY.match(lower):
            n = int(quantity["n"])
            if last >= 0 and items[last].count == 1 and 1 < n <= MAX_COUNT:
                items[last] = replace(items[last], count=n, raw=f"{items[last].raw} | {line}")
            last, pending = -1, None
            continue
        if _JUNK.search(lower):
            last, pending = -1, None
            continue
        price = _PRICE.search(lower)
        if price is None:
            last = -1
            pending = line if len(_TOKEN.findall(lower)) > 0 else None
            continue
        body = lower[: price.start()].strip()
        if not body and pending is not None:  # "BROCCOLI" / "£0.39" split over two lines
            item = _item(pending, f"{pending} | {line}", price)
        else:
            item = _item(body, raw_line.strip(), price)
        pending = None
        if item is None:
            last = -1
            continue
        items.append(item)
        last = len(items) - 1
    return items


def _item(body: str, raw: str, price: re.Match[str] | None) -> ReceiptItem | None:
    """`body` is the name part of the line (no price); `price` the price match, if any."""
    if price is not None and (price["neg"] or price["neg2"]):
        return None  # a discount
    parsed = _parse_body(body.lower())
    if parsed is None:
        return None
    price_minor = round(_float(price["amount"]) * 100) if price is not None else None
    return replace(parsed, raw=raw, price_minor=price_minor)


def _fold(text: str) -> str:
    """ASCII only: accents OCR adds ("Šaved") and symbols other than currency go."""
    folded = unicodedata.normalize("NFKD", text.replace("\u00d7", "x"))
    return "".join(c for c in folded if c.isascii() or c in "£€")


def _ocr_fixes(text: str) -> str:
    """Common OCR confusions on receipts: a zero for the letter O inside words ("KR0") and in
    ounces ("80Z" = 8 oz; no unit is spelt "z")."""
    text = re.sub(r"(\d)0z\b", r"\1oz", text)
    return re.sub(r"(?<=[a-z])0(?=[a-z]|\b)", "o", text)


def _parse_body(text: str) -> ReceiptItem | None:
    """A product name with its size/count tokens -> an item without price or raw text."""
    s = _ocr_fixes(_fold(text).lower())
    s = re.sub(r"\b\d{5,}\b", " ", s)  # item codes, UPCs
    count = 1.0
    if m := re.match(r"^\s*(\d{1,2})\s*x\s+", s) or re.match(r"^\s*(\d{1,2})\s+(?=[a-z])", s):
        rest = s[m.end() :]
        first = rest.split(" ", 1)[0]
        if 0 < int(m[1]) <= MAX_COUNT and first not in _SIZE_UNITS:
            count, s = float(m[1]), rest
    if (m := re.search(r"\s+x\s?(\d{1,2})\s*$", s)) and 0 < int(m[1]) <= MAX_COUNT:
        count, s = float(m[1]), s[: m.start()]

    pieces: float | None = None
    size: Measure | None = None
    multipack = False
    if m := re.search(rf"\b(\d+)\s*x\s*(\d+(?:[.,]\d+)?)\s*({_UNIT_RE})\b", s):
        pieces, size, multipack = _positive(m[1]), _size(m[2], m[3]), True
        s = s[: m.start()] + " " + s[m.end() :]
    elif m := re.search(rf"(?:\b|(?<=\d))(\d+(?:[.,]\d+)?|1/2|half)\s*({_UNIT_RE})\b", s):
        size = _size(m[1], m[2])
        s = s[: m.start()] + " " + s[m.end() :]
    elif m := re.search(r"\b(gal|gallon)\b", s):
        size = _size("1", m[1])
        s = s[: m.start()] + " " + s[m.end() :]
    if m := re.search(r"\b(\d+)\s*(?:pk|pack|ct|s|pcs|pc)\b", s):
        pieces = _positive(m[1]) or pieces
        s = s[: m.start()] + " " + s[m.end() :]
    elif m := re.search(r"\b(\d+)?\s*doz(?:en)?\b", s):
        pieces = 12 * (_positive(m[1]) or 1)
        s = s[: m.start()] + " " + s[m.end() :]
    if size is not None and not multipack:
        pieces = None  # "STEAKS 2PK 454G": the size is the whole pack's

    milk_fat = re.search(r"\b([12])\s?%", s)
    s = re.sub(r"\d+(?:[.,]\d+)?\s?%|\b\d+/\d+\b", " ", s)
    trailing = re.search(r"[a-z]\s+(\d{1,2})\s*$", s)
    if pieces is None and trailing and 1 < int(trailing[1]) <= 60:
        pieces = float(trailing[1])  # "EGGS 6"
        s = s[: trailing.start() + 1]

    words = _TOKEN.findall(s)
    if milk_fat and "milk" in words:
        words = ["reduced fat" if milk_fat[1] == "2" else "lowfat", *words]
    grade = next((_GRADES[w] for w in words if w in _GRADES), None)
    storage: Storage | None = None
    if any(w in ("frozen", "frz", "frzn", "froz") for w in words):
        storage = "frozen"
    elif any(w in ("tin", "tins", "tinned", "can", "cans", "canned") for w in words):
        storage = "ambient"
    name = _clean_words(words)
    if not name:
        return None
    return ReceiptItem(
        raw="",
        name=name,
        count=count,
        pieces=pieces,
        size=size if size is not None and size.quantity > 0 else None,
        grade=grade,
        storage=storage,
    )


def clean_name(raw: str) -> str:
    """A product name as printed -> matching words ("CHKN BRST FLLTS" -> "chicken breast
    fillet"). Size and count tokens are dropped (parse_receipt reads them)."""
    item = _parse_body(raw.lower())
    return "" if item is None else item.name


def _clean_words(words: Sequence[str]) -> str:
    out: list[str] = []
    brand_food: str | None = None
    for word in words:
        word = word.strip("'&")
        if not word or (len(word) == 1 and word != "x") or word == "x":
            continue
        if word in _GRADES or word in _SIZE_UNITS:
            continue
        if word in BRAND_FOODS:
            brand_food = BRAND_FOODS[word]
            continue
        expanded = ABBREVIATIONS.get(word, word)
        for part in expanded.split():
            if part in NOISE or part in ("frozen", "tin", "tins", "tinned"):
                continue
            out.append(singular(part))
    if brand_food is not None and brand_food not in out:
        out.append(singular(brand_food))
    return " ".join(out)


def match_names(name: str) -> list[str]:
    """Phrases to look up, best first: the whole name, then shorter runs of its words, longest
    first and, among equals, rightmost first (the head noun ends an English name)."""
    words = name.split()
    out: list[str] = []
    for length in range(len(words), 0, -1):
        for start in range(len(words) - length, -1, -1):
            out.append(" ".join(words[start : start + length]))
    return out


# --- amounts ----------------------------------------------------------------------------------


def estimate_amount(
    item: ReceiptItem, portions: Sequence[Portion], description: str, category: str | None
) -> Amount:
    """Quantity, unit and grams of the item for the pantry, from the matched food's portions."""
    name = description.lower()
    n = item.count * (item.pieces or 1)
    if item.size is not None and item.size.unit is not None:
        total, unit = n * item.size.quantity, item.size.unit
        if unit in MASS_UNITS:
            grams = convert(total, unit, "g")
            if unit in ("g", "kg"):
                return Amount(_round(total), unit, grams, approx=False)
            return Amount(_round(grams), "g", grams, approx=False)
        if unit in VOLUME_UNITS:
            ml = convert(total, unit, "ml")
            grams = grams_for(Measure(ml, "ml"), portions, name, category) or ml
            if unit in ("ml", "l"):
                return Amount(_round(total), unit, grams, approx=False)
            return Amount(_round(ml), "ml", grams, approx=False)
    each = ("bulb", COUNT_DEFAULT_G["bulb"]) if "garlic" in name else _each(portions, item.grade)
    if item.pieces is not None:
        if each is not None:
            return Amount(_round(n), each[0], n * each[1], approx=False)
        piece = grams_for(Measure(n, None), portions, name, category)
        if piece is not None:
            return Amount(_round(piece), "g", piece, approx=False)
    if each is not None:
        return Amount(_round(item.count), each[0], item.count * each[1], approx=True)
    first = next((p.grams for p in portions if p.grams > 0), TYPICAL_G)
    grams = n * first
    return Amount(_round(grams), "g", grams, approx=True)


def _each(portions: Sequence[Portion], grade: str | None) -> tuple[str, float] | None:
    """(unit, grams) of one of the food: the printed grade's portion, else medium, an unsized
    count portion, large, small (as larder_core.quantities.each_weight)."""
    each = count_portions(portions)

    def size_of(p: Portion) -> str | None:
        if p.unit in SIZES:
            return p.unit
        first = (p.qualifier or "").split(" ", 1)[0]
        return first if first in SIZES else None

    for wanted in ([grade] if grade else []) + ["medium", None, "large", "small"]:
        matches = [p for p in each if size_of(p) == wanted and p.unit not in _NOT_ONE]
        matches.sort(key=lambda p: p.unit)  # portions come in no particular order
        if matches:
            unit = matches[0].unit
            return unit, median(p.per_unit for p in matches if p.unit == unit)
    return None


def _round(value: float) -> float:
    return round(value, 3) if value < 10 else float(round(value))


def _float(token: str) -> float:
    return float(token.replace(",", "."))


def _positive(token: str | None) -> float | None:
    if not token:
        return None
    value = _float(token)
    return value if value > 0 else None


def _size(quantity: str, unit: str) -> Measure | None:
    q = 0.5 if quantity in ("1/2", "half") else _float(quantity)
    canonical = _SIZE_UNITS[unit]
    if canonical == "gal":
        return Measure(q * GALLON_ML, "ml")
    return Measure(q, canonical) if q > 0 else None

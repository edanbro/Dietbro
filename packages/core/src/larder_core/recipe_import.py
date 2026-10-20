"""Recipes from web pages: the schema.org `Recipe` most recipe sites embed for search engines
(JSON-LD in a <script type="application/ld+json">), and ingredient lines ("2 tbsp olive oil,
plus extra") split into an amount and a name. Pure functions: fetching lives in the API.
"""

import html
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, cast

from larder_core.units import SIZES, canonical_unit

__all__ = ["ImportedRecipe", "find_recipe", "split_line"]


@dataclass(frozen=True, slots=True)
class ImportedRecipe:
    name: str
    servings: int | None
    ingredients: list[str]
    instructions: str
    category: str | None
    cuisine: str | None
    image_url: str | None


_SCRIPT_RE = re.compile(
    r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.I | re.S
)
_TAG_RE = re.compile(r"<[^>]+>")


def _obj(value: object) -> dict[str, Any] | None:
    return cast("dict[str, Any]", value) if isinstance(value, dict) else None


def _items(value: object) -> list[Any]:
    """A JSON value as a list: lists as they are, anything else as a list of one."""
    return cast("list[Any]", value) if isinstance(value, list) else [value]


def _text(value: object) -> str:
    """Plain text from a JSON-LD string: entities decoded, stray tags dropped, spaces squeezed."""
    if not isinstance(value, str):
        return ""
    text = re.sub(r"\s+", " ", _TAG_RE.sub(" ", html.unescape(value))).strip()
    return re.sub(r"\s+([.,;:!?])", r"\1", text)


def _is_recipe(node: dict[str, Any]) -> bool:
    return "Recipe" in _items(node.get("@type"))


def _nodes(data: object) -> Iterator[dict[str, Any]]:
    """Every object in a JSON-LD document: top-level lists and @graph included."""
    if isinstance(data, list):
        for item in _items(cast(object, data)):
            yield from _nodes(item)
    elif (node := _obj(data)) is not None:
        yield node
        if "@graph" in node:
            yield from _nodes(node["@graph"])


def _first(value: object) -> object:
    items = _items(value)
    return items[0] if items else None


def _servings(value: object) -> int | None:
    for item in _items(value):
        if isinstance(item, int | float) and not isinstance(item, bool) and item > 0:
            return int(item)
        if isinstance(item, str) and (m := re.search(r"\d+", item)):
            return int(m.group())
    return None


def _steps(value: object) -> Iterator[str]:
    """Method steps from a string, a list of strings, HowToStep or HowToSection objects."""
    if isinstance(value, str):
        if text := _text(value):
            yield text
    elif isinstance(value, list):
        for item in _items(cast(object, value)):
            yield from _steps(item)
    elif (node := _obj(value)) is not None:
        if "itemListElement" in node:
            yield from _steps(node["itemListElement"])
        else:
            yield from _steps(node.get("text") or node.get("name"))


def _image(value: object) -> str | None:
    first = _first(value)
    if (node := _obj(first)) is not None:
        first = node.get("url")
    return first if isinstance(first, str) and first.startswith(("https://", "http://")) else None


def find_recipe(page: str) -> ImportedRecipe | None:
    """The first schema.org Recipe on a page with a name and ingredients, or None."""
    for block in _SCRIPT_RE.findall(page):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for node in _nodes(data):
            if not _is_recipe(node):
                continue
            name = _text(node.get("name"))
            lines = [t for t in (_text(i) for i in _items(node.get("recipeIngredient"))) if t]
            if not name or not lines:
                continue
            return ImportedRecipe(
                name=name,
                servings=_servings(node.get("recipeYield")),
                ingredients=lines,
                instructions="\n\n".join(_steps(node.get("recipeInstructions"))),
                category=_text(_first(node.get("recipeCategory"))) or None,
                cuisine=_text(_first(node.get("recipeCuisine"))) or None,
                image_url=_image(node.get("image")),
            )
    return None


# --- ingredient lines ------------------------------------------------------------------------

_FRACTIONS = "½⅓⅔¼¾⅛⅜⅝⅞"  # 1/2 1/3 ... 7/8
_NUMBER = rf"(?:\d+\s*[{_FRACTIONS}]|\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?(?:\s+\d+/\d+)?|[{_FRACTIONS}])"
_RANGE = "(?:-|" + chr(0x2013) + "|to)"  # hyphen, en dash or "to"
_QUANTITY_RE = re.compile(rf"^\s*({_NUMBER}(?:\s*{_RANGE}\s*{_NUMBER})?)\s*", re.I)
_WORDS = {"a", "an", "one", "two", "three", "four", "five", "six", "half"}
_PACKS = r"(?:tins?|cans?|packs?|packets?|jars?|bags?|pots?|tubs?|cartons?)"
_CONTAINER_RE = re.compile(
    rf"^\s*(?:{_NUMBER}\s*x\s*)?{_NUMBER}\s*(?:g|kg|ml|l|oz)\b\s*{_PACKS}?\s*", re.I
)
_PREP_TAIL_RE = re.compile(
    r",\s*(?:plus|to|for|finely|roughly|thinly|chopped|sliced|diced|minced|peeled|grated"
    r"|crushed|halved|beaten|melted|softened|drained|rinsed|trimmed|deseeded|cut|optional"
    r"|at room).*$",
    re.I,
)
# The same notes written without a comma: "onions sliced", "lamb cut into chunks".
_PREP_WORDS_RE = re.compile(
    r"(?<=\S)\s+(?:preferably|sliced|chopped|diced|cut|finely|roughly|thinly|grated|crushed"
    r"|minced|peeled|halved|quartered|skinned|trimmed|deseeded|drained|rinsed|torn|picked"
    r"|to serve|for)\b.*$",
    re.I,
)


def split_line(line: str) -> tuple[str, str]:
    """'2 tbsp olive oil, plus extra' -> ('2 tbsp', 'olive oil'); '400g tin chopped tomatoes'
    -> ('400g tin', 'chopped tomatoes'); 'salt and pepper' -> ('', 'salt and pepper')."""
    text = re.sub(r"\([^)]*\)", " ", html.unescape(line))
    text = re.sub(r"\s+", " ", text).strip(" -•*")
    if m := _CONTAINER_RE.match(text):
        quantity, rest = m.group().strip(), text[m.end() :]
    elif m := _QUANTITY_RE.match(text):
        quantity, rest = m.group().strip(), text[m.end() :]
        words = rest.split()
        taken = 0
        while taken < min(len(words), 2):
            word = words[taken].lower().strip(".,")
            if word not in SIZES and canonical_unit(word) is None:
                break
            taken += 1
        quantity = " ".join([quantity, *words[:taken]])
        rest = " ".join(words[taken:])
    else:
        first, _, after = text.partition(" ")
        quantity, rest = (first, after) if first.lower() in _WORDS and after else ("", text)
    rest = re.sub(r"^of\s+", "", rest.strip(), flags=re.I)
    name = _PREP_WORDS_RE.sub("", _PREP_TAIL_RE.sub("", rest)).strip(" ,.;")
    return quantity, name or rest.strip()

"""USDA survey foods (FNDDS, "Survey Foods" in FoodData Central): ~5,400 foods as people eat
them ("Pizza, cheese", "Milk, whole") with household portions ("1 slice", "1 cup").

Same CSV layout as SR Legacy, with differences handled here:
- the category is a WWEIA category (mapped to a USDA category: larder_core.categories);
- `food_nutrient.nutrient_id` holds the nutrient *number* (208 = energy), translated to the
  FDC nutrient id (1008) through nutrient.csv;
- portions carry the amount in `portion_description` ("1 cup") and a numeric FNDDS portion code
  in `modifier`, which is not a unit; "Quantity not specified", dietary-guideline and school
  portions are skipped;
- `input_food` lists each food's ingredients by SR NDB number: a food that is mostly (>= 80% of
  the weight) one SR food is linked to it as its generic (it "counts as" that food).

Public domain: https://fdc.nal.usda.gov/download-datasets
"""

import csv
import io
import re
import zipfile
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

from larder_core.categories import wweia_category
from larder_data.usda import (
    NUTRIENT_IDS,
    FoodRecord,
    PortionRecord,
    pick_nutrients,
    portion_unit,
)

__all__ = ["DOMINANT_SHARE", "parse_survey_portion", "read_sr_ndb", "read_survey"]

DATASET = "survey_fndds"
DOMINANT_SHARE = 0.8  # an ingredient this share of the weight makes the food count as it
_WANTED = {nid for ids in NUTRIENT_IDS.values() for nid in ids}
_SKIP = ("quantity not specified", "guideline amount", "nfs")
_AMOUNT = re.compile(r"^(\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)\s*(.*)$")


def read_sr_ndb(sr_zip: Path) -> dict[int, int]:
    """SR Legacy NDB number -> FDC id (FNDDS ingredients name SR foods by NDB number)."""
    with zipfile.ZipFile(sr_zip) as zf:
        return {
            int(r["NDB_number"]): int(r["fdc_id"])
            for r in _rows(zf, "sr_legacy_food")
            if r["NDB_number"] and r["fdc_id"]
        }


def read_survey(zip_path: Path, ndb_to_fdc: dict[int, int]) -> list[FoodRecord]:
    """FNDDS foods with macros per 100 g, portions, mapped category and dominant-ingredient
    generic (an SR FDC id; the caller drops links to foods it doesn't have)."""
    with zipfile.ZipFile(zip_path) as zf:
        names = {
            r["wweia_food_category"]: r["wweia_food_category_description"]
            for r in _rows(zf, "wweia_food_category")
        }
        foods: dict[int, FoodRecord] = {}
        for r in _rows(zf, "food"):
            if r["data_type"] != "survey_fndds_food":
                continue
            fdc_id, code = int(r["fdc_id"]), r["food_category_id"]
            foods[fdc_id] = FoodRecord(
                id=fdc_id,
                description=r["description"].strip(),
                data_type=DATASET,
                category=wweia_category(code),
                source_category=names.get(code),
            )

        by_number = {
            r["nutrient_nbr"].split(".")[0]: int(r["id"])
            for r in _rows(zf, "nutrient")
            if r["nutrient_nbr"]
        }
        amounts: dict[int, dict[int, float]] = defaultdict(dict)
        for r in _rows(zf, "food_nutrient"):
            if not (r["fdc_id"] and r["nutrient_id"] and r["amount"]):
                continue
            fdc_id = int(r["fdc_id"])
            nutrient_id = by_number.get(r["nutrient_id"], int(r["nutrient_id"]))
            if fdc_id in foods and nutrient_id in _WANTED:
                amounts[fdc_id][nutrient_id] = float(r["amount"])

        for r in _rows(zf, "food_portion"):
            fdc_id = int(r["fdc_id"] or 0)
            if fdc_id in foods and (portion := parse_survey_portion(r)) is not None:
                foods[fdc_id].portions.append(portion)

        weights: dict[int, dict[int, float]] = defaultdict(lambda: defaultdict(float))
        for r in _rows(zf, "input_food"):
            fdc_id = int(r["fdc_id"] or 0)
            if fdc_id in foods and r["sr_code"] and r["gram_weight"] and not r["fdc_of_input_food"]:
                weights[fdc_id][int(r["sr_code"])] += float(r["gram_weight"])

    for fdc_id, food in foods.items():
        food.nutrients = pick_nutrients(amounts.get(fdc_id, {}))
        parts = weights.get(fdc_id)
        if parts:
            ndb, grams = max(parts.items(), key=lambda kv: kv[1])
            total = sum(parts.values())
            if total > 0 and grams / total >= DOMINANT_SHARE and ndb in ndb_to_fdc:
                food.generic_food_id = ndb_to_fdc[ndb]
                food.generic_method = "input_food"
    return list(foods.values())


def parse_survey_portion(row: dict[str, str]) -> PortionRecord | None:
    """'1 cup' -> (1, cup); '1 slice (1/8 of 14" pizza)' -> (1, slice, '(1/8 of 14" pizza)');
    'Quantity not specified' and zero weights -> None. `modifier` is a portion code: ignored."""
    grams = float(row["gram_weight"] or 0)
    text = " ".join(row["portion_description"].split())
    folded = text.casefold()
    if grams <= 0 or not text or folded.startswith(_SKIP) or "school" in folded:
        return None
    match = _AMOUNT.match(text)
    amount, rest = (_fraction(match.group(1)), match.group(2)) if match else (1.0, text)
    if amount <= 0:
        return None
    unit, qualifier = portion_unit(rest or "serving")
    return PortionRecord(amount=amount, unit=unit, qualifier=qualifier, grams=grams)


def _fraction(text: str) -> float:
    whole, _, frac = text.partition(" ") if "/" in text and " " in text else ("0", "", text)
    if "/" in frac:
        num, den = frac.split("/", 1)
        value = float(num) / float(den) if float(den) else 0.0
    else:
        value = float(frac)
    return float(whole) + value


def _rows(zf: zipfile.ZipFile, name: str) -> Iterator[dict[str, str]]:
    member = next(n for n in zf.namelist() if n.rsplit("/", 1)[-1] == f"{name}.csv")
    with zf.open(member) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8"))

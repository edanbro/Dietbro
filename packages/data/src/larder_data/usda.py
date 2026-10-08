"""USDA FoodData Central importer (Foundation Foods + SR Legacy, CSV releases).

Public domain data: https://fdc.nal.usda.gov/download-datasets
"""

import csv
import io
import logging
import re
import zipfile
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from larder_core.units import SIZES, canonical_unit
from larder_db.models import Food, FoodPortion

logger = logging.getLogger(__name__)

BASE_URL = "https://fdc.nal.usda.gov/fdc-datasets/"
DATASETS: dict[str, str] = {
    "foundation": "FoodData_Central_foundation_food_csv_2026-04-30.zip",
    "sr_legacy": "FoodData_Central_sr_legacy_food_csv_2018-04.zip",
}
_FDC_DATA_TYPE = {"foundation": "foundation_food", "sr_legacy": "sr_legacy_food"}

# Our column -> FDC nutrient ids, first present wins. Foundation Foods often report energy only
# as Atwater factors (2047/2048) and fat/carbs by alternative methods.
NUTRIENT_IDS: dict[str, tuple[int, ...]] = {
    "kcal": (1008, 2048, 2047),
    "protein_g": (1003,),
    "fat_g": (1004, 1085),
    "carbs_g": (1005, 1050),
    "fiber_g": (1079,),
    "sugars_g": (2000, 1063),
    "sat_fat_g": (1258,),
    "sodium_mg": (1093,),
}
_WANTED = {nid for ids in NUTRIENT_IDS.values() for nid in ids}
_UNDETERMINED_UNIT = "undetermined"
_BATCH = 1000


@dataclass(frozen=True, slots=True)
class PortionRecord:
    amount: float
    unit: str
    qualifier: str | None
    grams: float


@dataclass(slots=True)
class FoodRecord:
    id: int
    description: str
    data_type: str
    category: str | None
    nutrients: dict[str, float | None] = field(default_factory=dict[str, float | None])
    portions: list[PortionRecord] = field(default_factory=list[PortionRecord])


# --- download ---------------------------------------------------------------------------------


async def download(dataset: str, cache_dir: Path, client: httpx.AsyncClient) -> Path:
    """Fetch a dataset zip into `cache_dir` unless already there."""
    filename = DATASETS[dataset]
    path = cache_dir / filename
    if path.exists():
        return path
    cache_dir.mkdir(parents=True, exist_ok=True)
    logger.info("downloading %s", filename)
    tmp = path.with_suffix(".part")
    async with client.stream("GET", BASE_URL + filename, follow_redirects=True) as response:
        response.raise_for_status()
        with tmp.open("wb") as f:
            async for chunk in response.aiter_bytes():
                f.write(chunk)
    tmp.rename(path)
    return path


# --- parse ------------------------------------------------------------------------------------


def read_dataset(zip_path: Path, dataset: str) -> list[FoodRecord]:
    """Parse one FDC CSV zip into food records with macros per 100 g and portion weights."""
    with zipfile.ZipFile(zip_path) as zf:

        def rows(name: str) -> Iterator[dict[str, str]]:
            member = next(n for n in zf.namelist() if n.rsplit("/", 1)[-1] == f"{name}.csv")
            with zf.open(member) as raw:
                yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8"))

        categories = {r["id"]: r["description"] for r in rows("food_category")}
        units = {r["id"]: r["name"] for r in rows("measure_unit")}
        wanted_type = _FDC_DATA_TYPE[dataset]
        foods: dict[int, FoodRecord] = {}
        for r in rows("food"):
            if r["data_type"] != wanted_type:
                continue
            fdc_id = int(r["fdc_id"])
            foods[fdc_id] = FoodRecord(
                id=fdc_id,
                description=r["description"].strip(),
                data_type=dataset,
                category=categories.get(r["food_category_id"]),
            )

        amounts: dict[int, dict[int, float]] = defaultdict(dict)
        for r in rows("food_nutrient"):
            if not (r["fdc_id"] and r["nutrient_id"] and r["amount"]):
                continue
            fdc_id, nutrient_id = int(r["fdc_id"]), int(r["nutrient_id"])
            if fdc_id in foods and nutrient_id in _WANTED:
                amounts[fdc_id][nutrient_id] = float(r["amount"])

        for r in rows("food_portion"):
            fdc_id = int(r["fdc_id"] or 0)
            if fdc_id not in foods or not r["gram_weight"]:
                continue
            portion = parse_portion(r, units.get(r["measure_unit_id"], _UNDETERMINED_UNIT))
            if portion is not None:
                foods[fdc_id].portions.append(portion)

    for fdc_id, food in foods.items():
        food.nutrients = pick_nutrients(amounts.get(fdc_id, {}))
    return list(foods.values())


def pick_nutrients(by_id: dict[int, float]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for column, ids in NUTRIENT_IDS.items():
        out[column] = next((by_id[i] for i in ids if i in by_id), None)
    p, f, c = out["protein_g"], out["fat_g"], out["carbs_g"]
    if out["kcal"] is None and p is not None and f is not None and c is not None:
        out["kcal"] = 4 * p + 9 * f + 4 * c  # Atwater general factors
    return out


def parse_portion(row: dict[str, str], unit_name: str) -> PortionRecord | None:
    """FDC portion row -> (amount, unit, qualifier, grams).

    SR Legacy puts the unit in `modifier` ("cup, chopped", "large", "clove"); Foundation uses
    `measure_unit_id` plus optional description.
    """
    grams = float(row["gram_weight"])
    amount = float(row["amount"] or 1) or 1.0
    if grams <= 0:
        return None
    if unit_name != _UNDETERMINED_UNIT:
        text = " ".join(
            t for t in (unit_name, row["portion_description"], row["modifier"]) if t
        ).strip()
    else:
        text = (row["modifier"] or row["portion_description"]).strip()
    unit, qualifier = portion_unit(text)
    return PortionRecord(amount=amount, unit=unit, qualifier=qualifier, grams=grams)


def portion_unit(text: str) -> tuple[str, str | None]:
    """'cup, chopped' -> ('cup', 'chopped'); 'medium (2-1/2" dia)' -> ('medium', '(2-1/2" dia)')."""
    s = text.strip().lower()
    match = re.match(r"(fl oz|fluid ounce|extra large|[a-z]+)[\s,]*(.*)$", s)
    if not match:
        return (s or "serving"), None
    head, rest = match.group(1), match.group(2).strip() or None
    if head in ("fl oz", "fluid ounce"):
        return "fl_oz", rest
    if head == "extra large":
        return "large", "extra large" + (f" {rest}" if rest else "")
    if head in SIZES:
        return head, rest
    unit = canonical_unit(head)
    return (unit or head), rest


# --- load -------------------------------------------------------------------------------------


async def load_foods(session: AsyncSession, records: Iterable[FoodRecord]) -> int:
    """Upsert foods and replace their portions. Returns the number of foods written."""
    records = list(records)
    for batch in _chunks(records, _BATCH):
        stmt = insert(Food).values(
            [
                {
                    "id": r.id,
                    "description": r.description,
                    "data_type": r.data_type,
                    "category": r.category,
                    **r.nutrients,
                }
                for r in batch
            ]
        )
        excluded = stmt.excluded
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Food.id],
                set_={
                    c: getattr(excluded, c)
                    for c in ("description", "data_type", "category", *NUTRIENT_IDS)
                },
            )
        )
        await session.execute(
            delete(FoodPortion).where(FoodPortion.food_id.in_([r.id for r in batch]))
        )
        portions = [
            {
                "food_id": r.id,
                "amount": p.amount,
                "unit": p.unit,
                "qualifier": p.qualifier,
                "grams": p.grams,
            }
            for r in batch
            for p in r.portions
        ]
        for portion_batch in _chunks(portions, _BATCH):
            await session.execute(insert(FoodPortion).values(portion_batch))
    await session.commit()
    return len(records)


async def count_foods(session: AsyncSession) -> int:
    return await session.scalar(select(func.count(Food.id))) or 0


def _chunks[T](items: list[T], size: int) -> Iterator[list[T]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]

"""UK composition data: McCance and Widdowson's The Composition of Foods Integrated Dataset 2021
(CoFID), ~2,900 foods as eaten in the UK and Ireland ("Bacon rashers, back, dry-fried",
"Potato crisps", "Milk, semi-skimmed, pasteurised, average").

Contains public sector information licensed under the Open Government Licence v3.0.
https://www.gov.uk/government/publications/composition-of-foods-integrated-dataset-cofid

One xlsx with a sheet per nutrient table; row 1 holds headers, row 2 short nutrient codes, data
from row 4. Values are per 100 g of food: "Tr" (trace) is 0, "N" (present, not measured) and
blanks are unknown. Food groups map to USDA categories (larder_core.categories); an unmapped
group stops the import. No household portions (grams only).
"""

import logging
from pathlib import Path
from typing import Any

import httpx
import openpyxl

from larder_core.categories import cofid_category
from larder_data.local_foods import LocalFood

__all__ = ["FILENAME", "URL", "download", "read_cofid"]

logger = logging.getLogger(__name__)

FILENAME = "McCance_Widdowsons_Composition_of_Foods_Integrated_Dataset_2021.xlsx"
URL = (
    "https://assets.publishing.service.gov.uk/media/60538b91e90e07527df82ae4/"
    "McCance_Widdowsons_Composition_of_Foods_Integrated_Dataset_2021..xlsx"
)
SOURCE = "cofid"

# Our column -> CoFID codes on the "Proximates" sheet, first present wins. AOAC fibre matches
# USDA's total dietary fibre; Englyst NSP (lower) only when AOAC is missing.
PROXIMATES: dict[str, tuple[str, ...]] = {
    "kcal": ("KCALS",),
    "protein_g": ("PROT",),
    "fat_g": ("FAT",),
    "carbs_g": ("CHO",),
    "fiber_g": ("AOACFIB", "ENGFIB"),
    "sugars_g": ("TOTSUG",),
    "sat_fat_g": ("SATFOD",),
}
INORGANICS: dict[str, tuple[str, ...]] = {
    "sodium_mg": ("NA",),
    "iron_mg": ("FE",),
    "calcium_mg": ("CA",),
    "potassium_mg": ("K",),
}
# CoFID's folate is total folate (USDA gives dietary folate equivalents where it can; they
# differ only for fortified foods).
VITAMINS: dict[str, tuple[str, ...]] = {
    "vitamin_c_mg": ("VITC",),
    "vitamin_d_ug": ("VITD",),
    "folate_ug": ("FOLT",),
    "vitamin_b12_ug": ("VITB12",),
}


async def download(cache_dir: Path, client: httpx.AsyncClient) -> Path:
    path = cache_dir / FILENAME
    if path.exists():
        return path
    cache_dir.mkdir(parents=True, exist_ok=True)
    logger.info("downloading %s", FILENAME)
    tmp = path.with_suffix(".part")
    async with client.stream("GET", URL, follow_redirects=True) as response:
        response.raise_for_status()
        with tmp.open("wb") as f:
            async for chunk in response.aiter_bytes():
                f.write(chunk)
    tmp.rename(path)
    return path


def read_cofid(path: Path) -> list[LocalFood]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        proximates = _sheet(wb, "Proximates")
        inorganics = _sheet(wb, "Inorganics")
        vitamins = _sheet(wb, "Vitamins")
    finally:
        wb.close()
    foods: list[LocalFood] = []
    for code, row in proximates.items():
        nutrients = {col: _first(row, codes) for col, codes in PROXIMATES.items()}
        nutrients |= {
            col: _first(inorganics.get(code, {}), codes) for col, codes in INORGANICS.items()
        }
        nutrients |= {col: _first(vitamins.get(code, {}), codes) for col, codes in VITAMINS.items()}
        name, group = str(row["Food Name"]).strip(), str(row["Group"]).strip()
        foods.append(
            LocalFood(
                source=SOURCE,
                source_id=code,
                description=name,
                data_type="cofid",
                category=cofid_category(group),
                source_category=group,
                nutrients=nutrients,
            )
        )
    return foods


def _sheet(wb: Any, suffix: str) -> dict[str, dict[str, Any]]:
    """Rows keyed by food code, cells keyed by nutrient code (row 2) or header (row 1)."""
    ws = next(ws for ws in wb.worksheets if ws.title.endswith(suffix))
    rows = ws.iter_rows(values_only=True)
    headers = [str(h).strip() if h is not None else "" for h in next(rows)]
    codes = [str(c).strip() if c is not None else "" for c in next(rows)]
    keys = [code or header for header, code in zip(headers, codes, strict=True)]
    keys[0] = "Food Code"  # the Inorganics sheet leaves this header blank
    out: dict[str, dict[str, Any]] = {}
    for values in rows:
        row = dict(zip(keys, values, strict=False))
        code = row.get("Food Code")
        if code and row.get("Food Name"):
            out[str(code).strip()] = row
    return out


def _first(row: dict[str, Any], codes: tuple[str, ...]) -> float | None:
    for code in codes:
        value = _value(row.get(code))
        if value is not None:
            return value
    return None


def _value(cell: Any) -> float | None:
    if cell is None:
        return None
    text = str(cell).strip()
    if text.casefold() in ("tr", "trace"):
        return 0.0
    try:
        return float(text)
    except ValueError:
        return None  # "N", "", footnote markers

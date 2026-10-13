"""Open Food Facts bulk import: packaged products sold in the chosen countries (default Ireland
and the UK) from the nightly CSV export (~1.3 GB gzipped, tab-separated), streamed with the
standard library. Only products with a name and plausible energy are kept (larder_core.off).

Data: (c) Open Food Facts contributors, under the Open Database License (ODbL). We store no
images. Products no longer in the export (for those countries) are marked retired, never
deleted, because pantry items and receipts may point at them.

Products are matched to the generic food they count as later (link-generics); the category
table gives many of them one at import.
"""

import csv
import gzip
import logging
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import String, any_, bindparam, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from larder_core.categories import off_category
from larder_core.off import OffProduct, country_tags, parse_product
from larder_data.local_foods import LocalFood, load_local_foods
from larder_data.usda import PortionRecord
from larder_db.models import Food

__all__ = ["FILENAME", "URL", "download", "import_products", "iter_products", "local_food"]

logger = logging.getLogger(__name__)

FILENAME = "en.openfoodfacts.org.products.csv.gz"
URL = "https://static.openfoodfacts.org/data/" + FILENAME
SOURCE = "off"
DEFAULT_COUNTRIES = ("IE", "GB")
_BATCH = 2000
_MAX_INGREDIENTS = 4000


async def download(cache_dir: Path, client: httpx.AsyncClient, *, refresh: bool = False) -> Path:
    path = cache_dir / FILENAME
    if path.exists() and not refresh:
        return path
    cache_dir.mkdir(parents=True, exist_ok=True)
    logger.info("downloading %s (about 1.3 GB)", FILENAME)
    tmp = path.with_name(path.name + ".part")
    async with client.stream("GET", URL, follow_redirects=True, timeout=None) as response:
        response.raise_for_status()
        with tmp.open("wb") as f:
            async for chunk in response.aiter_bytes():
                f.write(chunk)
    tmp.replace(path)
    return path


def iter_products(path: Path, countries: Iterable[str]) -> Iterator[OffProduct]:
    """Products sold in `countries` (ISO codes), parsed and checked."""
    wanted = set(countries)
    tags = country_tags(wanted)
    csv.field_size_limit(2**31 - 1)
    with gzip.open(path, "rt", encoding="utf-8", newline="", errors="replace") as f:
        reader = csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE)
        header = next(reader)
        index = {name: i for i, name in enumerate(header)}
        at_countries = index["countries_tags"]
        for values in reader:
            if len(values) <= at_countries:
                continue
            sold = values[at_countries]
            if not any(t in sold for t in tags):
                continue
            row = {name: values[i] for name, i in index.items() if i < len(values)}
            product = parse_product(row, countries=wanted)
            if product is not None and product.countries:
                yield product


def local_food(p: OffProduct, origin: str) -> LocalFood:
    portions = [PortionRecord(1.0, unit, None, grams) for unit, grams in p.portions]
    ingredients = p.ingredients[:_MAX_INGREDIENTS] if p.ingredients else None
    return LocalFood(
        source=SOURCE,
        source_id=p.code,
        description=p.name,
        data_type="branded",
        category=off_category(p.categories),
        source_category=p.categories[-1] if p.categories else None,
        brand=p.brand,
        barcode=p.barcode,
        countries=list(p.countries),
        allergens_declared=sorted(a.value for a in p.allergens) or None,
        traces_declared=sorted(a.value for a in p.traces) or None,
        ingredients_text=ingredients,
        origin=origin,
        nutrients={
            "kcal": p.kcal,
            "protein_g": p.protein_g,
            "fat_g": p.fat_g,
            "carbs_g": p.carbs_g,
            "fiber_g": p.fiber_g,
            "sugars_g": p.sugars_g,
            "sat_fat_g": p.sat_fat_g,
            "sodium_mg": p.sodium_mg,
        },
        portions=portions,
    )


async def import_products(
    session: AsyncSession, products: Iterable[OffProduct], countries: Iterable[str]
) -> int:
    """Upsert products in batches, then retire bulk products (of these countries) that are no
    longer in the export. Returns the number written."""
    started = datetime.now(UTC)
    seen: list[str] = []
    batch: list[LocalFood] = []
    for p in products:
        batch.append(local_food(p, "bulk"))
        if len(batch) >= _BATCH:
            seen += [r.source_id for r in batch]
            await load_local_foods(session, batch)
            logger.info("open food facts: %d products", len(seen))
            batch = []
    if batch:
        seen += [r.source_id for r in batch]
        await load_local_foods(session, batch)
    wanted = sorted({c.upper() for c in countries})
    retired = (
        await session.scalars(
            update(Food)
            .where(
                Food.source == SOURCE,
                Food.origin == "bulk",
                Food.retired_at.is_(None),
                Food.countries.overlap(wanted),
                ~(Food.source_id == any_(bindparam("seen", seen, type_=ARRAY(String)))),
            )
            .values(retired_at=started)
            .returning(Food.id)
        )
    ).all()
    await session.commit()
    logger.info("open food facts: %d written, %d retired", len(seen), len(retired))
    return len(seen)

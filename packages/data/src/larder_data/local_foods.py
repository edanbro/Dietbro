"""Loading foods from sources other than USDA (CoFID, Open Food Facts): they have their own ids
(`source_id`), so rows get ids from `foods_local_id_seq` (1e9 and up). Re-imports keep each
food's id (looked up by source and source_id first), so pantry items and receipts that point at
a food keep pointing at it.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import case, delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from larder_data.usda import NUTRIENT_IDS, PortionRecord
from larder_db.models import Food, FoodPortion

__all__ = ["LocalFood", "load_local_foods"]

_BATCH = 1000


@dataclass(slots=True)
class LocalFood:
    source: str  # cofid | off
    source_id: str
    description: str
    data_type: str  # cofid | branded
    category: str | None  # a USDA category name (mapped)
    source_category: str | None = None
    brand: str | None = None
    barcode: str | None = None
    countries: list[str] | None = None
    allergens_declared: list[str] | None = None
    traces_declared: list[str] | None = None
    ingredients_text: str | None = None
    origin: str | None = None
    generic_food_id: int | None = None
    generic_method: str | None = None
    nutrients: dict[str, float | None] = field(default_factory=dict[str, float | None])
    portions: list[PortionRecord] = field(default_factory=list[PortionRecord])


async def load_local_foods(session: AsyncSession, records: Sequence[LocalFood]) -> list[int]:
    """Upsert by (source, source_id), replacing portions; returns the ids written, in order.
    A barcode already used by another row is dropped from the newcomer (OFF has duplicates
    like 036000291452 / 0036000291452). Seen rows are un-retired."""
    ids: list[int] = []
    for batch in _chunks(list(records), _BATCH):
        ids += await _load_batch(session, batch)
    await session.commit()
    return ids


async def _load_batch(session: AsyncSession, batch: list[LocalFood]) -> list[int]:
    source = {r.source for r in batch}
    assert len(source) == 1, "one source per batch"
    found = await session.execute(
        select(Food.source_id, Food.id).where(
            Food.source == batch[0].source,
            Food.source_id.in_([r.source_id for r in batch]),
        )
    )
    existing: dict[str, int] = {sid: fid for sid, fid in found.all() if sid is not None}
    fresh = [r.source_id for r in batch if r.source_id not in existing]
    if fresh:
        new_ids = (
            await session.scalars(
                text("SELECT nextval('foods_local_id_seq') FROM generate_series(1, :n)"),
                {"n": len(fresh)},
            )
        ).all()
        existing.update(zip(fresh, new_ids, strict=True))

    barcodes = [r.barcode for r in batch if r.barcode]
    used = await session.execute(select(Food.barcode, Food.id).where(Food.barcode.in_(barcodes)))
    taken: dict[str, int] = {code: fid for code, fid in used.all() if code is not None}
    seen_barcodes: set[str] = set()
    rows: list[dict[str, Any]] = []
    for r in batch:
        fid = existing[r.source_id]
        barcode = r.barcode
        if barcode and (taken.get(barcode, fid) != fid or barcode in seen_barcodes):
            barcode = None
        if barcode:
            seen_barcodes.add(barcode)
        rows.append(
            {
                "id": fid,
                "source": r.source,
                "source_id": r.source_id,
                "description": r.description,
                "data_type": r.data_type,
                "category": r.category,
                "source_category": r.source_category,
                "brand": r.brand,
                "barcode": barcode,
                "countries": r.countries,
                "allergens_declared": r.allergens_declared,
                "traces_declared": r.traces_declared,
                "ingredients_text": r.ingredients_text,
                "origin": r.origin,
                "generic_food_id": r.generic_food_id,
                "generic_method": r.generic_method,
                "retired_at": None,
                **{k: r.nutrients.get(k) for k in NUTRIENT_IDS},
            }
        )
    stmt = insert(Food).values(rows)
    keep_link = Food.generic_food_id.is_not(None) & stmt.excluded.generic_food_id.is_(None)
    update_cols: dict[str, Any] = {
        c: getattr(stmt.excluded, c) for c in rows[0] if c not in ("id", "source")
    }
    # A link made later (link-generics) survives a re-import that has none.
    update_cols["generic_food_id"] = case(
        (keep_link, Food.generic_food_id), else_=stmt.excluded.generic_food_id
    )
    update_cols["generic_method"] = case(
        (keep_link, Food.generic_method), else_=stmt.excluded.generic_method
    )
    await session.execute(stmt.on_conflict_do_update(index_elements=[Food.id], set_=update_cols))
    written: list[int] = [row["id"] for row in rows]
    await session.execute(delete(FoodPortion).where(FoodPortion.food_id.in_(written)))
    portions: list[dict[str, Any]] = [
        {
            "food_id": row["id"],
            "amount": p.amount,
            "unit": p.unit,
            "qualifier": p.qualifier,
            "grams": p.grams,
        }
        for row, r in zip(rows, batch, strict=True)
        for p in r.portions
    ]
    for chunk in _chunks(portions, _BATCH):
        await session.execute(insert(FoodPortion).values(chunk))
    return written


def _chunks[T](items: list[T], size: int) -> Iterator[list[T]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]

"""Reviewed tags of real foods, so a rule change can't silently change real data.

`data/food_tags_snapshot.csv` holds `tag_food` output for every USDA food used by a plannable
(nutrition_complete) recipe in the seeded catalog, plus every food a curated alias points to. It
was reviewed by hand; wrong tags were fixed with rules or `food_tags.csv` rows.

- Without a database (CI) the snapshot is re-tagged and must not change.
- With the seeded catalog (`$CATALOG_DATABASE_URL`, default `$DATABASE_URL` or the compose
  `larder` database) the snapshot is regenerated from the catalog and must not change either, and
  every plannable recipe must have all its lines resolved (exact alias or reviewed line_tags.csv).
  These tests skip when the catalog isn't seeded (CI's database is empty). With
  LARDER_REQUIRE_DB=1 an unreachable server fails instead of skipping.

After a reviewed change (new rules, new aliases, a re-resolve), regenerate with:

    LARDER_UPDATE_SNAPSHOT=1 uv run pytest packages/core/tests/test_tagging_snapshot.py

and review the diff of food_tags_snapshot.csv before committing it.
"""

import asyncio
import csv
import os
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from larder_core.aliases import load_alias_rows
from larder_core.names import normalise_name
from larder_core.prices import load_prices
from larder_core.tagging import format_tags, load_line_tags, make_line, recipe_tags, tag_food
from larder_db.engine import database_url, make_engine

SNAPSHOT = Path(__file__).parent / "data" / "food_tags_snapshot.csv"
FIELDS: list[str] = ["fdc_id", "description", "category", "allergens", "animal"]
UPDATE = os.environ.get("LARDER_UPDATE_SNAPSHOT") == "1"
HOW = (
    "Review each change (fix wrong tags with rules or data/food_tags.csv), then regenerate with "
    "`LARDER_UPDATE_SNAPSHOT=1 uv run pytest packages/core/tests/test_tagging_snapshot.py` "
    "and commit the reviewed food_tags_snapshot.csv."
)

type Row = dict[str, str]


def snapshot_row(fdc_id: int, description: str, category: str | None) -> Row:
    tags = tag_food(fdc_id, description, category)
    return {
        "fdc_id": str(fdc_id),
        "description": description,
        "category": category or "",
        "allergens": format_tags(tags.allergens),
        "animal": format_tags(tags.animal),
    }


def read_snapshot() -> list[Row]:
    with SNAPSHOT.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_snapshot(rows: list[Row]) -> None:
    with SNAPSHOT.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: int(r["fdc_id"])))


def diff(old: list[Row], new: list[Row]) -> list[str]:
    before = {r["fdc_id"]: r for r in old}
    after = {r["fdc_id"]: r for r in new}
    out = [f"new food {k}: {_show(after[k])}" for k in sorted(after.keys() - before.keys())]
    out += [f"no longer used {k}: {_show(before[k])}" for k in sorted(before.keys() - after.keys())]
    out += [
        f"changed {k}: {_show(before[k])} -> {_show(after[k])}"
        for k in sorted(before.keys() & after.keys())
        if before[k] != after[k]
    ]
    return out


def _show(row: Row) -> str:
    return f"{row['description']!r} [{row['category']}] {row['allergens']} / {row['animal']}"


def test_snapshot_matches_the_rules() -> None:
    old = read_snapshot()
    assert len(old) >= 450
    new = [snapshot_row(int(r["fdc_id"]), r["description"], r["category"] or None) for r in old]
    changes = diff(old, new)
    if changes and UPDATE:
        write_snapshot(new)
        return
    assert changes == [], f"tag rules changed reviewed foods. {HOW}"


# --- against the seeded catalog --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Catalog:
    foods: list[tuple[int, str, str | None]]  # used by plannable recipes or by an alias
    categories: set[str]
    missing_alias_foods: set[int]
    recipes: dict[int, tuple[str, str | None, str]]  # plannable: name, category, instructions
    lines: list[tuple[int, str, int | None, str | None, str | None, str | None]]


_FOODS = """
    SELECT DISTINCT f.id, f.description, f.category FROM foods f
    WHERE f.id = ANY(:aliases) OR f.id IN (
        SELECT ri.food_id FROM recipe_ingredients ri JOIN recipes r ON r.id = ri.recipe_id
        WHERE r.nutrition_complete)
"""
_LINES = """
    SELECT ri.recipe_id, ri.raw_name, ri.food_id, f.description, f.category, ri.match_method
    FROM recipe_ingredients ri JOIN recipes r ON r.id = ri.recipe_id
    LEFT JOIN foods f ON f.id = ri.food_id
    WHERE r.nutrition_complete ORDER BY ri.recipe_id, ri.position
"""


async def _load(url: str) -> Catalog:
    aliases = sorted({a.fdc_id for a in load_alias_rows()})
    engine = make_engine(url, connect_args={"timeout": 3})
    try:
        async with engine.connect() as conn:
            foods = [
                (int(i), str(d), c)
                for i, d, c in await conn.execute(text(_FOODS), {"aliases": aliases})
            ]
            categories = {
                str(c)
                for (c,) in await conn.execute(text("SELECT DISTINCT category FROM foods"))
                if c is not None
            }
            recipes = {
                int(i): (str(n), c, str(t))
                for i, n, c, t in await conn.execute(
                    text(
                        "SELECT id, name, category, instructions FROM recipes "
                        "WHERE nutrition_complete"
                    )
                )
            }
            lines = [
                (int(rid), str(raw), fid, desc, cat, method)
                for rid, raw, fid, desc, cat, method in await conn.execute(text(_LINES))
            ]
    finally:
        await engine.dispose()
    found = {i for i, _, _ in foods}
    return Catalog(foods, categories, set(aliases) - found, recipes, lines)


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    url = os.environ.get("CATALOG_DATABASE_URL") or database_url()
    try:
        loaded = asyncio.run(_load(url))
    except (OSError, TimeoutError, DBAPIError) as exc:
        if "does not exist" in str(exc):
            pytest.skip(f"catalog database not found ({url}); seed it with `make data`")
        if os.environ.get("LARDER_REQUIRE_DB") == "1":
            raise
        pytest.skip(f"Postgres not reachable ({exc}); run `docker compose up -d db`")
    if not loaded.recipes:
        pytest.skip("catalog has no plannable recipes; seed and resolve it with `make data`")
    return loaded


def test_snapshot_matches_the_catalog(catalog: Catalog) -> None:
    new = [snapshot_row(i, d, c) for i, d, c in catalog.foods]
    changes = diff(read_snapshot(), new)
    if changes and UPDATE:
        write_snapshot(new)
        return
    assert changes == [], f"the catalog's foods changed. {HOW}"


def test_every_plannable_recipe_is_fully_resolved(catalog: Catalog) -> None:
    # Every approximate or automatic match used by a plannable recipe has been reviewed.
    by_recipe: dict[int, list[tuple[str, int | None, str | None, str | None]]] = {}
    for rid, raw, fid, desc, cat, _ in catalog.lines:
        by_recipe.setdefault(rid, []).append((raw, fid, desc, cat))
    unresolved: list[str] = []
    for rid, (name, category, instructions) in catalog.recipes.items():
        lines = [
            make_line(raw, fid, tag_food(fid, desc or "", cat) if fid is not None else None)
            for raw, fid, desc, cat in by_recipe.get(rid, [])
        ]
        if recipe_tags(name, category, instructions, lines).unresolved:
            unresolved.append(name)
    assert unresolved == [], "add reviewed rows for their lines to data/line_tags.csv"


def test_line_tags_cover_every_automatic_match(catalog: Catalog) -> None:
    automatic = {normalise_name(raw) for _, raw, _, _, _, m in catalog.lines if m == "embedding"}
    assert automatic - load_line_tags().keys() == set()


def test_aliases_point_at_catalog_foods(catalog: Catalog) -> None:
    assert catalog.missing_alias_foods == set()


def test_every_catalog_category_has_a_price(catalog: Catalog) -> None:
    assert catalog.categories - load_prices().category.keys() == set()

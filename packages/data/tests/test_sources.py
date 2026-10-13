"""Survey foods (FNDDS), CoFID and Open Food Facts readers, and loading foods from sources
other than USDA."""

import gzip
from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from larder_core.categories import UnmappedCategory, off_generic, off_generic_ids
from larder_core.generic_links import (
    Facts,
    category_generic,
    name_endings,
    name_forms,
    plausible,
)
from larder_data import cofid, off
from larder_data.fndds import parse_survey_portion
from larder_data.local_foods import LocalFood, load_local_foods
from larder_db.models import LOCAL_ID_START, Food, FoodPortion


def portion(description: str, grams: str = "100", modifier: str = "10205") -> dict[str, str]:
    return {"portion_description": description, "gram_weight": grams, "modifier": modifier}


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (portion("1 cup", "244"), (1.0, "cup", None, 244.0)),
        (portion('1 slice (1/8 of 14" pizza)', "107"), (1.0, "slice", '(1/8 of 14" pizza)', 107.0)),
        (portion("1/2 cup", "120"), (0.5, "cup", None, 120.0)),
        (portion("1 1/2 cups", "360"), (1.5, "cup", None, 360.0)),
    ],
)
def test_survey_portions_ignore_the_numeric_modifier(
    row: dict[str, str], expected: tuple[float, str, str | None, float]
) -> None:
    p = parse_survey_portion(row)
    assert p is not None
    assert (p.amount, p.unit, p.qualifier, p.grams) == expected


@pytest.mark.parametrize(
    "row",
    [
        portion("Quantity not specified", "245"),
        portion("Guideline amount per cup of hot cereal", "61"),
        portion("1 individual school container", "244"),
        portion("1 cup", "0"),
    ],
)
def test_survey_portions_skip_non_household_ones(row: dict[str, str]) -> None:
    assert parse_survey_portion(row) is None


def _workbook(path: Path, groups: tuple[str, ...] = ("OA", "MAA")) -> Path:
    wb = openpyxl.Workbook()
    info = ["Food Code", "Food Name", "Description", "Group", "Previous", "Refs", "Footnote"]
    prox = wb.active
    assert prox is not None
    prox.title = "1.3 Proximates"
    prox.append(
        [
            *info,
            "Protein (g)",
            "Fat (g)",
            "Carbohydrate (g)",
            "Energy (kcal) (kcal)",
            "Total sugars (g)",
            "AOAC fibre (g)",
            "NSP (g)",
            "Satd FA /100g food (g)",
        ]
    )
    prox.append(
        [None] * 7 + ["PROT", "FAT", "CHO", "KCALS", "TOTSUG", "AOACFIB", "ENGFIB", "SATFOD"]
    )
    prox.append([None] * 15)
    prox.append(
        [
            "17-001",
            "Butter, salted",
            "",
            groups[0],
            1,
            "",
            None,
            "0.6",
            "82.2",
            "0.6",
            "744",
            "0.6",
            "N",
            "Tr",
            "52.1",
        ]
    )
    prox.append(
        [
            "19-498",
            "Bacon rashers, back, raw",
            "",
            groups[1],
            2,
            "",
            None,
            "16.5",
            "16.5",
            "0",
            "215",
            "0",
            None,
            "0",
            "6.0",
        ]
    )
    inorg = wb.create_sheet("1.4 Inorganics")
    inorg.append(
        [" ", "Food Name", "Description", "Group", "Previous", "Refs", "Footnote", "Sodium (mg)"]
    )
    inorg.append([None] * 7 + ["NA"])
    inorg.append([None] * 8)
    inorg.append(["17-001", "Butter, salted", "", groups[0], 1, "", None, "750"])
    out = path / "cofid.xlsx"
    wb.save(out)
    return out


def test_cofid_reader(tmp_path: Path) -> None:
    butter, bacon = cofid.read_cofid(_workbook(tmp_path))

    assert (butter.source, butter.source_id, butter.category) == (
        "cofid",
        "17-001",
        "Dairy and Egg Products",  # butters are dairy: they keep the milk tag
    )
    assert butter.nutrients["kcal"] == 744
    assert butter.nutrients["fiber_g"] == 0  # AOAC unknown ("N"), NSP a trace ("Tr")
    assert butter.nutrients["sodium_mg"] == 750
    assert bacon.category == "Pork Products"  # MAA before M (meat dishes)
    assert bacon.nutrients["sodium_mg"] is None  # not on the inorganics sheet


def test_cofid_unknown_group_stops_the_import(tmp_path: Path) -> None:
    with pytest.raises(UnmappedCategory):
        cofid.read_cofid(_workbook(tmp_path, groups=("OA", "ZZ")))


def _export(path: Path, rows: list[dict[str, str]]) -> Path:
    header = [
        "code",
        "product_name",
        "brands",
        "countries_tags",
        "categories_tags",
        "allergens",
        "traces_tags",
        "ingredients_text",
        "energy-kcal_100g",
        "proteins_100g",
        "fat_100g",
        "salt_100g",
        "product_quantity",
        "serving_quantity",
    ]
    out = path / off.FILENAME
    with gzip.open(out, "wt", encoding="utf-8", newline="") as f:
        f.write("\t".join(header) + "\n")
        for row in rows:
            f.write("\t".join(row.get(h, "") for h in header) + "\n")
    return out


PRODUCT = {
    "code": "4006381333931",
    "product_name": "Pure Irish Butter",
    "brands": "Kerrygold",
    "countries_tags": "en:ireland,en:germany",
    "categories_tags": "en:dairies,en:butters",
    "allergens": "en:milk",
    "energy-kcal_100g": "740",
    "fat_100g": "82",
    "salt_100g": "1.5",
    "product_quantity": "227",
}


def test_off_export_keeps_products_sold_in_the_countries(tmp_path: Path) -> None:
    path = _export(
        tmp_path,
        [
            PRODUCT,
            PRODUCT | {"code": "3000000000001", "countries_tags": "en:france"},
            PRODUCT | {"code": "4000000000002", "product_name": ""},  # no name
        ],
    )

    products = list(off.iter_products(path, ["IE", "GB"]))

    assert [p.code for p in products] == ["4006381333931"]
    food = off.local_food(products[0], "bulk")
    assert (food.category, food.countries, food.allergens_declared) == (
        "Dairy and Egg Products",
        ["IE"],
        ["milk"],
    )
    assert [(p.unit, p.grams) for p in food.portions] == [("packet", 227.0)]


async def test_local_foods_keep_their_ids_on_reimport(db_session: AsyncSession) -> None:
    first = LocalFood("cofid", "17-001", "Butter, salted", "cofid", "Dairy and Egg Products")
    ids = await load_local_foods(db_session, [first])
    again = await load_local_foods(
        db_session, [LocalFood("cofid", "17-001", "Butter, salted (new)", "cofid", None)]
    )

    assert ids == again
    assert ids[0] >= LOCAL_ID_START
    food = await db_session.get(Food, ids[0])
    assert food is not None
    await db_session.refresh(food)
    assert food.description == "Butter, salted (new)"


async def test_a_barcode_is_kept_by_its_first_product(db_session: AsyncSession) -> None:
    a = LocalFood("off", "036000291452", "A", "branded", None, barcode="0036000291452")
    b = LocalFood("off", "0036000291452", "B", "branded", None, barcode="0036000291452")
    ids = await load_local_foods(db_session, [a, b])

    rows = (await db_session.execute(select(Food.id, Food.barcode).order_by(Food.id))).all()
    assert [(i, code) for i, code in rows if i in ids] == [
        (ids[0], "0036000291452"),
        (ids[1], None),
    ]


async def test_products_retire_when_gone_from_the_export(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    gone = PRODUCT | {"code": "5000159407236", "product_name": "Old crisps"}
    await off.import_products(
        db_session, off.iter_products(_export(tmp_path, [PRODUCT, gone]), ["IE"]), ["IE"]
    )
    await off.import_products(
        db_session, off.iter_products(_export(tmp_path, [PRODUCT]), ["IE"]), ["IE"]
    )

    rows = (
        await db_session.execute(
            select(Food.source_id, Food.retired_at.is_not(None)).where(Food.source == "off")
        )
    ).all()
    assert sorted(rows) == [("4006381333931", False), ("5000159407236", True)]
    portions = await db_session.scalars(select(FoodPortion.unit))
    assert set(portions) == {"packet"}


def test_name_forms_turn_cofid_names_round() -> None:
    assert name_forms("Milk, semi-skimmed, pasteurised, average")[:2] == [
        "milk semi-skimmed pasteurised average",
        "semi-skimmed milk",
    ]
    assert "black pudding" in name_forms("Black pudding, raw")
    assert "milk" not in name_forms("Milk, skimmed")  # a kind, not how it's sold
    assert name_endings("pure irish butter") == ["irish butter", "butter"]


def test_plausibility() -> None:
    bacon_uk, bacon_us = (
        Facts("Pork Products", 215, 16.5, 16.5),
        Facts("Pork Products", 417, 13, 40),
    )
    assert plausible(bacon_uk, bacon_us, reviewed=True)  # leaner, still bacon
    assert not plausible(bacon_uk, bacon_us, reviewed=False)
    almond = Facts("Beverages", 15, 0.5, 1.1)
    milk = Facts("Dairy and Egg Products", 61, 3.2, 3.3)
    assert not plausible(almond, milk, reviewed=True, same_category=True)


BUTTER = 173410
BUTTER_FACTS = Facts("Dairy and Egg Products", 717, 0.9, 81)


def test_off_category_generics() -> None:
    assert off_generic(["en:dairies", "en:butters", "en:salted-butters"]) == BUTTER
    assert off_generic(["en:dairies", "en:milks", "en:whole-milks"]) == 171265  # most specific
    assert off_generic(["en:snacks"]) is None
    assert BUTTER in off_generic_ids()


def test_category_links_need_a_plausible_generic() -> None:
    butters = ["en:dairies", "en:butters"]
    generics = {BUTTER: BUTTER_FACTS}
    butter = Facts("Dairy and Egg Products", 740, 0.5, 82)
    spread = Facts("Fats and Oils", 540, 0.2, 59)  # a spread filed under butters
    light = Facts("Dairy and Egg Products", 300, 1, 33)  # too far from butter's energy

    assert category_generic(butters, butter, generics) == BUTTER
    assert category_generic(butters, spread, generics) is None
    assert category_generic(butters, light, generics) is None
    assert category_generic(butters, butter, {}) is None  # generic not in the database


def test_off_products_link_by_category_at_import(tmp_path: Path) -> None:
    (product,) = off.iter_products(_export(tmp_path, [PRODUCT]), ["IE"])

    linked = off.local_food(product, "bulk", {BUTTER: BUTTER_FACTS})
    unlinked = off.local_food(product, "bulk")

    assert (linked.generic_food_id, linked.generic_method) == (BUTTER, "category")
    assert (unlinked.generic_food_id, unlinked.generic_method) == (None, None)


async def test_import_loads_the_category_generics(db_session: AsyncSession, tmp_path: Path) -> None:
    db_session.add(
        Food(
            id=BUTTER,
            description="Butter, salted",
            data_type="sr_legacy",
            category="Dairy and Egg Products",
            kcal=717,
            protein_g=0.9,
            fat_g=81,
        )
    )
    await db_session.commit()

    await off.import_products(
        db_session, off.iter_products(_export(tmp_path, [PRODUCT]), ["IE"]), ["IE"]
    )

    row = (
        await db_session.execute(
            select(Food.generic_food_id, Food.generic_method).where(Food.source == "off")
        )
    ).one()
    assert tuple(row) == (BUTTER, "category")

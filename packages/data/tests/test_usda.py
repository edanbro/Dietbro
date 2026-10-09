from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from larder_data import usda
from larder_db.models import Food


def test_read_dataset_keeps_only_the_dataset_type(fdc_zip: Path) -> None:
    foods = {f.id: f for f in usda.read_dataset(fdc_zip, "sr_legacy")}

    assert set(foods) == {170000, 171413}
    onion = foods[170000]
    assert onion.description == "Onions, raw"
    assert onion.category == "Vegetables and Vegetable Products"
    assert onion.nutrients["kcal"] == 40
    assert onion.nutrients["sodium_mg"] == 4
    assert onion.nutrients["fiber_g"] is None


def test_read_dataset_parses_portions(fdc_zip: Path) -> None:
    foods = {f.id: f for f in usda.read_dataset(fdc_zip, "sr_legacy")}

    onion = {(p.unit, p.qualifier): p.grams for p in foods[170000].portions}
    assert onion == {("cup", "chopped"): 160, ("medium", '(2-1/2" dia)'): 110, ("large", None): 150}
    # Foundation-style measure_unit_id; the empty gram_weight row is dropped.
    oil = [(p.unit, p.grams) for p in foods[171413].portions]
    assert oil == [("tbsp", 13.5)]


def test_missing_energy_falls_back_to_atwater(fdc_zip: Path) -> None:
    oil = next(f for f in usda.read_dataset(fdc_zip, "sr_legacy") if f.id == 171413)

    assert oil.nutrients["kcal"] == 900


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("cup, chopped", ("cup", "chopped")),
        ("tbsp chopped", ("tbsp", "chopped")),
        ("clove", ("clove", None)),
        ("cloves", ("clove", None)),
        ("fl oz", ("fl_oz", None)),
        ("extra large", ("large", "extra large")),
        ('fruit (2-1/8" dia)', ("fruit", '(2-1/8" dia)')),
        ("NLEA serving", ("nlea", "serving")),
        ("", ("serving", None)),
    ],
)
def test_portion_unit(text: str, expected: tuple[str, str | None]) -> None:
    assert usda.portion_unit(text) == expected


async def test_download_caches(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=b"zipbytes")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = await usda.download("sr_legacy", tmp_path, client)
        second = await usda.download("sr_legacy", tmp_path, client)

    assert first == second
    assert first.read_bytes() == b"zipbytes"
    assert calls == [usda.BASE_URL + usda.DATASETS["sr_legacy"]]


async def test_load_foods_upserts(db_session: AsyncSession, fdc_zip: Path) -> None:
    records = usda.read_dataset(fdc_zip, "sr_legacy")

    assert await usda.load_foods(db_session, records) == 2
    assert await usda.load_foods(db_session, records) == 2  # idempotent

    foods = (
        await db_session.scalars(
            select(Food).options(selectinload(Food.portions)).order_by(Food.id)
        )
    ).all()
    assert [f.description for f in foods] == ["Onions, raw", "Oil, olive, salad or cooking"]
    assert len(foods[0].portions) == 3
    assert await usda.count_foods(db_session) == 2

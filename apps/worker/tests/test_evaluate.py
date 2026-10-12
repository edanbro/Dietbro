"""The M6 accuracy floor, CI-safe: the labelled receipts through the production pipeline
against a fixture of the foods the matcher can reach (larder-receipt-eval --write-foods), so
the numbers match the seeded database's. Full report: make receipt-eval."""

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from larder_api.foodmatch import FoodMatch
from larder_api.receipts import Suggestion
from larder_core.receipts import Amount, ReceiptItem
from larder_db.engine import make_sessionmaker
from larder_worker.evaluate import (
    Expected,
    Labelled,
    load_foods,
    load_labels,
    run_images,
    run_text,
    score,
    similarity,
    summarize,
)


@pytest.fixture
async def usda(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    maker = make_sessionmaker(db_engine)
    async with maker() as session:
        await load_foods(session)
    return maker


def test_labels_load() -> None:
    receipts = load_labels()

    assert len(receipts) >= 25
    assert sum(len(r.items) for r in receipts) >= 200
    assert sum(r.holdout for r in receipts) >= 5
    assert sum(r.image is not None for r in receipts) >= 10


def test_similarity_tolerates_ocr_noise() -> None:
    assert similarity("SKMD MILK 4PT", "TESCO SEMI SKMD MILK 4PT £1.45") == 1.0
    assert similarity("SKMD MILK 4PT", "TESC0 SEMI SKMD MlLK 4PT £1.45") >= 0.8
    assert similarity("SKMD MILK", "BANANAS 0.68") < 0.5


def test_score_counts_misses_wrong_foods_amounts_and_extra_lines() -> None:
    receipt = Labelled(
        id="r",
        text="",
        items=(
            Expected("MILK", "milk", frozenset({1}), 1000, 0.15, False),
            Expected("EGGS", "egg", frozenset({2}), None, 0.15, False),
            Expected("BREAD", "bread", frozenset({3}), 800, 0.15, False),
            Expected("WATER", "water", frozenset({4}), None, 0.15, True),
            Expected("HAM", "ham", frozenset({5}), None, 0.15, False),
        ),
        image=None,
        holdout=False,
    )

    def s(raw: str, food: int | None, grams: float = 100) -> Suggestion:
        match = None if food is None else FoodMatch(food, f"food {food}", "alias")
        return Suggestion(
            ReceiptItem(raw=raw, name=raw.lower()), match, Amount(grams, "g", grams, False), None
        )

    result = score(
        receipt,
        [
            s("MILK 1L", 1, 1030),
            s("EGGS 6", 9),
            s("BREAD", 3, 400),
            s("WATER", 4),
            s("TOTAL", None),
        ],
        fuzzy=False,
    )

    assert (result.predicted, result.expected, result.found) == (4, 4, 3)
    assert (result.food_ok, result.qty_labelled, result.qty_ok, result.end_to_end) == (2, 2, 1, 1)
    assert len(result.issues) == 4  # eggs wrong food, bread amount, ham missed, TOTAL extra


async def test_text_path_meets_the_floor(usda: async_sessionmaker[AsyncSession]) -> None:
    metrics, total = summarize(await run_text(usda, load_labels()))

    assert metrics.precision >= 0.95, total.issues
    assert metrics.recall >= 0.95, total.issues
    assert metrics.food >= 0.9, total.issues
    assert metrics.quantity >= 0.9, total.issues
    assert metrics.end_to_end >= 0.9, total.issues


async def test_photo_path_on_three_receipts(usda: async_sessionmaker[AsyncSession]) -> None:
    pytest.importorskip("rapidocr")
    receipts = [r for r in load_labels() if r.id in {"r01_tesco", "r13_walmart", "r16_costco"}]
    try:
        scores, _ = await run_images(usda, receipts)
    except Exception as exc:  # models missing or onnxruntime unavailable on this platform
        pytest.skip(f"OCR engine unavailable: {exc}")

    metrics, total = summarize(scores)
    assert metrics.receipts == 3
    assert metrics.recall >= 0.85, total.issues
    assert metrics.end_to_end >= 0.8, total.issues

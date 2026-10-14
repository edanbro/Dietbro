"""Prices learned from the user's own receipts. The estimate tables are UK averages scaled for
the region (larder_core.regions); a confirmed receipt line says what this user actually pays.

Per food the planner counts (a product counts as its generic, like pantry items), the learned
price per kg is the median of the latest few confirmed lines with a printed size and price,
from the last half year. Lines far from the estimate (outside 0.25-4x) are taken as misread
(a price on the wrong line, "2 for" deals) and ignored. Per user only: one person's receipts
never price another's plan.
"""

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from larder_db import models as db

__all__ = [
    "LATEST",
    "LOOKBACK_DAYS",
    "learned_price",
    "price_with_receipts",
    "receipt_prices",
]

LOOKBACK_DAYS = 180
LATEST = 5  # lines per food
_LOW, _HIGH = 0.25, 4.0

# The statuses a confirmed line can end in that went into the pantry (not "rejected").
_KEPT = ("suggested", "accepted", "edited")


async def receipt_prices(
    session: AsyncSession, user_id: int, today: date
) -> dict[int, tuple[int, ...]]:
    """Food id -> the latest prices paid (minor units per kg, newest first), from the user's
    confirmed receipts of the last LOOKBACK_DAYS. Lines without a printed size are skipped."""
    key = func.coalesce(db.Food.generic_food_id, db.ReceiptLine.food_id)
    rows = await session.execute(
        select(key, db.ReceiptLine.price_minor, db.ReceiptLine.grams)
        .join(db.ReceiptUpload, db.ReceiptLine.upload_id == db.ReceiptUpload.id)
        .join(db.Food, db.ReceiptLine.food_id == db.Food.id)
        .where(
            db.ReceiptUpload.user_id == user_id,
            db.ReceiptUpload.status == "confirmed",
            db.ReceiptUpload.purchased_on >= today - timedelta(days=LOOKBACK_DAYS),
            db.ReceiptLine.status.in_(_KEPT),
            db.ReceiptLine.approx.is_(False),
            db.ReceiptLine.price_minor > 0,
            db.ReceiptLine.grams > 0,
        )
        .order_by(db.ReceiptUpload.purchased_on.desc(), db.ReceiptLine.id.desc())
    )
    out: dict[int, list[int]] = {}
    for food_id, price_minor, grams in rows:
        if price_minor is None or not grams:
            continue  # filtered above; for the type checker
        seen = out.setdefault(food_id, [])
        if len(seen) < LATEST:
            seen.append(round(price_minor * 1000 / grams))
    return {fid: tuple(p) for fid, p in out.items()}


def learned_price(estimate: int, paid: Sequence[int]) -> int | None:
    """The median of `paid` (per kg) after dropping prices outside 0.25-4x the estimate; None
    when none is left. Without an estimate (0) every price counts."""
    kept = [p for p in paid if estimate <= 0 or _LOW * estimate <= p <= _HIGH * estimate]
    return round(median(kept)) if kept else None


def price_with_receipts(estimate: int, food_id: int, paid: Mapping[int, Sequence[int]]) -> int:
    """The estimate, unless the user's receipts say otherwise."""
    learned = learned_price(estimate, paid.get(food_id, ()))
    return estimate if learned is None else learned

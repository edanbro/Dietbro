"""Price watch: what the user pays for the foods they buy again and again, from their own
confirmed receipts (GET /insights/prices).

Lines are compared per kg and grouped like the planner's learned prices (larder_api.prices): a
product counts as its generic food, so two brands of chicken breast are one item. Only lines with
a printed size and price count. Within an item, a line far from the item's usual price (outside
0.25-4x its median) is taken as misread (a price on the wrong line, a "2 for" deal) and left out.

For each item bought at least twice:
- the price history, the latest price and the usual one (the median of the earlier ones);
- a rise when the latest is at least RISE times the usual, with two or more earlier prices;
- a cheaper option when another product the user bought for the same item has a median price at
  least CHEAPER below the latest one: what it was, its price and when they last bought it.
Per user only: one person's receipts never show in another's.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from larder_db import models as db

__all__ = ["CHEAPER", "RISE", "Bought", "Cheaper", "Item", "load_lines", "watch"]

RISE = 1.15
CHEAPER = 0.9
_LOW, _HIGH = 0.25, 4.0
HISTORY = 12  # prices kept per item, newest last
_KEPT = ("suggested", "accepted", "edited")  # confirmed lines that went into the pantry


@dataclass(frozen=True, slots=True)
class Bought:
    """One receipt line: `item` is the generic food (or the food itself), `product` the food
    matched on the line, `label` how to name that product."""

    item: int
    item_name: str
    product: int
    label: str
    on: date
    per_kg: int  # minor units


@dataclass(frozen=True, slots=True)
class Cheaper:
    label: str
    per_kg: int
    last_bought: date


@dataclass(frozen=True, slots=True)
class Item:
    food_id: int
    name: str
    history: tuple[tuple[date, int], ...]  # (bought on, per kg), oldest first
    latest: int
    usual: int  # the median of the earlier prices
    change_pct: int  # latest against usual
    rise: bool
    cheaper: Cheaper | None


def watch(lines: Iterable[Bought]) -> list[Item]:
    """Items bought at least twice, rises first (biggest first), then by name."""
    by_item: dict[int, list[Bought]] = defaultdict(list)
    for line in lines:
        by_item[line.item].append(line)
    items: list[Item] = []
    for item_id, bought in by_item.items():
        middle = median(b.per_kg for b in bought)
        kept = sorted(
            (b for b in bought if _LOW * middle <= b.per_kg <= _HIGH * middle),
            key=lambda b: b.on,
        )
        if len(kept) < 2:
            continue
        latest, earlier = kept[-1], kept[:-1]
        usual = round(median(b.per_kg for b in earlier))
        change = round((latest.per_kg / usual - 1) * 100)
        rise = len(earlier) >= 2 and latest.per_kg >= RISE * usual
        items.append(
            Item(
                food_id=item_id,
                name=latest.item_name,
                history=tuple((b.on, b.per_kg) for b in kept[-HISTORY:]),
                latest=latest.per_kg,
                usual=usual,
                change_pct=change,
                rise=rise,
                cheaper=_cheaper(kept, latest),
            )
        )
    return sorted(items, key=lambda i: (not i.rise, -i.change_pct if i.rise else 0, i.name))


def _cheaper(kept: Sequence[Bought], latest: Bought) -> Cheaper | None:
    by_product: dict[int, list[Bought]] = defaultdict(list)
    for b in kept:
        if b.product != latest.product:
            by_product[b.product].append(b)
    best: Cheaper | None = None
    for bought in by_product.values():
        price = round(median(b.per_kg for b in bought))
        if price <= CHEAPER * latest.per_kg and (best is None or price < best.per_kg):
            last = max(bought, key=lambda b: b.on)
            best = Cheaper(label=last.label, per_kg=price, last_bought=last.on)
    return best


async def load_lines(session: AsyncSession, user_id: int, today: date, months: int) -> list[Bought]:
    """The user's priced, sized lines from confirmed receipts of the last `months` months."""
    generic = aliased(db.Food)
    rows = await session.execute(
        select(
            func.coalesce(db.Food.generic_food_id, db.ReceiptLine.food_id),
            func.coalesce(generic.description, db.Food.description),
            db.ReceiptLine.food_id,
            db.Food.brand,
            db.Food.description,
            db.Food.generic_food_id,
            db.ReceiptLine.name,
            db.ReceiptUpload.purchased_on,
            db.ReceiptLine.price_minor,
            db.ReceiptLine.grams,
        )
        .join(db.ReceiptUpload, db.ReceiptLine.upload_id == db.ReceiptUpload.id)
        .join(db.Food, db.ReceiptLine.food_id == db.Food.id)
        .outerjoin(generic, db.Food.generic_food_id == generic.id)
        .where(
            db.ReceiptUpload.user_id == user_id,
            db.ReceiptUpload.status == "confirmed",
            db.ReceiptUpload.purchased_on >= today - timedelta(days=31 * months),
            db.ReceiptLine.status.in_(_KEPT),
            db.ReceiptLine.approx.is_(False),
            db.ReceiptLine.price_minor > 0,
            db.ReceiptLine.grams > 0,
        )
    )
    out: list[Bought] = []
    for (
        item,
        item_name,
        product,
        brand,
        description,
        generic_id,
        line_name,
        on,
        price,
        grams,
    ) in rows:
        if price is None or not grams or product is None:
            continue  # filtered above; for the type checker
        # A product reads best as its brand and name; a generic match as the receipt's words.
        label = (
            " ".join(part for part in (brand, description) if part)
            if generic_id is not None
            else (line_name or description)
        )
        out.append(
            Bought(
                item=item,
                item_name=item_name,
                product=product,
                label=label,
                on=on,
                per_kg=round(price * 1000 / grams),
            )
        )
    return out

"""Receipt intake (M6, docs/adr/0016-receipt-intake.md): text -> suggested pantry lines.

The API stores an upload (photo or pasted text) and enqueues it; the worker runs
`process_upload`, handing in its OCR for photos. Everything after the text is here, so the
pasted-text path, the worker and the accuracy eval share one pipeline:

    text -> larder_core.receipts.parse_receipt -> items (name, count, size, price, storage)
    item -> match_receipt_food -> food        (no model: vocabulary, alias, trigram, sub-phrase)
    item + food portions -> estimate_amount   (quantity/unit/grams, approx without a size)
    food + purchase date -> suggest_expiry    (larder_core.shelf_life)

Matching, in order: the receipt vocabulary (larder_core/data/receipt_foods.csv) and the curated
alias table on the whole name; a trigram clear winner (larder_api.foodmatch) among grocery
categories whose description starts with one of the name's words and isn't a cooked form the
name didn't ask for; then the same tables on shorter runs of the name's words, longest and
rightmost first ("chicken breast fillet" -> "chicken breast"), marked `partial`. Anything else
stays unmatched for the user to pick. Receipt text is data: it only ever becomes search terms.

`process_upload` is idempotent and safe to retry: it claims the upload with a conditional
UPDATE (queued/processing -> processing), replaces the upload's lines in one transaction, and
deletes the photo whether reading succeeded or failed. `sweep_stale` fails uploads a crashed or
timed-out job left behind.
"""

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from larder_api.clock import utc_now
from larder_api.foodmatch import (
    NOT_GROCERIES,
    FoodMatch,
    alias_food,
    candidates,
    clear_winner,
    tokens,
)
from larder_api.routers.foods import load_portions
from larder_core.quantities import grams_for
from larder_core.receipts import (
    Amount,
    ReceiptItem,
    estimate_amount,
    load_receipt_foods,
    match_names,
    parse_receipt,
)
from larder_core.shelf_life import suggest_expiry
from larder_core.units import parse_measure
from larder_db.models import Food, PantryItem, ReceiptLine, ReceiptUpload

logger = logging.getLogger(__name__)

type ReadImage = Callable[[bytes], Awaitable[str]]

NO_TEXT = (
    "Couldn't read any text in the photo. Try a sharper, well-lit photo of the whole receipt, "
    "or paste the receipt's text instead."
)
NO_ITEMS = (
    "No item lines found on this receipt (an item line has a name and a price). Try a clearer "
    "photo, or paste the text."
)
GONE = "The photo is no longer available; upload it again."
BROKEN = "Something went wrong reading this receipt. Try again, or paste the text."
STALE = "Reading this receipt took too long. Try again, or paste the text."

# Description words for prepared foods; a receipt names what's in the bag, not a cooked dish.
_COOKED = frozenset(
    {
        "cooked",
        "roasted",
        "braised",
        "grilled",
        "fried",
        "broiled",
        "boiled",
        "microwaved",
        "stewed",
        "toasted",
        "heated",
        "prepared",
        "simmered",
        "steamed",
    }
)


class ReceiptUnreadable(Exception):
    """A receipt we couldn't use; the message is shown to the user."""


@dataclass(frozen=True, slots=True)
class Suggestion:
    """One parsed item and the pantry entry suggested for it (food None: unmatched)."""

    item: ReceiptItem
    match: FoodMatch | None
    amount: Amount | None
    expires_on: date | None


# --- matching ---------------------------------------------------------------------------------


async def _table_food(session: AsyncSession, phrase: str) -> FoodMatch | None:
    fdc_id = load_receipt_foods().get(phrase)
    if fdc_id is not None and (food := await session.get(Food, fdc_id)) is not None:
        return FoodMatch(food.id, food.description, "receipt")
    return await alias_food(session, phrase)


def _plausible(name: str, description: str) -> bool:
    """A trigram winner must start with one of the name's words ("Cereals, ... DINOSAUR EGGS"
    is not "brown eggs") and not be a cooked form the name didn't ask for."""
    words = tokens(name)
    if not words & tokens(description.split(",", 1)[0]):
        return False
    return not (tokens(description) & _COOKED) - words


async def match_receipt_food(session: AsyncSession, name: str) -> FoodMatch | None:
    phrases = match_names(name)
    if not phrases:
        return None
    if (hit := await _table_food(session, phrases[0])) is not None:
        return hit
    winner = clear_winner(await candidates(session, phrases[0], exclude_categories=NOT_GROCERIES))
    if winner is not None and _plausible(phrases[0], winner.description):
        return FoodMatch(winner.food_id, winner.description, "trigram")
    for phrase in phrases[1:]:
        if (hit := await _table_food(session, phrase)) is not None:
            return FoodMatch(hit.food_id, hit.description, "partial")
    return None


# --- amounts ----------------------------------------------------------------------------------


async def amount_for(session: AsyncSession, item: ReceiptItem, food: Food) -> Amount:
    """The item's amount for this food, in a quantity/unit the pantry converts back to the same
    grams (larder_api.routers.pantry.to_grams); otherwise in grams."""
    portions = await load_portions(session, food.id)
    amount = estimate_amount(item, portions, food.description, food.category)
    measure = parse_measure(f"{amount.quantity:g} {amount.unit}")
    grams = grams_for(measure, portions, food.description.lower(), food.category)
    if grams is None or grams <= 0 or measure.vague:
        grams = amount.grams
        return Amount(round(grams), "g", grams, amount.approx)
    return Amount(amount.quantity, amount.unit, grams, amount.approx)


def item_of(line: ReceiptLine) -> ReceiptItem:
    """The parsed item behind a stored line (re-read from its text)."""
    items = parse_receipt(line.raw_text.replace(" | ", "\n"))
    return items[0] if items else ReceiptItem(raw=line.raw_text, name=line.name)


async def suggest(session: AsyncSession, item: ReceiptItem, purchased_on: date) -> Suggestion:
    match = await match_receipt_food(session, item.name)
    food = None if match is None else await session.get(Food, match.food_id)
    if match is None or food is None:
        return Suggestion(item, None, None, None)
    amount = await amount_for(session, item, food)
    expires = suggest_expiry(purchased_on, food.description, food.category, storage=item.storage)
    return Suggestion(item, match, amount, expires)


async def read_text(session: AsyncSession, text: str, purchased_on: date) -> list[Suggestion]:
    return [await suggest(session, item, purchased_on) for item in parse_receipt(text)]


# --- the job ----------------------------------------------------------------------------------


async def process_upload(
    maker: async_sessionmaker[AsyncSession],
    upload_id: int,
    read_image: ReadImage | None,
) -> str | None:
    """Read one upload into lines. Returns the final status, or None when there was nothing to
    do (already read, confirmed or deleted)."""
    async with maker() as session:
        claimed = (
            await session.execute(
                update(ReceiptUpload)
                .where(
                    ReceiptUpload.id == upload_id,
                    ReceiptUpload.status.in_(("queued", "processing")),
                )
                .values(status="processing", updated_at=func.now())
                .returning(ReceiptUpload.source, ReceiptUpload.text, ReceiptUpload.purchased_on)
            )
        ).first()
        image = (
            await session.scalar(select(ReceiptUpload.image).where(ReceiptUpload.id == upload_id))
            if claimed is not None and claimed.source == "image"
            else None
        )
        await session.commit()
    if claimed is None:
        return None

    started = time.perf_counter()
    text: str | None = claimed.text
    suggestions: list[Suggestion] = []
    error: str | None = None
    try:
        if claimed.source == "image":
            if image is None:
                raise ReceiptUnreadable(GONE)
            if read_image is None:
                raise RuntimeError("this process has no OCR engine")
            text = await read_image(image)
        if not text or not text.strip():
            raise ReceiptUnreadable(NO_TEXT)
        async with maker() as session:
            suggestions = await read_text(session, text, claimed.purchased_on)
        if not suggestions:
            raise ReceiptUnreadable(NO_ITEMS)
    except ReceiptUnreadable as exc:
        error, suggestions = str(exc), []
    except Exception:
        logger.exception("reading receipt upload %s failed", upload_id)
        error, suggestions = BROKEN, []
    elapsed_ms = round((time.perf_counter() - started) * 1000)

    async with maker() as session:
        upload = await session.get(ReceiptUpload, upload_id, with_for_update=True)
        if upload is None or upload.status != "processing":
            return None  # deleted (or swept) while we read it
        await session.execute(delete(ReceiptLine).where(ReceiptLine.upload_id == upload_id))
        session.add_all(_line(upload_id, i, s) for i, s in enumerate(suggestions))
        upload.status = "failed" if error else "ready"
        upload.error = error
        upload.text = text
        upload.image = None  # privacy: the photo is gone once read, success or not
        upload.read_ms = elapsed_ms
        upload.processed_at = utc_now()
        await session.commit()
        logger.info(
            "receipt %s read: %s, %d lines, %d matched, %d ms",
            upload_id,
            upload.status,
            len(suggestions),
            sum(s.match is not None for s in suggestions),
            elapsed_ms,
        )
        return upload.status


def _line(upload_id: int, position: int, s: Suggestion) -> ReceiptLine:
    return ReceiptLine(
        upload_id=upload_id,
        position=position,
        raw_text=s.item.raw[:1000],
        name=s.item.name[:500],
        food_id=None if s.match is None else s.match.food_id,
        match_method=None if s.match is None else s.match.method,
        quantity=None if s.amount is None else s.amount.quantity,
        unit=None if s.amount is None else s.amount.unit,
        grams=None if s.amount is None else s.amount.grams,
        approx=False if s.amount is None else s.amount.approx,
        price_minor=s.item.price_minor,
        expires_on=s.expires_on,
        status="suggested",
    )


async def sweep_stale(maker: async_sessionmaker[AsyncSession], older_than: timedelta) -> int:
    """Fail uploads stuck in queued/processing (a job that crashed or timed out) and delete
    their photos. Returns how many."""
    cutoff: datetime = utc_now() - older_than
    async with maker() as session:
        result = await session.execute(
            update(ReceiptUpload)
            .where(
                ReceiptUpload.status.in_(("queued", "processing")),
                ReceiptUpload.updated_at < cutoff,
            )
            .values(status="failed", error=STALE, image=None, updated_at=func.now())
            .returning(ReceiptUpload.id)
        )
        swept = len(result.all())
        await session.commit()
    return swept


# --- confirm ----------------------------------------------------------------------------------


def confirmable(line: ReceiptLine) -> bool:
    """Lines confirm adds: anything not rejected that has a food and an amount."""
    return (
        line.status != "rejected"
        and line.food_id is not None
        and line.grams is not None
        and line.quantity is not None
        and line.unit is not None
    )


def confirm(upload: ReceiptUpload) -> list[tuple[ReceiptLine, PantryItem]]:
    """Pantry items (source receipt) for every confirmable line; suggested lines become
    accepted. The caller adds, flushes and links them (`pantry_item_id`) and commits; the full
    receipt text is dropped (it holds payment lines)."""
    created: list[tuple[ReceiptLine, PantryItem]] = []
    for line in upload.lines:
        food_id, grams, quantity, unit = line.food_id, line.grams, line.quantity, line.unit
        if line.status == "rejected" or None in (food_id, grams, quantity, unit):
            continue
        assert food_id is not None
        assert grams is not None
        assert quantity is not None
        assert unit is not None
        item = PantryItem(
            user_id=upload.user_id,
            food_id=food_id,
            grams=grams,
            quantity=quantity,
            unit=unit,
            approx=line.approx,
            expires_on=line.expires_on,
            source="receipt",
        )
        created.append((line, item))
        if line.status == "suggested":
            line.status = "accepted"
    upload.status = "confirmed"
    upload.confirmed_at = utc_now()
    upload.text = None
    return created

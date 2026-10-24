"""What the user buys most weeks (GET /shopping/usuals), from their own confirmed receipts:
offered on the shopping list to add in one tap ("milk", "bread"), since a plan only lists what
its recipes need."""

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from larder_api.auth import CurrentUser
from larder_api.clock import Clock, get_clock
from larder_api.db import Session
from larder_api.prices import KEPT_LINES
from larder_api.schemas import UsualOut
from larder_core.regions import local_today
from larder_db import models as db

router = APIRouter(prefix="/shopping", tags=["shopping"])

WEEKS = 8  # looked back over
MIN_WEEKS = 3  # bought in at least this many of them
SHOWN = 8


def _week(on: date) -> date:
    return on - timedelta(days=on.weekday())


@router.get("/usuals", operation_id="listShoppingUsuals")
async def usuals(
    user: CurrentUser, session: Session, clock: Annotated[Clock, Depends(get_clock)]
) -> list[UsualOut]:
    """Foods on the user's confirmed receipts in at least MIN_WEEKS of the last WEEKS weeks
    (a product counts as its generic food), most weeks first, then most recently bought."""
    today = local_today(user.timezone, clock())
    generic = aliased(db.Food)
    rows = await session.execute(
        select(
            func.coalesce(db.Food.generic_food_id, db.ReceiptLine.food_id),
            func.coalesce(generic.description, db.Food.description),
            db.ReceiptUpload.purchased_on,
        )
        .select_from(db.ReceiptLine)
        .join(db.ReceiptUpload, db.ReceiptLine.upload_id == db.ReceiptUpload.id)
        .join(db.Food, db.ReceiptLine.food_id == db.Food.id)
        .outerjoin(generic, db.Food.generic_food_id == generic.id)
        .where(
            db.ReceiptUpload.user_id == user.id,
            db.ReceiptUpload.status == "confirmed",
            db.ReceiptUpload.purchased_on > today - timedelta(weeks=WEEKS),
            db.ReceiptUpload.purchased_on <= today,
            db.ReceiptLine.status.in_(KEPT_LINES),
        )
    )
    weeks: dict[int, set[date]] = {}
    names: dict[int, str] = {}
    last: dict[int, date] = {}
    for food_id, name, on in rows:
        weeks.setdefault(food_id, set()).add(_week(on))
        names[food_id] = name
        last[food_id] = max(on, last.get(food_id, on))
    often = [f for f, w in weeks.items() if len(w) >= MIN_WEEKS]
    often.sort(key=lambda f: (-len(weeks[f]), -last[f].toordinal(), names[f]))
    return [
        UsualOut(food_id=f, name=names[f], weeks=len(weeks[f]), last_bought=last[f])
        for f in often[:SHOWN]
    ]

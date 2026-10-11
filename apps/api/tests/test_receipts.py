"""Receipt intake (DESIGN §7, docs/adr/0016): upload/paste -> worker job -> review -> pantry.
The worker is simulated by running `process_upload` with a fake OCR; the queue by a list."""

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from larder_api.clock import get_clock
from larder_api.jobs import QueueUnavailable, get_enqueue
from larder_api.main import app
from larder_api.receipts import BROKEN, NO_ITEMS, NO_TEXT, STALE, process_upload, sweep_stale
from larder_api.settings import Settings, get_settings
from larder_db import models as db
from larder_db.engine import make_sessionmaker

Auth = Callable[..., dict[str, str]]

MILK, EGG, CHICKEN, BANANA, TOMATOES, ONION = 171267, 171287, 171077, 173944, 170051, 170000
BOUGHT = date(2026, 10, 12)
NOW = datetime.fromisoformat("2026-10-12T09:00:00+00:00")
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

RECEIPT = """TESCO
Tesco Stores Ltd
TESCO SEMI SKMD MILK 4PT        £1.45
TSC CHKN BRST FLLTS 650G        £4.75
BANANAS LOOSE                   £0.68
2 x TESCO CHOPPED TOMS 400G     £1.10
TSC FR LGE EGGS 6PK             £2.10
MYSTERY GADGET                  £9.99
CLUBCARD PRICE                 -£0.50
TOTAL                          £19.57
VISA                           £19.57
"""


@dataclass
class Worker:
    """Collects enqueued uploads and runs them like the worker would."""

    maker: async_sessionmaker[AsyncSession]
    queued: list[int] = field(default_factory=list[int])
    ocr_text: str = RECEIPT
    ocr_error: Exception | None = None
    down: bool = False

    async def enqueue(self, upload_id: int) -> None:
        if self.down:
            raise QueueUnavailable("connection refused")
        self.queued.append(upload_id)

    async def ocr(self, image: bytes) -> str:
        assert image == PNG
        if self.ocr_error is not None:
            raise self.ocr_error
        return self.ocr_text

    async def run(self) -> list[str | None]:
        done = [await process_upload(self.maker, i, self.ocr) for i in self.queued]
        self.queued.clear()
        return done


@pytest.fixture
async def grocery(db_engine: AsyncEngine, foods: None) -> None:
    async with make_sessionmaker(db_engine)() as session:
        session.add_all(
            [
                db.Food(
                    id=MILK,
                    description="Milk, reduced fat, fluid, 2% milkfat, with added vitamin A and "
                    "vitamin D",
                    data_type="sr_legacy",
                    category="Dairy and Egg Products",
                    kcal=50,
                    portions=[db.FoodPortion(amount=1, unit="cup", grams=244)],
                ),
                db.Food(
                    id=EGG,
                    description="Egg, whole, raw, fresh",
                    data_type="sr_legacy",
                    category="Dairy and Egg Products",
                    kcal=143,
                    portions=[
                        db.FoodPortion(amount=1, unit="large", grams=50),
                        db.FoodPortion(amount=1, unit="medium", grams=44),
                    ],
                ),
                db.Food(
                    id=CHICKEN,
                    description="Chicken, broiler or fryers, breast, skinless, boneless, meat "
                    "only, raw",
                    data_type="sr_legacy",
                    category="Poultry Products",
                    kcal=120,
                ),
                db.Food(
                    id=BANANA,
                    description="Bananas, raw",
                    data_type="sr_legacy",
                    category="Fruits and Fruit Juices",
                    kcal=89,
                    portions=[db.FoodPortion(amount=1, unit="medium", grams=118)],
                ),
                db.Food(
                    id=TOMATOES,
                    description="Tomatoes, red, ripe, canned, packed in tomato juice",
                    data_type="sr_legacy",
                    category="Vegetables and Vegetable Products",
                    kcal=16,
                ),
            ]
        )
        await session.commit()


@pytest.fixture
async def worker(
    api: httpx.AsyncClient, db_engine: AsyncEngine, grocery: None
) -> AsyncIterator[Worker]:
    w = Worker(make_sessionmaker(db_engine))
    app.dependency_overrides[get_enqueue] = lambda: w.enqueue
    app.dependency_overrides[get_clock] = lambda: lambda: NOW
    yield w
    app.dependency_overrides.pop(get_enqueue, None)
    app.dependency_overrides.pop(get_clock, None)


async def paste(api: httpx.AsyncClient, auth: Auth, text: str = RECEIPT, user: str = "user_a"):
    return await api.post(
        "/pantry/receipts/text",
        json={"text": text, "purchased_on": BOUGHT.isoformat()},
        headers=auth(user),
    )


async def ready(api: httpx.AsyncClient, auth: Auth, worker: Worker, user: str = "user_a"):
    upload = (await paste(api, auth, user=user)).json()
    await worker.run()
    return (await api.get(f"/pantry/receipts/{upload['id']}", headers=auth(user))).json()


def by_name(receipt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {line["name"]: line for line in receipt["lines"]}


# --- reading ----------------------------------------------------------------------------------


async def test_pasted_text_is_queued_then_read_into_suggestions(
    api: httpx.AsyncClient, auth: Auth, worker: Worker
) -> None:
    response = await paste(api, auth)

    assert response.status_code == 202
    queued = response.json()
    assert (queued["status"], queued["source"], queued["lines"]) == ("queued", "text", [])
    assert worker.queued == [queued["id"]]

    assert await worker.run() == ["ready"]
    receipt = (await api.get(f"/pantry/receipts/{queued['id']}", headers=auth())).json()

    assert receipt["status"] == "ready"
    assert receipt["error"] is None
    lines = by_name(receipt)
    assert list(lines) == [
        "semi skimmed milk",
        "chicken breast fillet",
        "banana",
        "chopped tomato",
        "egg",
        "mystery gadget",
    ]
    milk = lines["semi skimmed milk"]
    assert (milk["food"]["id"], milk["match_method"]) == (MILK, "receipt")
    assert (milk["quantity"], milk["unit"], milk["approx"]) == (2273, "ml", False)
    assert milk["grams"] == pytest.approx(2273 * 244 / 240, rel=0.01)
    assert milk["expires_on"] == "2026-10-19"
    assert milk["price_minor"] == 145
    chicken = lines["chicken breast fillet"]
    assert (chicken["food"]["id"], chicken["match_method"]) == (CHICKEN, "partial")
    assert (chicken["grams"], chicken["expires_on"]) == (650, "2026-10-14")
    banana = lines["banana"]
    assert (banana["quantity"], banana["unit"], banana["grams"]) == (1, "medium", 118)
    assert banana["approx"] is True
    tomatoes = lines["chopped tomato"]
    assert (tomatoes["grams"], tomatoes["expires_on"]) == (800, None)  # tinned: no date
    eggs = lines["egg"]
    assert (eggs["quantity"], eggs["unit"], eggs["grams"]) == (6, "large", 300)
    gadget = lines["mystery gadget"]
    assert (gadget["food"], gadget["grams"], gadget["status"]) == (None, None, "suggested")


async def test_photo_is_read_by_ocr_and_deleted(
    api: httpx.AsyncClient, auth: Auth, worker: Worker, db_engine: AsyncEngine
) -> None:
    response = await api.post(
        "/pantry/receipts/image",
        files={"file": ("receipt.png", PNG, "application/octet-stream")},
        data={"purchased_on": BOUGHT.isoformat()},
        headers=auth(),
    )

    assert response.status_code == 202
    upload_id = response.json()["id"]
    assert response.json()["source"] == "image"
    async with make_sessionmaker(db_engine)() as session:
        assert await image_of(session, upload_id) == PNG

    assert await worker.run() == ["ready"]

    receipt = (await api.get(f"/pantry/receipts/{upload_id}", headers=auth())).json()
    assert len(receipt["lines"]) == 6
    async with make_sessionmaker(db_engine)() as session:
        assert await image_of(session, upload_id) is None
        row = await session.get(db.ReceiptUpload, upload_id)
        assert row is not None
        assert (row.image_bytes, row.image_type) == (len(PNG), "image/png")
        assert row.text == RECEIPT


async def image_of(session: AsyncSession, upload_id: int) -> bytes | None:
    return await session.scalar(
        select(db.ReceiptUpload.image).where(db.ReceiptUpload.id == upload_id)
    )


@pytest.mark.parametrize(
    ("text", "error"),
    [("   \n  ", NO_TEXT), ("THANK YOU FOR SHOPPING\nTOTAL 1.00", NO_ITEMS)],
)
async def test_unreadable_photo_fails_with_a_reason_and_is_deleted(
    api: httpx.AsyncClient,
    auth: Auth,
    worker: Worker,
    db_engine: AsyncEngine,
    text: str,
    error: str,
) -> None:
    worker.ocr_text = text
    upload_id = (
        await api.post("/pantry/receipts/image", files={"file": ("r.png", PNG)}, headers=auth())
    ).json()["id"]

    assert await worker.run() == ["failed"]

    receipt = (await api.get(f"/pantry/receipts/{upload_id}", headers=auth())).json()
    assert (receipt["status"], receipt["error"], receipt["lines"]) == ("failed", error, [])
    async with make_sessionmaker(db_engine)() as session:
        assert await image_of(session, upload_id) is None


async def test_ocr_crash_is_recorded(api: httpx.AsyncClient, auth: Auth, worker: Worker) -> None:
    worker.ocr_error = RuntimeError("onnx exploded")
    upload_id = (
        await api.post("/pantry/receipts/image", files={"file": ("r.png", PNG)}, headers=auth())
    ).json()["id"]

    assert await worker.run() == ["failed"]
    receipt = (await api.get(f"/pantry/receipts/{upload_id}", headers=auth())).json()
    assert receipt["error"] == BROKEN


async def test_job_is_idempotent_and_skips_deleted_uploads(
    api: httpx.AsyncClient, auth: Auth, worker: Worker
) -> None:
    first = (await paste(api, auth)).json()["id"]
    second = (await paste(api, auth)).json()["id"]
    worker.queued += [first]  # delivered twice

    assert (await api.delete(f"/pantry/receipts/{second}", headers=auth())).status_code == 204
    assert await worker.run() == ["ready", None, None]

    receipt = (await api.get(f"/pantry/receipts/{first}", headers=auth())).json()
    assert len(receipt["lines"]) == 6
    assert (await api.get(f"/pantry/receipts/{second}", headers=auth())).status_code == 404


async def test_a_retried_job_rereads_an_upload_left_processing(
    api: httpx.AsyncClient, auth: Auth, worker: Worker, db_engine: AsyncEngine
) -> None:
    upload_id = (await paste(api, auth)).json()["id"]
    maker = make_sessionmaker(db_engine)
    async with maker() as session:  # a worker died mid-job
        await session.execute(
            update(db.ReceiptUpload)
            .where(db.ReceiptUpload.id == upload_id)
            .values(status="processing")
        )
        await session.commit()

    assert await worker.run() == ["ready"]
    assert await worker.run() == []


async def test_stale_uploads_are_swept(
    api: httpx.AsyncClient, auth: Auth, worker: Worker, db_engine: AsyncEngine
) -> None:
    upload_id = (
        await api.post("/pantry/receipts/image", files={"file": ("r.png", PNG)}, headers=auth())
    ).json()["id"]
    maker = make_sessionmaker(db_engine)

    assert await sweep_stale(maker, timedelta(minutes=15)) == 0
    async with maker() as session:
        await session.execute(
            update(db.ReceiptUpload)
            .where(db.ReceiptUpload.id == upload_id)
            .values(updated_at=func.now() - timedelta(minutes=20))
        )
        await session.commit()
    assert await sweep_stale(maker, timedelta(minutes=15)) == 1

    receipt = (await api.get(f"/pantry/receipts/{upload_id}", headers=auth())).json()
    assert (receipt["status"], receipt["error"]) == ("failed", STALE)
    async with maker() as session:
        assert await image_of(session, upload_id) is None
    assert await worker.run() == [None]  # the late job finds nothing to do


# --- uploads: limits --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"GIF89a" + b"\x00" * 20, 415),
        (b"\x00\x00\x00\x18ftypheic" + b"\x00" * 20, 415),
        (b"\xff\xd8\xff" + b"\x00" * 2000, 413),
    ],
)
async def test_photo_type_and_size_are_checked(
    api: httpx.AsyncClient, auth: Auth, worker: Worker, content: bytes, code: int
) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(receipt_max_image_bytes=1000)
    try:
        response = await api.post(
            "/pantry/receipts/image",
            files={"file": ("r.jpg", content, "image/jpeg")},
            headers=auth(),
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == code
    assert worker.queued == []
    if content.startswith(b"\x00\x00\x00\x18ftyp"):
        assert "HEIC" in response.json()["detail"]


async def test_daily_upload_limit(api: httpx.AsyncClient, auth: Auth, worker: Worker) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(receipt_daily_uploads=2)
    try:
        codes = [(await paste(api, auth)).status_code for _ in range(3)]
        other = (await paste(api, auth, user="user_b")).status_code
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert codes == [202, 202, 429]
    assert other == 202


async def test_queue_down_fails_the_upload(
    api: httpx.AsyncClient, auth: Auth, worker: Worker, db_engine: AsyncEngine
) -> None:
    worker.down = True

    response = await api.post(
        "/pantry/receipts/image", files={"file": ("r.png", PNG)}, headers=auth()
    )

    assert response.status_code == 503
    listed = (await api.get("/pantry/receipts", headers=auth())).json()
    assert [(r["status"], r["error"]) for r in listed] == [("failed", "queue unavailable")]
    async with make_sessionmaker(db_engine)() as session:
        assert await image_of(session, listed[0]["id"]) is None


async def test_text_is_limited(api: httpx.AsyncClient, auth: Auth, worker: Worker) -> None:
    assert (await paste(api, auth, text="")).status_code == 422
    assert (await paste(api, auth, text="x" * 20_001)).status_code == 422


# --- review and confirm -----------------------------------------------------------------------


async def test_review_edits_then_confirm_fills_the_pantry(
    api: httpx.AsyncClient, auth: Auth, worker: Worker, db_engine: AsyncEngine
) -> None:
    receipt = await ready(api, auth, worker)
    lines = by_name(receipt)
    base = f"/pantry/receipts/{receipt['id']}/lines"

    rejected = await api.patch(
        f"{base}/{lines['banana']['id']}", json={"status": "rejected"}, headers=auth()
    )
    gadget = await api.patch(
        f"{base}/{lines['mystery gadget']['id']}", json={"food_id": ONION}, headers=auth()
    )
    eggs = await api.patch(
        f"{base}/{lines['egg']['id']}",
        json={"quantity": 12, "unit": "medium", "expires_on": "2026-11-01"},
        headers=auth(),
    )
    accepted = await api.patch(
        f"{base}/{lines['chopped tomato']['id']}", json={"status": "accepted"}, headers=auth()
    )

    assert rejected.json()["status"] == "rejected"
    assert gadget.status_code == 200
    g = gadget.json()
    assert (g["food"]["id"], g["match_method"], g["status"]) == (ONION, "user", "edited")
    assert (g["quantity"], g["unit"], g["grams"], g["approx"]) == (1, "medium", 110, True)
    assert g["expires_on"] == "2026-11-02"  # onions keep 21 days
    e = eggs.json()
    assert (e["quantity"], e["unit"], e["grams"], e["status"]) == (12, "medium", 528, "edited")
    assert e["expires_on"] == "2026-11-01"
    assert accepted.json()["status"] == "accepted"

    response = await api.post(f"/pantry/receipts/{receipt['id']}/confirm", headers=auth())

    assert response.status_code == 200
    body = response.json()
    created = {i["food"]["id"]: i for i in body["created"]}
    assert set(created) == {MILK, CHICKEN, TOMATOES, EGG, ONION}
    assert all(i["source"] == "receipt" for i in body["created"])
    assert created[ONION]["approx"] is True
    assert created[CHICKEN]["approx"] is False
    assert (created[EGG]["quantity"], created[EGG]["grams"]) == (12, 528)
    assert created[CHICKEN]["expires_on"] == "2026-10-14"
    statuses = {line["name"]: line["status"] for line in body["receipt"]["lines"]}
    assert statuses == {
        "semi skimmed milk": "accepted",
        "chicken breast fillet": "accepted",
        "banana": "rejected",
        "chopped tomato": "accepted",
        "egg": "edited",
        "mystery gadget": "edited",
    }
    assert body["receipt"]["status"] == "confirmed"
    linked = [line["pantry_item_id"] for line in body["receipt"]["lines"]]
    assert sorted(i for i in linked if i is not None) == sorted(i["id"] for i in body["created"])

    pantry = (await api.get("/pantry", headers=auth())).json()
    assert len(pantry) == 5
    async with make_sessionmaker(db_engine)() as session:
        upload = await session.get(db.ReceiptUpload, receipt["id"])
        assert upload is not None
        assert upload.text is None  # payment lines dropped

    again = await api.post(f"/pantry/receipts/{receipt['id']}/confirm", headers=auth())
    late_edit = await api.patch(
        f"{base}/{lines['banana']['id']}", json={"status": "accepted"}, headers=auth()
    )
    assert (again.status_code, late_edit.status_code) == (409, 409)
    assert len((await api.get("/pantry", headers=auth())).json()) == 5


async def test_unmatched_lines_are_skipped_and_need_a_food_to_accept(
    api: httpx.AsyncClient, auth: Auth, worker: Worker
) -> None:
    receipt = await ready(api, auth, worker)
    gadget = by_name(receipt)["mystery gadget"]
    path = f"/pantry/receipts/{receipt['id']}/lines/{gadget['id']}"

    assert (await api.patch(path, json={"status": "accepted"}, headers=auth())).status_code == 400
    bad_unit = await api.patch(path, json={"quantity": 2, "unit": "kg"}, headers=auth())
    assert bad_unit.status_code == 400
    missing = await api.patch(path, json={"food_id": 999}, headers=auth())
    assert missing.status_code == 404

    body = (await api.post(f"/pantry/receipts/{receipt['id']}/confirm", headers=auth())).json()
    assert len(body["created"]) == 5


async def test_confirm_needs_a_ready_receipt(
    api: httpx.AsyncClient, auth: Auth, worker: Worker
) -> None:
    upload_id = (await paste(api, auth)).json()["id"]

    response = await api.post(f"/pantry/receipts/{upload_id}/confirm", headers=auth())

    assert response.status_code == 409


async def test_list_is_newest_first_with_line_counts(
    api: httpx.AsyncClient, auth: Auth, worker: Worker
) -> None:
    first = await ready(api, auth, worker)
    second = (await paste(api, auth, text="TSC FR LGE EGGS 6PK  £2.10")).json()
    await worker.run()

    listed = (await api.get("/pantry/receipts", headers=auth())).json()

    assert [(r["id"], r["lines"]) for r in listed] == [(second["id"], 1), (first["id"], 6)]


# --- user scoping -----------------------------------------------------------------------------


async def test_other_users_receipts_are_invisible(
    api: httpx.AsyncClient, auth: Auth, worker: Worker
) -> None:
    receipt = await ready(api, auth, worker)
    line = receipt["lines"][0]
    other = auth("user_b")
    base = f"/pantry/receipts/{receipt['id']}"

    assert (await api.get("/pantry/receipts", headers=other)).json() == []
    assert (await api.get(base, headers=other)).status_code == 404
    assert (
        await api.patch(f"{base}/lines/{line['id']}", json={"status": "rejected"}, headers=other)
    ).status_code == 404
    assert (await api.post(f"{base}/confirm", headers=other)).status_code == 404
    assert (await api.delete(base, headers=other)).status_code == 404
    assert (await api.get("/pantry", headers=other)).json() == []
    assert (await api.get(base, headers=auth())).json()["status"] == "ready"


async def test_a_line_id_from_another_receipt_is_404(
    api: httpx.AsyncClient, auth: Auth, worker: Worker
) -> None:
    mine = await ready(api, auth, worker)
    theirs = await ready(api, auth, worker, user="user_b")

    response = await api.patch(
        f"/pantry/receipts/{mine['id']}/lines/{theirs['lines'][0]['id']}",
        json={"status": "rejected"},
        headers=auth(),
    )

    assert response.status_code == 404


async def test_receipts_need_auth(api: httpx.AsyncClient) -> None:
    assert (await api.get("/pantry/receipts")).status_code == 401
    assert (await api.post("/pantry/receipts/text", json={"text": "x"})).status_code == 401

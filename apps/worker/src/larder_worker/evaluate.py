"""Receipt line-item accuracy (M6's done criterion): `make receipt-eval`.

Runs the labelled receipts in apps/worker/tests/fixtures/receipts (labels.toml) through the
production pipeline (larder_api.receipts.read_text) against a database with USDA foods - the
seeded dev database by default - twice: from the receipt text (the pasted-text path) and from
rendered photos of some of them through OCR (the photo path). Writes docs/receipt-accuracy.md.

Metrics, per path (expected items exclude `optional` ones; a predicted line aligned to an
optional item is ignored):
- line precision: predicted item lines that are real items / predicted lines
- line recall: expected items found / expected items
- food accuracy: found items matched to an acceptable food / found items
- quantity accuracy: found, correctly matched items with a labelled amount whose grams are
  within tolerance / such items
- end to end: expected items found with an acceptable food (and, where labelled, the right
  amount) / expected items

A predicted line is aligned to an expected item when the item's key appears in the line (text
path) or matches part of it at >= 80% similarity (photo path, after OCR), first unused line
wins. `--write-foods` dumps the subset of foods the matcher can reach for the labelled text
(every candidate row of every query it makes, plus alias and label foods) so the CI test can
reproduce the text-path numbers without the full USDA import.
"""

import argparse
import asyncio
import gzip
import json
import re
import time
import tomllib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from larder_api.foodmatch import NOT_GROCERIES
from larder_api.receipts import Suggestion, read_text
from larder_api.settings import get_settings
from larder_core.aliases import load_aliases
from larder_core.names import normalise_name
from larder_core.receipts import load_receipt_foods, match_names, parse_receipt
from larder_db.engine import make_engine, make_sessionmaker
from larder_db.models import Food, FoodPortion

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "receipts"
PURCHASED = date(2026, 10, 12)
DEFAULT_TOL = 0.15
FUZZY = 0.8
# Photos rendered harder (larder_worker.render): small type, 4-6 degree tilt, noise, blur.
HARD = frozenset({"r05_lidl", "r16_costco", "r24_safeway"})


@dataclass(frozen=True, slots=True)
class Expected:
    key: str
    group: str
    foods: frozenset[int]
    grams: float | None
    tol: float
    optional: bool


@dataclass(frozen=True, slots=True)
class Labelled:
    id: str
    text: str
    items: tuple[Expected, ...]
    image: Path | None
    holdout: bool


@dataclass
class Score:
    """Counts for one receipt on one path, plus what went wrong (for the report)."""

    receipt: str
    holdout: bool
    predicted: int = 0
    expected: int = 0
    found: int = 0
    food_ok: int = 0
    qty_labelled: int = 0
    qty_ok: int = 0
    end_to_end: int = 0
    approx: int = 0
    methods: Counter[str] = field(default_factory=Counter[str])
    issues: list[str] = field(default_factory=list[str])
    seconds: float = 0.0

    def add(self, other: "Score") -> None:
        for name in (
            "predicted",
            "expected",
            "found",
            "food_ok",
            "qty_labelled",
            "qty_ok",
            "end_to_end",
            "approx",
            "seconds",
        ):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.methods.update(other.methods)
        self.issues += other.issues


def load_labels(directory: Path = FIXTURES) -> list[Labelled]:
    data = tomllib.loads((directory / "labels.toml").read_text(encoding="utf-8"))
    groups: dict[str, list[int]] = data["foods"]
    out: list[Labelled] = []
    for r in data["receipt"]:
        items = tuple(
            Expected(
                key=i["key"],
                group=i["food"],
                foods=frozenset(groups[i["food"]]),
                grams=i.get("grams"),
                tol=i.get("tol", DEFAULT_TOL),
                optional=i.get("optional", False),
            )
            for i in r["items"]
        )
        image = directory / f"{r['id']}.jpg"
        out.append(
            Labelled(
                id=r["id"],
                text=(directory / f"{r['id']}.txt").read_text(encoding="utf-8"),
                items=items,
                image=image if image.exists() else None,
                holdout=r.get("holdout", False),
            )
        )
    return out


def _norm(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def similarity(key: str, line: str) -> float:
    """How well `key` matches part of `line` (1.0 = contained), ignoring case and spacing."""
    k, s = _norm(key), _norm(line)
    if not k:
        return 0.0
    if k in s:
        return 1.0
    if len(s) <= len(k):
        return SequenceMatcher(None, k, s).ratio()
    return max(
        SequenceMatcher(None, k, s[i : i + len(k)]).ratio() for i in range(len(s) - len(k) + 1)
    )


def score(receipt: Labelled, suggestions: Sequence[Suggestion], *, fuzzy: bool) -> Score:
    result = Score(receipt.id, receipt.holdout)
    used: set[int] = set()
    threshold = FUZZY if fuzzy else 1.0
    ignored = 0
    for want in receipt.items:
        best: tuple[float, int] | None = None
        for i, s in enumerate(suggestions):
            if i in used:
                continue
            sim = similarity(want.key, s.item.raw)
            if sim >= threshold and (best is None or sim > best[0]):
                best = (sim, i)
                if sim == 1.0:
                    break
        if want.optional:
            if best is not None:
                used.add(best[1])
                ignored += 1
            continue
        result.expected += 1
        if best is None:
            result.issues.append(f"{receipt.id}: missed `{want.key}`")
            continue
        used.add(best[1])
        got = suggestions[best[1]]
        result.found += 1
        if got.match is not None:
            result.methods[got.match.method] += 1
        if got.amount is not None and got.amount.approx:
            result.approx += 1
        food_ok = got.match is not None and got.match.food_id in want.foods
        qty_ok = True
        if not food_ok:
            matched = "nothing" if got.match is None else f"{got.match.description!r}"
            result.issues.append(f"{receipt.id}: `{want.key}` -> {matched} (want {want.group})")
        else:
            result.food_ok += 1
            if want.grams is not None:
                result.qty_labelled += 1
                grams = got.amount.grams if got.amount is not None else 0.0
                qty_ok = abs(grams - want.grams) <= want.tol * want.grams
                if qty_ok:
                    result.qty_ok += 1
                else:
                    result.issues.append(
                        f"{receipt.id}: `{want.key}` {grams:.0f} g (want {want.grams:.0f} g)"
                    )
        if food_ok and qty_ok:
            result.end_to_end += 1
    result.predicted = len(suggestions) - ignored
    for i, s in enumerate(suggestions):
        if i not in used:
            result.issues.append(f"{receipt.id}: not an item: `{s.item.raw}`")
    return result


async def run_text(
    maker: async_sessionmaker[AsyncSession], receipts: Sequence[Labelled]
) -> list[Score]:
    scores: list[Score] = []
    for r in receipts:
        started = time.perf_counter()
        async with maker() as session:
            suggestions = await read_text(session, r.text, PURCHASED)
        s = score(r, suggestions, fuzzy=False)
        s.seconds = time.perf_counter() - started
        scores.append(s)
    return scores


async def run_images(
    maker: async_sessionmaker[AsyncSession], receipts: Sequence[Labelled]
) -> tuple[list[Score], dict[str, str]]:
    from larder_worker.ocr import Ocr  # needs the OCR models; only this path loads them

    ocr = Ocr(get_settings().ocr_max_side_px)
    await asyncio.to_thread(ocr.engine)
    scores: list[Score] = []
    texts: dict[str, str] = {}
    for r in receipts:
        if r.image is None:
            continue
        started = time.perf_counter()
        texts[r.id] = await asyncio.to_thread(ocr.read, r.image.read_bytes())
        async with maker() as session:
            suggestions = await read_text(session, texts[r.id], PURCHASED)
        s = score(r, suggestions, fuzzy=True)
        s.seconds = time.perf_counter() - started
        scores.append(s)
    return scores, texts


@dataclass(frozen=True, slots=True)
class Metrics:
    receipts: int
    expected: int
    precision: float
    recall: float
    food: float
    quantity: float
    end_to_end: float
    approx: float
    seconds: float


def summarize(scores: Sequence[Score]) -> tuple[Metrics, Score]:
    total = Score("all", False)
    for s in scores:
        total.add(s)

    def ratio(a: int, b: int) -> float:
        return a / b if b else 0.0

    return (
        Metrics(
            receipts=len(scores),
            expected=total.expected,
            precision=ratio(total.found, total.predicted),
            recall=ratio(total.found, total.expected),
            food=ratio(total.food_ok, total.found),
            quantity=ratio(total.qty_ok, total.qty_labelled),
            end_to_end=ratio(total.end_to_end, total.expected),
            approx=ratio(total.approx, total.found),
            seconds=total.seconds / len(scores) if scores else 0.0,
        ),
        total,
    )


def _row(name: str, m: Metrics) -> str:
    def pct(v: float) -> str:
        return f"{v:.1%}"

    return (
        f"| {name} | {m.receipts} | {m.expected} | {pct(m.precision)} | {pct(m.recall)} | "
        f"{pct(m.food)} | {pct(m.quantity)} | {pct(m.end_to_end)} | {m.seconds * 1000:.0f} ms |"
    )


def report(text_scores: Sequence[Score], image_scores: Sequence[Score] | None) -> str:
    header = (
        "| Path | Receipts | Items | Line precision | Line recall | Food match | Quantity | "
        "End to end | Time / receipt |\n|---|---|---|---|---|---|---|---|---|"
    )
    rows = [_row("Text (pasted)", summarize(text_scores)[0])]
    dev = [s for s in text_scores if not s.holdout]
    hold = [s for s in text_scores if s.holdout]
    if hold:
        rows.append(_row("Text, tuning set", summarize(dev)[0]))
        rows.append(_row("Text, holdout", summarize(hold)[0]))
    if image_scores:
        ids = {s.receipt for s in image_scores}
        same = [s for s in text_scores if s.receipt in ids]
        rows.append(_row("Photo (OCR)", summarize(image_scores)[0]))
        hard = [s for s in image_scores if s.receipt in HARD]
        if hard:
            rows.append(_row("Photo, hard renders", summarize(hard)[0]))
        rows.append(_row("Text, same receipts", summarize(same)[0]))
    _, text_total = summarize(text_scores)
    methods = ", ".join(f"{k} {v}" for k, v in text_total.methods.most_common())
    parts = [
        "# Receipt line-item accuracy",
        "",
        "Generated by `make receipt-eval` (`larder-receipt-eval`): the labelled receipts in "
        "`apps/worker/tests/fixtures/receipts` through the production pipeline "
        "(`larder_api.receipts.read_text`) against the seeded database. Definitions in "
        "`larder_worker/evaluate.py`; method and caveats in "
        "[ADR-0016](adr/0016-receipt-intake.md).",
        "",
        header,
        *rows,
        "",
        f"Text path: matched by {methods}; {summarize(text_scores)[0].approx:.0%} of found "
        "items had no printed size (one typical portion, flagged approximate). Photo times "
        "include OCR on this machine's CPU.",
    ]
    for title, scores in (("Text path", text_scores), ("Photo path", image_scores or [])):
        issues = [i for s in scores for i in s.issues]
        if scores:
            parts += ["", f"## Misses: {title.lower()} ({len(issues)})", ""]
            parts += [f"- {i}" for i in issues] or ["- none"]
    return "\n".join(parts) + "\n"


# --- CI fixture: the foods the matcher can reach ----------------------------------------------

_REACH_SQL = text(
    """
    SELECT id FROM foods
    WHERE kcal IS NOT NULL
      AND NOT (coalesce(category, '') = ANY(:excluded))
      AND (description ILIKE '%' || :q || '%' OR :q <% description)
    """
)


async def write_foods(maker: async_sessionmaker[AsyncSession], path: Path) -> int:
    receipts = load_labels()
    phrases = {
        p for r in receipts for item in parse_receipt(r.text) for p in match_names(item.name)
    }
    aliases = load_aliases()
    ids: set[int] = set(load_receipt_foods().values())
    ids |= {fid for r in receipts for i in r.items for fid in i.foods}
    async with maker() as session:
        for phrase in sorted(phrases):
            if (fid := aliases.get(normalise_name(phrase))) is not None:
                ids.add(fid)
            rows = await session.scalars(
                _REACH_SQL, {"q": phrase.lower(), "excluded": list(NOT_GROCERIES)}
            )
            ids.update(rows)
        foods = (await session.scalars(select(Food).where(Food.id.in_(ids)))).all()
        portions = (
            await session.scalars(select(FoodPortion).where(FoodPortion.food_id.in_(ids)))
        ).all()
    payload: dict[str, Any] = {
        "foods": [
            [f.id, f.description, f.data_type, f.category, f.kcal]
            for f in sorted(foods, key=lambda f: f.id)
        ],
        "portions": [
            [p.food_id, p.amount, p.unit, p.qualifier, p.grams]
            for p in sorted(portions, key=lambda p: p.id)
        ],
    }
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    return len(foods)


async def load_foods(session: AsyncSession, path: Path = FIXTURES / "foods.json.gz") -> None:
    """Insert the fixture foods (tests)."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        payload = json.load(f)
    session.add_all(
        Food(id=i, description=d, data_type=t, category=c, kcal=k)
        for i, d, t, c, k in payload["foods"]
    )
    await session.flush()
    session.add_all(
        FoodPortion(food_id=fid, amount=a, unit=u, qualifier=q, grams=g)
        for fid, a, u, q, g in payload["portions"]
    )
    await session.commit()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="larder-receipt-eval", description=__doc__)
    parser.add_argument("--database-url", default=None, help="default: $DATABASE_URL")
    parser.add_argument("--out", type=Path, default=None, help="write the markdown report here")
    parser.add_argument("--no-images", action="store_true", help="skip the OCR path")
    parser.add_argument("--write-foods", type=Path, default=None, help="dump the CI food subset")
    args = parser.parse_args(argv)

    async def run() -> None:
        engine = make_engine(args.database_url or get_settings().database_url)
        maker = make_sessionmaker(engine)
        try:
            if args.write_foods is not None:
                n = await write_foods(maker, args.write_foods)
                print(f"wrote {n} foods to {args.write_foods}")
                return
            receipts = load_labels()
            text_scores = await run_text(maker, receipts)
            image_scores = None if args.no_images else (await run_images(maker, receipts))[0]
        finally:
            await engine.dispose()
        markdown = report(text_scores, image_scores)
        print(markdown)
        if args.out is not None:
            args.out.write_text(markdown, encoding="utf-8")

    asyncio.run(run())


if __name__ == "__main__":
    main()

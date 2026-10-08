"""How good is the automatic matcher on its own? Scored against the hand-curated aliases.

For every curated name that maps to the same food (approximations excluded), run retrieval +
rerank without the alias table and compare. Sweeping the acceptance threshold gives the
precision / coverage trade-off used to pick `matching.ACCEPT_THRESHOLD`.
"""

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from larder_data import matching
from larder_data.embeddings import Embedder
from larder_db.models import Food

THRESHOLDS = (0.80, 0.84, 0.86, 0.88, 0.90, 0.92, 0.95, 1.0)


@dataclass(frozen=True, slots=True)
class ThresholdRow:
    threshold: float
    accepted: int
    correct: int
    equivalent: int

    @property
    def precision(self) -> float:
        return self.correct / self.accepted if self.accepted else 0.0

    @property
    def equivalent_precision(self) -> float:
        return self.equivalent / self.accepted if self.accepted else 0.0


@dataclass(frozen=True, slots=True)
class Evaluation:
    names: int
    top1_correct: int
    top1_equivalent: int
    rows: list[ThresholdRow]

    @property
    def top1_accuracy(self) -> float:
        return self.top1_correct / self.names if self.names else 0.0

    @property
    def top1_equivalent_accuracy(self) -> float:
        return self.top1_equivalent / self.names if self.names else 0.0


def _same_food(a: str, b: str) -> bool:
    """Foundation and SR Legacy repeat foods under different ids; compare descriptions."""

    def key(s: str) -> str:
        return re.sub(r"\s*\(includes foods for usda.*$", "", s.lower()).strip()

    return key(a) == key(b)


def _equivalent(c: matching.Candidate, gold: Food) -> bool:
    """Nutritionally interchangeable for planning: same USDA category, energy within 25%."""
    if c.category != gold.category or c.kcal is None or gold.kcal is None:
        return False
    return abs(c.kcal - gold.kcal) <= 0.25 * max(gold.kcal, 1.0)


async def evaluate(session: AsyncSession, embedder: Embedder) -> Evaluation:
    gold = [a for a in matching.load_alias_rows() if not a.approximation]
    foods = {
        f.id: f
        for f in await session.scalars(select(Food).where(Food.id.in_([a.fdc_id for a in gold])))
    }
    vectors = embedder.embed([matching.rewrite(a.name) for a in gold])
    predictions: list[tuple[float, bool, bool]] = []
    for alias, vector in zip(gold, vectors, strict=True):
        found = await matching.rank(session, alias.name, vector)
        if found is None:
            predictions.append((float("-inf"), False, False))
            continue
        candidate, score = found
        correct = candidate.food_id == alias.fdc_id or _same_food(
            candidate.description, alias.description
        )
        predictions.append((score, correct, correct or _equivalent(candidate, foods[alias.fdc_id])))

    rows = [
        ThresholdRow(
            t,
            accepted=sum(1 for s, _, _ in predictions if s >= t),
            correct=sum(1 for s, ok, _ in predictions if s >= t and ok),
            equivalent=sum(1 for s, _, eq in predictions if s >= t and eq),
        )
        for t in THRESHOLDS
    ]
    return Evaluation(
        len(gold),
        sum(1 for _, ok, _ in predictions if ok),
        sum(1 for _, _, eq in predictions if eq),
        rows,
    )


def render(e: Evaluation) -> str:
    out = [
        "## Matcher accuracy without the alias table",
        "",
        f"Scored on {e.names} hand-curated names (approximations excluded). Top-1: "
        f"{100 * e.top1_accuracy:.1f}% the curated food, {100 * e.top1_equivalent_accuracy:.1f}% "
        "the curated food or a nutritional equivalent (same USDA category, energy within 25%).",
        "",
        "| Threshold | Accepted | Exact precision | Equivalent precision | Coverage |",
        "|---|---|---|---|---|",
    ]
    for r in e.rows:
        out.append(
            f"| {r.threshold:.2f} | {r.accepted} | {100 * r.precision:.1f}% "
            f"| {100 * r.equivalent_precision:.1f}% | {100 * r.accepted / e.names:.1f}% |"
        )
    return "\n".join(out) + "\n"

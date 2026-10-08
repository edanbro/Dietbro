import hashlib
import math
from collections.abc import Sequence

from larder_db.models import EMBEDDING_DIM


class FakeEmbedder:
    """Deterministic bag-of-words vectors: texts sharing words are similar."""

    model = "fake"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            v = [0.0] * EMBEDDING_DIM
            for word in text.lower().replace(",", " ").split():
                v[int(hashlib.sha1(word.encode()).hexdigest(), 16) % EMBEDDING_DIM] += 1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return out

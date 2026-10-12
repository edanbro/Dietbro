"""Receipt photo -> text lines, offline (RapidOCR: PP-OCR det/cls/rec models on onnxruntime,
bundled in the `rapidocr` wheel; no network, no API key). docs/adr/0016-receipt-intake.md.

The photo is decoded with Pillow (EXIF rotation applied, alpha dropped) and scaled so its long
side is at most `max_side` px. OCR returns text boxes; receipts need lines, so boxes are
grouped by their vertical centre after removing the page's skew (the median slope of the
boxes' top edges), then joined left to right. The result is what a pasted receipt looks like,
and goes through the same parser.
"""

import logging
from dataclasses import dataclass
from io import BytesIO
from statistics import median
from threading import Lock
from typing import Any

import numpy as np
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

for name in ("RapidOCR", "rapidocr"):
    logging.getLogger(name).setLevel(logging.WARNING)


class UnreadableImage(Exception):
    """Not an image Pillow can decode."""


@dataclass(frozen=True, slots=True)
class Box:
    """One text box: its corners (clockwise from top-left) and text."""

    points: tuple[tuple[float, float], ...]
    text: str

    @property
    def left(self) -> float:
        return min(x for x, _ in self.points)

    @property
    def centre(self) -> tuple[float, float]:
        xs = [x for x, _ in self.points]
        ys = [y for _, y in self.points]
        return sum(xs) / len(xs), sum(ys) / len(ys)

    @property
    def height(self) -> float:
        (x0, y0), (_, _), (_, _), (x3, y3) = self.points[:4]
        return float(np.hypot(x3 - x0, y3 - y0))

    @property
    def slope(self) -> float:
        (x0, y0), (x1, y1) = self.points[0], self.points[1]
        return (y1 - y0) / (x1 - x0) if x1 != x0 else 0.0


def group_lines(boxes: list[Box]) -> list[str]:
    """Text boxes -> lines of text, top to bottom. A box joins a line when its deskewed centre
    is within half a box height of the line's."""
    if not boxes:
        return []
    skew = median(b.slope for b in boxes)
    tall = median(b.height for b in boxes) or 1.0
    placed = sorted(
        ((b.centre[1] - skew * b.centre[0], b) for b in boxes), key=lambda pair: pair[0]
    )
    lines: list[list[tuple[float, Box]]] = []
    for y, box in placed:
        if lines and abs(y - median(p[0] for p in lines[-1])) < tall * 0.5:
            lines[-1].append((y, box))
        else:
            lines.append([(y, box)])
    return [
        "  ".join(b.text.strip() for _, b in sorted(line, key=lambda p: p[1].left))
        for line in lines
    ]


def load_image(data: bytes, max_side: int) -> Any:
    """Decoded RGB pixels (numpy array), upright and at most `max_side` px on the long side."""
    try:
        with Image.open(BytesIO(data)) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
    except Exception as exc:  # Pillow raises several types for bad input
        raise UnreadableImage(str(exc)) from exc
    image.thumbnail((max_side, max_side))
    return np.asarray(image)


class Ocr:
    """Lazily loaded OCR engine (models load in ~1 s; one instance per worker process).
    `read` is blocking and CPU-bound: call it from a thread."""

    def __init__(self, max_side: int = 2000) -> None:
        self.max_side = max_side
        self._engine: Any = None
        self._lock = Lock()

    def engine(self) -> Any:
        with self._lock:
            if self._engine is None:
                from rapidocr import RapidOCR  # heavy import; only workers pay for it

                self._engine = RapidOCR(params={"Global.log_level": "warning"})
            return self._engine

    def boxes(self, data: bytes) -> list[Box]:
        result: Any = self.engine()(load_image(data, self.max_side))
        if result.boxes is None or result.txts is None:
            return []
        return [
            Box(tuple((float(x), float(y)) for x, y in points), str(text))
            for points, text in zip(result.boxes, result.txts, strict=True)
            if str(text).strip()
        ]

    def read(self, data: bytes) -> str:
        """The photo's text, one receipt line per line."""
        return "\n".join(group_lines(self.boxes(data)))

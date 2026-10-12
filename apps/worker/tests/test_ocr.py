"""OCR boxes -> receipt lines, and the OCR engine on a rendered receipt (skipped if the bundled
models can't load)."""

from pathlib import Path

import pytest

from larder_worker.evaluate import FIXTURES
from larder_worker.ocr import Box, Ocr, UnreadableImage, group_lines, load_image


def box(
    x: float, y: float, text: str, width: float = 100, height: float = 20, slope: float = 0
) -> Box:
    rise = slope * width
    return Box(
        ((x, y), (x + width, y + rise), (x + width, y + rise + height), (x, y + height)),
        text,
    )


def test_boxes_on_one_line_are_joined_left_to_right() -> None:
    boxes = [
        box(300, 52, "1.45"),
        box(10, 50, "SEMI SKMD MILK"),
        box(10, 90, "TOTAL"),
        box(300, 91, "1.45"),
    ]

    assert group_lines(boxes) == ["SEMI SKMD MILK  1.45", "TOTAL  1.45"]


def test_skew_is_removed_before_grouping() -> None:
    # A page tilted ~3 degrees: the price at the right sits 15 px lower than its name.
    slope = 0.05
    boxes = [
        box(10, 50, "CHKN BRST", slope=slope),
        box(310, 50 + 300 * slope, "4.75", slope=slope),
        box(10, 80, "BANANAS", slope=slope),
        box(310, 80 + 300 * slope, "0.68", slope=slope),
    ]

    assert group_lines(boxes) == ["CHKN BRST  4.75", "BANANAS  0.68"]


def test_no_boxes_no_lines() -> None:
    assert group_lines([]) == []


def test_garbage_is_not_an_image() -> None:
    with pytest.raises(UnreadableImage):
        load_image(b"not a picture", 2000)


def test_large_photos_are_scaled_down() -> None:
    pixels = load_image((FIXTURES / "r01_tesco.jpg").read_bytes(), 400)

    assert max(pixels.shape[:2]) == 400


@pytest.fixture(scope="module")
def ocr() -> Ocr:
    engine = Ocr()
    try:
        engine.engine()
    except Exception as exc:  # models missing or onnxruntime unavailable on this platform
        pytest.skip(f"OCR engine unavailable: {exc}")
    return engine


def test_reads_a_rendered_receipt(ocr: Ocr) -> None:
    text = ocr.read(Path(FIXTURES / "r01_tesco.jpg").read_bytes())

    lines = text.splitlines()
    assert any("SKMD MILK" in line and "1.45" in line for line in lines), text
    assert any(line.startswith("TOTAL") for line in lines), text

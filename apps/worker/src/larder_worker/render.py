"""Render labelled receipt texts as photo-like JPEGs for the OCR half of the accuracy eval.

`python -m larder_worker.render r01_tesco r13_walmart ...` writes `<id>.jpg` next to the text
in apps/worker/tests/fixtures/receipts. The images are committed, so the eval needs no fonts;
this needs the fonts below (Debian: fonts-dejavu-core, fonts-liberation, fonts-freefont-ttf).

Each receipt gets its own seeded variation: thermal-printer-like monospace font and size, paper
tint on a darker table, a slight rotation, uneven lighting, sensor noise, a little blur and
JPEG compression; the receipts in evaluate.HARD get small type, a 4-6 degree tilt, heavy noise
and blur. Not a substitute for real photos (no crumples, curl or glare), so the photo numbers are
an upper bound for flat photos.
"""

import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from larder_worker.evaluate import FIXTURES, HARD

FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeMonoBold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
]


def render(text: str, seed: str, *, hard: bool = False) -> Image.Image:
    rng = random.Random(seed)
    size = rng.randint(15, 17) if hard else rng.randint(19, 24)
    font = ImageFont.truetype(rng.choice(FONTS), size)
    lines = text.rstrip("\n").splitlines()
    left, top, right, bottom = font.getbbox("M" * 48)
    line_h = round((bottom - top) * rng.uniform(1.35, 1.6))
    paper_w = round(right - left) + 60
    paper_h = line_h * len(lines) + 80
    paper = Image.new("L", (paper_w, paper_h), rng.randint(232, 250))
    draw = ImageDraw.Draw(paper)
    ink = rng.randint(20, 70)
    for i, line in enumerate(lines):
        draw.text((30, 40 + i * line_h), line, font=font, fill=ink)

    table = Image.new("L", (paper_w + 160, paper_h + 160), rng.randint(70, 130))
    table.paste(paper, (80, 80))
    tilt = rng.choice((-1, 1)) * rng.uniform(4, 6) if hard else rng.uniform(-2.5, 2.5)
    photo = table.rotate(
        tilt, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=rng.randint(70, 130)
    )
    pixels = np.asarray(photo, dtype=np.float32)
    h, w = pixels.shape
    light = np.linspace(rng.uniform(0.8, 0.95), rng.uniform(1.0, 1.08), w)[None, :]
    light = light * np.linspace(rng.uniform(0.9, 1.0), rng.uniform(0.95, 1.05), h)[:, None]
    np_rng = np.random.default_rng(rng.randint(0, 2**32 - 1))
    sigma = rng.uniform(14, 20) if hard else rng.uniform(4, 10)
    noisy = pixels * light + np_rng.normal(0, sigma, pixels.shape)
    out = Image.fromarray(np.clip(noisy, 0, 255).astype(np.uint8), "L")
    blur = rng.uniform(1.0, 1.4) if hard else rng.uniform(0.3, 0.9)
    return out.filter(ImageFilter.GaussianBlur(blur)).convert("RGB")


def main(argv: list[str] | None = None) -> None:
    ids = (argv if argv is not None else sys.argv[1:]) or []
    for receipt_id in ids:
        source: Path = FIXTURES / f"{receipt_id}.txt"
        hard = receipt_id in HARD
        image = render(source.read_text(encoding="utf-8"), receipt_id, hard=hard)
        target = FIXTURES / f"{receipt_id}.jpg"
        image.save(target, quality=55 if hard else random.Random(receipt_id).randint(70, 85))
        print(f"{target} {image.size[0]}x{image.size[1]} {target.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()

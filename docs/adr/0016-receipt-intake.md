# ADR-0016: Receipt intake - offline OCR in an arq worker, rule-based parsing, review before pantry

- Status: Accepted
- Date: 2026-10-11

## Context

M6 ("pantry intake") asks for receipt or photo upload -> a worker job -> a review screen ->
pantry items, expiry alerts, and a measured line-item accuracy. PLAN §7 sketched Claude vision
for reading receipts. The user chose free OCR instead: no paid API, no key, works offline, so
intake costs nothing per receipt and works in CI and on a self-hosted box. Receipts are
personal data (store, time, sometimes the card's last digits), and the photo is the most
sensitive part.

Options for reading the photo:

1. **Claude vision** (PLAN §7): best on crumpled, curled or odd receipts, reads and structures in
   one step; but paid per image, needs a key, and sends the photo to a third party.
2. **Tesseract** (apt package + pytesseract): mature, small (~30 MB with English data), but weak
   on photos without careful preprocessing (binarisation, deskew, DPI), and a system package to
   keep in the image.
3. **RapidOCR** (chosen): PaddleOCR's PP-OCR detection, angle and recognition models on
   onnxruntime, models bundled in the pip wheel. Pure pip, no system packages, robust to photos
   (it detects text boxes before reading them). onnxruntime is already in the tree (fastembed).

The `rapidocr-onnxruntime` package named in the plan is the project's deprecated 1.x line: it
caps Python below 3.13 (uv resolves the workspace for >=3.12, so it would need markers) and
pulls the GUI `opencv-python`, which needs libGL in a slim image. Its successor `rapidocr` 3.x is
the same project with `opencv-python-headless` and newer bundled models (PP-OCRv6 small det/rec,
~32 MB), so we use `rapidocr==3.10.0` (pinned: the models ship in the wheel, so an upgrade is an
accuracy change to re-measure). Tesseract stays the fallback if RapidOCR ever stops installing.

Options for parsing the text: an LLM (accurate on odd formats, but paid and online, the thing
we're avoiding) or rules (chosen): receipts are line-oriented and formulaic (name, size, price,
tax flag), and the hard part, deciding which USDA food a line is, already has an offline matcher.

## Decision

- **Pipeline** (DESIGN §7.1): `POST /pantry/receipts/image` (JPEG/PNG/WebP sniffed from the
  bytes, <= 8 MB, HEIC refused with advice) or `POST /pantry/receipts/text` stores an upload
  (`receipt_uploads`, status `queued`) and enqueues `read_receipt(upload_id)` on Redis with arq.
  The worker OCRs photos and runs the shared pipeline (`larder_api.receipts`): parse
  (`larder_core.receipts`), match foods, amounts from USDA portions, suggested use-by
  (`larder_core.shelf_life`). Lines land in `receipt_lines` (`suggested`); the user reviews
  (`PATCH .../lines/{id}`: food, quantity/unit, date, accept/reject) and confirms, which creates
  pantry items (`source = receipt`, `approx` when the size wasn't printed).
- **Worker**: a new workspace member `apps/worker` (PLAN §4 layout), `arq
  larder_worker.main.WorkerSettings`, same Dockerfile with a `worker` target so OCR's ~330 MB
  of dependencies (opencv-headless, onnxruntime, models, numpy) are only in the worker image.
  The API only needs arq to enqueue. Job ids are `receipt:<id>` (a duplicate enqueue is a no-op)
  and the job is idempotent: it claims the upload with a conditional UPDATE, replaces its lines
  in one transaction and skips uploads deleted meanwhile. One retry if the worker dies; a cron
  sweep fails uploads stuck past 15 minutes. Failures are recorded on the upload with a message
  for the user. arq 0.28 caps redis-py below 6; we override that to the API's redis-py 8 (uv
  `override-dependencies`) and exercise enqueue, the worker loop and job dedupe in the compose
  smoke test.
- **Privacy**: the photo is stored (bytea, deferred) only until the worker has read it, then
  set to NULL whether reading succeeded or failed (also when the queue is down or the sweep
  fails it); only its size and type are kept. The text read from it is kept for review and
  dropped on confirm (it includes payment lines); the item lines stay. Uploads and lines are in
  the GDPR export and cascade on account deletion. Receipt text is data: it only becomes search
  terms for the matcher; no model ever sees it. 20 uploads per user per 24 h.
- **Parsing** (rules, tests first): keep lines with a name and a price; drop headers, totals,
  VAT/tax, payment, change, loyalty and savings (negative prices) by keyword and shape; read
  follow-on lines (`2 @ 0.46`, `0.352 kg @ £1.10/kg`), sizes (`500G`, `4PT`, `2 GAL`, `15OZ`),
  packs (`4X420G`, `6PK`, `12CT`, `1 DOZ`, `EGGS 6`), quantity columns; strip item codes, tax
  flags, store brands and marketing words; expand a curated abbreviation table (SKMD, CHKN,
  BRST, TOMS...) and brand-implies-food words (Warburtons -> bread); fix common OCR confusions
  (`80Z` -> 8 oz, `KR0`).
- **Matching** (offline, no model): receipt vocabulary (`receipt_foods.csv`, shop names such as
  "semi skimmed" or "chopped tomato" -> the tinned food) and the curated recipe aliases on the
  whole name; else a trigram clear winner among grocery categories that starts with one of the
  name's words and isn't a cooked form; else the tables on shorter phrases, longest and rightmost
  first (`partial`). Unmatched lines stay for the user to pick a food.
- **Amounts**: printed metric sizes are kept as the pantry quantity (`1.5 kg`), imperial ones
  converted (`8 oz` -> 227 g, pints/gallons -> ml); piece counts use the food's count portion
  (`6 large` eggs); without a size, one typical portion, flagged approximate. The quantity/unit
  is checked to convert back through the pantry's own conversion, else stored in grams.
- **Expiry**: a small shelf-life table by USDA category with keyword overrides (poultry and fish
  2 days, red meat 3, dairy 7, hard cheese and eggs 21, produce 5 with berries 3 and onions 21,
  bread 4; frozen, tinned and dry goods none), documented in `larder_core.shelf_life`. Alerts:
  `GET /pantry/expiring?days=3` and `expiring_soon` on `GET /me`. The planner already prefers
  soon-expiring pantry food (prefilter bonus for lots expiring within 3 days, the objective's
  waste term), so intake feeds planning without solver changes.
- **Accuracy** is measured, not asserted: 25 labelled receipts (20 for tuning, 5 written after
  as a holdout) in UK and US formats, 11 also rendered as photo-like JPEGs (3 of them hard:
  small type, 4-6 degree tilt, noise, blur). `make receipt-eval` writes
  `docs/receipt-accuracy.md`; a CI test holds the text path to a floor against a fixture of the
  foods the matcher can reach.

Migration 0006: `receipt_uploads`, `receipt_lines`.

## Consequences

- Free and offline; the cost is a ~1.4 s CPU OCR per photo in the worker (two jobs at a time)
  and a 1.12 GB worker image (the API's stays at 681 MB, +1 MB for arq and multipart parsing).
- The photo numbers come from rendered images (flat, evenly lit): an upper bound. Real photos
  (crumples, curl, glare, thermal fade) need a labelled set of real receipts; the eval takes
  JPEGs next to the text, so adding them is a data change.
- The vocabulary tables are curated by hand and will grow with real receipts; the tuning set
  scores higher than the holdout, as expected. Unknown names fall back to the user's pick.
- Count-based amounts depend on USDA's typical weights (a USDA leek is 89 g), so loose produce
  is often approximate; the review screen shows `approx` and the user can fix it.
- A Claude-vision path can be added later behind the same worker job (a key and a per-user
  budget, as in the chat) for receipts the rules can't read.

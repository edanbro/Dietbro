# Progress

One short demo note per milestone: what works, how to see it.

## M0 — Foundations

**What works**
- Monorepo: uv workspace (`apps/api`, `packages/core`) + pnpm workspace (`apps/web`).
- `docker compose up` → Postgres 17 + pgvector, Redis, FastAPI on :8000, Next.js on :3000.
- API: `GET /healthz` (liveness), `GET /readyz` (Postgres + Redis checks, 503 when degraded).
- Web: home page shows live API status, fetched server-side with a client typed from the API's
  OpenAPI schema.
- CI on every PR: Python (ruff, pyright strict, pytest), web (eslint, tsc, vitest, build),
  API contract drift check, pre-commit (incl. gitleaks), Docker build + compose smoke test.

**See it**
```sh
docker compose up --build
curl localhost:8000/readyz   # {"status":"ok","checks":{"database":"ok","redis":"ok"}}
open http://localhost:3000   # "API: ok"
```

**Docs**: [DESIGN.md](DESIGN.md) skeleton; ADRs [0001](adr/0001-record-architecture-decisions.md),
[0002](adr/0002-hybrid-llm-constraint-solver.md), [0003](adr/0003-monorepo-tooling.md).

**Next (M1)**: schema + Alembic, USDA importer, recipe seed, unit conversion, ingredient normaliser.

## M1 — Data

**What works**
- Schema + Alembic migrations (`packages/db`): foods, portions, recipes, ingredient lines, tags,
  pgvector embeddings, match cache. A test fails if models and migrations drift.
- `uv run larder-data pipeline` (or `make data`), ~4 min from an empty database:
  USDA Foundation + SR Legacy import (8,262 foods, 14.6k portion weights) → local embeddings →
  TheMealDB import (790 recipes, 8,152 ingredient lines) → resolve every line to food + grams →
  recipe embeddings → report.
- Units: measure parser + conversions in `packages/core`, with Hypothesis property tests.
- Recipe nutrition per serving; recipes with every line resolved are flagged plannable.

**Numbers** ([full report](data-report.md))

| | |
|---|---|
| Lines resolved to a USDA food | **99.6%** (target ≥ 95%) |
| …via the curated alias table / automatic matcher | 94.6% / 5.0% |
| Lines with grams | 98.4% |
| Plannable recipes (complete nutrition) | 667 / 790 |
| Matcher alone vs curated names: equivalent precision at threshold | 87% |

**See it**
```sh
docker compose up -d db
make data            # migrate + pipeline + report (fails below 95%)
```
CI: the `Data pipeline` workflow runs the same thing weekly and on PRs touching data code, and
posts the report to the job summary.

**Docs**: DESIGN §5–6; ADRs [0004](adr/0004-shared-schema-package.md),
[0005](adr/0005-local-embeddings.md), [0006](adr/0006-ingredient-matching.md).

**Known gaps**: canned vs dried pulses are not distinguished; servings are estimated from energy
(TheMealDB has none); 123 recipes still have an unresolved line. LLM tiebreak lands in M4.

**Next (M2)**: auth, user scoping, pantry/goals/preferences/allergies CRUD + mobile UI.

## M2 — Accounts, profile, pantry

**What works**
- Sign-up / sign-in with Clerk; the API verifies session JWTs itself and scopes every query to
  the signed-in user (cross-user reads are 404s, tested).
- Mobile-first web app (installable PWA): 5-step setup on first sign-in, then Pantry and
  Profile tabs.
  - Goals: daily kcal band, optional protein minimum, weekly budget; unsafe targets are refused
    with the reason (calorie floor, max deficit vs estimated needs, impossible macros).
  - Optional body stats → estimated daily needs and one-tap suggested targets.
  - Allergies (EU/UK 14 + any specific foods) as hard constraints; diet and cuisine likes.
  - Pantry: type-ahead USDA search (curated names first), quantity in the food's own units
    ("2 large" onions = 300 g, "3 cloves" garlic), use-by dates with expiry badges, rough-amount
    flag.
  - Download my data (JSON) and delete my account.
- `docker compose up` now runs migrations first; `make seed` loads foods + recipes (~1 min).

**Tests**: 42 API tests (auth edge cases, scoping, safety rules, pantry conversions), property
tests for the energy maths, 21 web component tests, and a Playwright onboarding test on a Pixel 7
profile (CI job enabled by Clerk secrets).

**See it**
```sh
cp .env.example .env   # add your Clerk dev instance keys
docker compose up --build
make seed              # in another terminal
open http://localhost:3000
```

**Docs**: DESIGN §5, §7, §10; ADRs [0007](adr/0007-clerk-auth-and-user-scoping.md),
[0008](adr/0008-calorie-target-safety.md).

**Known gaps**: the e2e test needs `CLERK_PUBLISHABLE_KEY` + `CLERK_SECRET_KEY` repo secrets to
run in CI; liked/disliked *foods* are stored but have no UI yet (cuisines and diet do); no offline
mode in the PWA.

**Next (M3)**: CP-SAT weekly plan, independent validator, shopping list, plan view.

## M3 — Planning (in progress: CP-SAT `solve()` is Eduard's to write)

**What works**
- "Plan my week" on the phone: a 7-day plan (breakfast, lunch, dinner, optional snack) that
  respects allergies, diet and avoided foods, never goes under the calorie floor, stays in the
  daily kcal band, prefers liked cuisines and what's in the pantry, and explains itself: macro
  bars against the targets, "planned without: peanuts · vegetarian", cost against budget.
- Week grid and day view, recipe pages (derived allergens, suitable diets), and a shopping list
  grouped by aisle with ticks, estimated cost and a "check you have" staples section.
- Plans are versioned snapshots: re-planning makes a new version and never edits an old one.
- Today the plans come from a greedy **baseline** (`PLANNER=auto` falls back to it while
  `solve()` raises NotImplementedError). Every plan, from any planner, goes through the
  independent validator; a plan with a safety or structural violation is never saved.

**For the CP-SAT model** (`packages/solver`): the integer problem contract, the validator, metrics
(earliest-deadline-first pantry allocation, score), the prefilter, test scenarios with known
answers and decoys, and a failing tests-first spec (`tests/test_solve.py`, 62 cases) plus a
modelling guide (`packages/solver/README.md`). M3's gates, once `solve()` passes the spec:
validator passes 100% of generated scenarios; `make bench PLANNER=cpsat` end-to-end p95 < 5 s.

**Data**: allergen/diet tags from conservative rules + reviewed data (every approximate or
automatic ingredient match in a plannable recipe reviewed; tags also read recipe names and
instructions — "Egg Drop Soup" lists no egg); estimated UK prices; 57 curated breakfasts and
snacks so every common allergy/diet combination has a week of breakfasts; recipes with broken
nutrition (frying oil, missing main ingredient) excluded and listed in the data report.

**Numbers** (`docs/solver-bench-greedy.md`): the baseline plans in ~25 ms (p95 ~40 ms), meets
every hard rule on planted and realistic scenarios, and misses only tight budgets.

**See it**
```sh
docker compose up --build && make seed
open http://localhost:3000            # set up a profile, then "Plan my week"
make bench PLANNER=greedy             # planner benchmark
uv run pytest packages/solver/tests/test_solve.py   # the CP-SAT spec (xfails until solve() exists)
```

**Docs**: DESIGN §5, §7, §8; ADRs [0009](adr/0009-planning-contract.md),
[0010](adr/0010-meal-slots-and-curated-recipes.md), [0011](adr/0011-allergen-diet-tagging.md),
[0012](adr/0012-price-estimates.md).

**Known gaps**: costs are pro rata (no pack sizes); macro targets are soft; locks/eaten meals
and replanning with churn arrive in M5; the CP-SAT planner itself.

## M4 — LLM layer (chat that re-plans)

**What works**
- A Chat tab: tell it "craving something spicy tonight", "had 2 slices of pizza for lunch",
  "eating out Friday" or "swap Thursday's dinner", or ask why a meal is planned. Replies stream
  in; a card shows exactly what changed (meal by meal, with kcal estimates for logged food) and
  links to the plan, which now shows logged and skipped meals.
- The model (Claude Sonnet 5.5) never writes a plan: it calls typed tools (search recipes,
  request a replan, draft a recipe, explain a meal or a diff). One executor applies the changes:
  it replans only from today on, rebuilds earlier logs and pins, runs the planner and the same
  independent validator, and saves a new version. Claude Haiku 5.5 only picks among USDA foods we
  offer it; nutrition is always ours.
- Recipes the assistant drafts must match USDA foods and pass the planner's own allergen/diet
  gate; they are private to their owner.
- Without an API key (CI, self-hosting) or over the per-user budget, the chat runs offline: a
  rule parser (69-phrase test table) drives the same executor with templated replies.
- Limits and accounting: every model call is logged with tokens, cost and latency; 60 messages
  per user per 24 h, $1 per user per month (paced), $0.10 per turn.

**Done criteria**
- Chat handles craving / off-plan / swap / skip: API tests for each intent in both modes
  (scripted models and the offline path) and an offline-mode Playwright test on a phone.
- Zero allergen violations in tests: `assert_user_safe` recomputes allergens, diet and avoided
  foods from stored rows after the chat tests; adversarial scripts (unsafe or foreign recipe
  ids, disguised allergens in drafted recipes, injected instructions in messages and recipe
  text, failures after a write) save nothing unsafe.

**See it**
```sh
docker compose up --build && make seed
open http://localhost:3000/chat       # "skip dinner tonight", then open the plan
make llm-smoke                        # with ANTHROPIC_API_KEY in .env: 4 real turns + cost
```

**Docs**: DESIGN §9; ADRs [0013](adr/0013-llm-layer.md) (agent, typed tools, offline path,
transcript, limits), [0014](adr/0014-chat-replans.md) (open-horizon replans, `day_kcal`,
`choices`); `solve()` spec gained 13 cases for them.

**Known gaps**: `make llm-smoke` hasn't been run against Claude yet (needs a key); M5 brings the
<1 s replan target, warm starts, a craving bonus in the objective and the diff view; the CP-SAT
planner itself.

## M5 — Real-time replan

**What works**
- Replans without the chat: `POST /plans/replan` takes the same typed changes (skip, swap,
  craving, food eaten off-plan) and runs the chat's executor, so the plan screen gets the same
  results, new version and meal-by-meal diff. One change at a time per user (shared with the
  chat), safe to resend (`client_id`).
- Mark a meal eaten (and undo): logged as eaten, shown on the plan, its ingredients taken from
  the pantry (soonest-expiring first, never below zero); undo gives back exactly what was taken.
  Later replans keep eaten meals and count them once.
- Latency is measured on every replan (`Server-Timing`, logs, `stats.total_ms`).
- On the plan screen (web): each meal card has an options button. Today and earlier: mark
  eaten (a toast says what came out of the pantry; eaten meals get a check badge and can only be
  undone). Today and later: skip (eating elsewhere or not), swap for something else; today:
  "had something else" (a short description, logged off-plan). After a replan a "What changed"
  panel lists each request (done / not done and why), every changed meal with its reason
  ("Thu dinner: Lentil stew → Chilli — rebalanced to keep Thu on target"), logged food, days
  now off target, warnings and notes. One change at a time (buttons wait while one runs); the
  plan, shopping list and pantry reload after each; busy / already-made / stale-plan conflicts
  reload the plan with a toast. Eaten meals show in the week grid, and eaten logs (after a new
  plan) as "Lentil stew (eaten, 540 kcal)" with a link to the recipe.

**Done criteria**
- Replan p95 < 1 s at the API: `make bench-replan` (`docs/replan-bench-greedy.md`) - the
  executor against the seeded database, 40 replans: p50 152 ms, p95 319 ms (greedy planner);
  `scenarios.replan` problems: p95 201 ms. A solver test keeps greedy replans under 1 s p95.
- Average churn reported: 1.5 meals changed per replan through the executor (1.1 asked for,
  0.3 rebalancing); on `scenarios.replan` 6.9 slots vs `previous` (2.0 forced) - the number
  CP-SAT's warm start should bring down (spec test 17).

- Web tests: `meal-actions.test.tsx` and `what-changed.test.tsx` (options per day, pending
  state, toasts, request bodies, 409 handling, the diff lines); Playwright `e2e/replan.e2e.ts`
  marks today's breakfast eaten and undoes it, then skips tomorrow's dinner (valid at any hour)
  and checks the "What changed" panel and the skip on the plan.

**Docs**: DESIGN §5, §7, §9.3, §11; [ADR-0015](adr/0015-eaten-and-app-replans.md); solver
README section 7 (warm start). Migration 0005.

**Known gaps**: `solve()` and its warm start (replan time limit to lower then); a craving bonus
in the objective; swaps from the plan screen are "anything else" (no dish or tag picker yet);
the replan e2e hasn't run against a live Clerk instance from this branch yet.

## M6 — Pantry intake

**What works**
- Add groceries from a receipt: upload a photo (`POST /pantry/receipts/image`, JPEG/PNG/WebP up
  to 8 MB) or paste the text (`POST /pantry/receipts/text`, e.g. an online order). The worker
  (`apps/worker`, arq on Redis, compose service `worker`) reads it - photos with offline OCR
  (RapidOCR; free, no key, nothing leaves the box) - and the API serves the suggested lines:
  food, quantity and unit, grams (approximate when no size was printed), price, suggested
  use-by. Review each line (change the food, the amount or the date, accept or reject), then
  confirm: the lines go into the pantry as `source: receipt`. Photos are deleted as soon as
  they've been read; 20 receipts per user per day.
- Expiry alerts: `GET /pantry/expiring?days=3` (expired and soon-expiring, days left), and
  `expiring_soon` on `GET /me` for a badge. The planner already prefers food that expires soon.
- Receipt uploads and lines are in the data export and go with account deletion.
- Web (phone-first): "Add from receipt" on the pantry page opens `/pantry/receipts` with two
  tabs, Photo (take one with the back camera or choose one; type and 8 MB checked before
  upload, HEIC explained) and Paste text, plus the purchase date (today, local). The receipt
  page (`/pantry/receipts/{id}`) polls while the worker reads it (every 0.5 s for text, 1.5 s
  for photos; stops on ready/failed/confirmed; after 60 s says it's taking too long, with
  "Check again" and delete). Review: each line shows the matched food (or "No match — pick a
  food"), the printed line, amount, use-by and an approx flag; edit (food search shared with
  manual add, quantity/unit, use-by, rough amount) or reject/restore; "N items will be added"
  (unmatched lines are skipped); confirm toasts "Added N items to your pantry" and returns to
  the pantry, refreshing pantry, alerts and the badge. Failed receipts show the reason with
  retry and delete; recent receipts are listed (reopen one to review). The pantry page shows a
  "Use soon" card (expired / expiring within 3 days, "expires tomorrow", "expired 2 days
  ago"), and the Pantry tab in the bottom nav carries a count from `expiring_soon`.

**Done criterion: measured line-item accuracy** ([receipt-accuracy.md](receipt-accuracy.md),
`make receipt-eval`): 25 labelled UK/US receipts (209 items; 5 receipts written after tuning as a
holdout), 11 also as rendered photos.

| Path | Line precision | Line recall | Food match | Amount | End to end |
|---|---|---|---|---|---|
| Pasted text, all 25 | 100% | 100% | 99.0% | 99.0% | 98.1% |
| Pasted text, holdout 5 | 100% | 100% | 94.9% | 100% | 94.9% |
| Photo via OCR, 11 (3 degraded) | 100% | 99.0% | 99.0% | 98.9% | 97.0% |

OCR takes ~1.4 s per photo on CPU. A CI test keeps the pasted-text path above a floor using a
fixture of the USDA foods the matcher can reach; another OCRs three of the photos.

**Also**: `larder_core.quantities.each_weight` no longer counts slices and wedges as "one" of a
food ("1 medium onion" was 62 g, the median of a medium onion and a medium slice; now 110 g).
Recipe grams pick this up the next time `make data` re-resolves the catalogue.

**Docs**: [ADR-0016](adr/0016-receipt-intake.md), DESIGN §4, §5, §7, §7.1, §10. Migration 0006.
Images: the API image only gains arq and python-multipart (680 -> 681 MB); the worker image is
the API's code plus OCR, 1.12 GB (opencv-headless, onnxruntime, numpy and the models add ~290 MB
to the virtualenv).

- Web tests: `receipt-review.test.tsx` (polling until ready and stopping, giving up, failed,
  line counts, reject/restore, edit, picking a food for an unmatched line, confirm),
  `receipt-intake.test.tsx` (photo checks, multipart upload, text submit, upload error and
  retry, recent list), `expiry-alerts.test.tsx`, the nav badge in `app-shell.test.tsx`.
  Playwright `e2e/receipt.e2e.ts` pastes a three-line receipt, waits for the worker, moves the
  milk's use-by to tomorrow, rejects the bananas, confirms, and checks the pantry, the "Use
  soon" card and the badge. The CI e2e job now starts the worker (`arq`, health-checked).

**Known gaps**: the receipt e2e hasn't run against a live Clerk instance from this branch yet;
no client-side image downscaling (phone photos go up as taken, within 8 MB); the photo numbers come from
rendered images (flat, evenly lit), so real photos of crumpled or faded receipts need a labelled
set of real receipts; HEIC photos are refused (iPhones send JPEG from the browser); loose produce
is weighed by USDA's typical item, often approximate.

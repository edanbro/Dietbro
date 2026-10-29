# Mealwright

Meal planner: an LLM for language, a CP-SAT planner for the plan, and an independent validator
that checks every plan. See README.md for the product and docs/DESIGN.md for the architecture.

## Where things stand (update this when a milestone moves)

- M0–M7 are done: data, accounts, the pantry, CP-SAT planning, the chat that re-plans, live
  replans, receipt intake and evals. M0–M6 have demo notes in `docs/progress.md`; M7's numbers
  are in `evals/REPORT.md` and the README's Measured table.
- Since M7, small user-facing features have landed as one PR each: templates, recipe editing
  and notes, micronutrients, price watch, the weekly recap, meal prep, shared shopping lists,
  units, cheaper and favourite swaps. A design pass covered tokens, contrast, keyboard access
  and copy (PRs #64 to #67).
- Next: a security review before hosting (share and calendar tokens, the recipe-import SSRF
  guard, rate limits), then M8 (deploy per `docs/deploy.md` and `render.yaml`, monitoring, load
  numbers), then M9 (beta users). Check with Eduard before anything with running costs.
- The roadmap and its done criteria are in `PLAN.md` §9, and the decisions in `docs/adr/`. Add
  an ADR when choosing between real alternatives.

## Working with Eduard

- Claude is the main coder, solver included. Explain the design choices so Eduard can defend
  them in an interview.
- Work autonomously and don't hand him chores. Open each PR with auto-merge on.
- Keep answers short.

## Layout

- `apps/api`: FastAPI, SQLAlchemy async, Alembic (`larder_api`). Routers live in `routers/` and
  chat in `chat/`; `planning.py` runs the planner and falls back to greedy.
- `apps/web`: Next.js 16, TanStack Query, Tailwind v4 (tokens in `src/app/globals.css`), Clerk.
  The API client types in `src/lib/api/schema.d.ts` are generated, so never edit them by hand.
- `apps/worker`: arq worker (receipt OCR, reminders).
- `packages/solver`: `solve()` (CP-SAT), `greedy`, `validate`, `metrics`. The objective equals
  `metrics.score`.
- `packages/core`, `packages/data`, `packages/db`, `packages/llm`: domain, importers, models and
  prompts.
- `evals/`, `docs/`: the benchmarks and their reports.

## Commands (Windows: Git Bash; there's no `make`, so run the recipe lines directly)

- Everything CI runs, locally: `bash scripts/dev/check.sh`. Add `--visual` to also compare the
  screenshots, and `--py` or `--web` to run one side only.
- Python: `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`
- Web: `pnpm -C apps/web lint && pnpm -C apps/web typecheck && pnpm -C apps/web test`
- After API changes: `make gen-api` (the recipe is in the Makefile), and commit the schema.
- The stack: `docker compose up -d --build` (web on :3000, api on :8000).
- Screenshots: `sh apps/web/scripts/visual.sh [--update-snapshots]`. It needs the stack up and
  runs in the Playwright container. After an update, restore the unrelated drift with
  `git checkout -- apps/web/e2e/__screenshots__/desktop/cook-dark.png`.
- Benches: `sh scripts/dev/with-db.sh uv run larder-bench` (or `... uv run larder-evals
  --catalog db --n 50`). It passes only `DATABASE_URL` from `.env`, pointed at localhost.

## Gotchas

- Docker Desktop may not be running: start
  `C:\Users\spode\AppData\Local\Programs\DockerDesktop\Docker Desktop.exe`, then poll
  `docker info`.
- Repeated local e2e runs hit Clerk's "Too Many Requests"; rely on CI for e2e then.
- Any visible text change breaks the screenshot baselines, so run
  `bash scripts/dev/check.sh --visual` before pushing UI changes.
- Never type into Clerk sign-in in a browser pane; e2e uses Clerk testing tokens.
- Python files are formatted after each edit by the `.claude/settings.json` hook
  (`scripts/dev/format_hook.py`).

## GitHub (the GitHub MCP server is unreliable; these use git's stored credential)

- `sh scripts/dev/gh.sh ...` is gh without `gh auth login`, for example
  `gh.sh pr create --fill` or `gh.sh pr merge N --auto --merge`.
- `main` requires the 6 CI checks, and auto-merge is on. After opening a PR, set auto-merge
  instead of waiting on CI.
- `sh scripts/dev/cilog.sh SHA` prints only the failing jobs' errors.
- `sh scripts/dev/ghapi.sh METHOD PATH [json-file]` calls the REST API, and
  `sh scripts/dev/waitci.sh SHA` blocks until the checks finish. Neither prints the token.

## Conventions

- One branch and PR per step, never push to main, and merge yourself once CI is green.
- Tests come with every change: pytest for Python, vitest beside components, and Playwright in
  `apps/web/e2e`.
- Match the surrounding code's comment density and naming. Comments explain why, not what.
- UI colours come from the semantic tokens (`text-success`, `bg-warning-subtle`, `border-field`
  …), not raw Tailwind palette classes.
- Secrets live only in the git-ignored `.env`, which `.claude/settings.json` denies reading or
  editing; scripts that need a value read it themselves (see `with-db.sh`).
- Ask before anything paid (LLM runs, services) or any heavy dependency.

## Compact instructions

When compacting, keep: the current goal, open PR numbers and branch, files changed, failing
checks with their exact errors, and decisions the user made. Drop old exploration, full logs and
passing test output.

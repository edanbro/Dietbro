#!/usr/bin/env bash
# What CI runs, on this machine, before pushing:
#   bash scripts/dev/check.sh            # Python and web
#   bash scripts/dev/check.sh --py       # Python only (ruff, format, pyright, pytest)
#   bash scripts/dev/check.sh --web      # web only (eslint, tsc, vitest)
#   bash scripts/dev/check.sh --visual   # also compare the page screenshots (needs Docker)
# Test output is cut to the summary and the failures.
set -euo pipefail
cd "$(dirname "$0")/../.."
py=1 web=1 visual=0
for a; do
  case "$a" in
    --py) web=0 ;;
    --web) py=0 ;;
    --visual) visual=1 ;;
    *) echo "check.sh: unknown option $a" >&2; exit 2 ;;
  esac
done
step() { printf '\n== %s\n' "$*"; }
# pnpm in CI; npm runs the same package.json scripts where pnpm isn't installed.
if command -v pnpm >/dev/null; then
  web() { pnpm -C apps/web -s "$@"; }
else
  web() { npm --prefix apps/web run -s "$@"; }
fi
# Postgres for the database tests (without it they skip, and the run proves less).
if docker info >/dev/null 2>&1; then
  docker compose up -d --wait db >/dev/null 2>&1 || echo "Couldn't start the db container" >&2
else
  echo "Docker isn't running: the database tests will be skipped" >&2
fi
if [ "$py" = 1 ]; then
  step ruff; uv run ruff check . -q
  step format; uv run ruff format --check . -q
  step pyright; uv run pyright 2>&1 | tail -n 3
  step pytest; uv run pytest -q 2>&1 | grep -vE '^SKIPPED|^[.sx]+( +\[|$)|^$' | tail -n 30
fi
if [ "$web" = 1 ]; then
  step eslint; web lint
  step tsc; web typecheck
  step vitest; web test 2>&1 | grep -E 'FAIL|✗|×|AssertionError|Error:|Test Files|Tests ' | head -n 40
fi
if [ "$visual" = 1 ]; then
  step visual
  docker info >/dev/null 2>&1 || { echo "Docker isn't running" >&2; exit 1; }
  docker compose up -d --build --quiet-pull >/dev/null 2>&1
  sh apps/web/scripts/visual.sh 2>&1 | tail -n 15
fi
step "all passed"

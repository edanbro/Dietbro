#!/bin/sh
# Compare every page with its screenshot in e2e/__screenshots__/ (e2e/visual.e2e.ts), or rewrite
# them with --update-snapshots. Runs in the Playwright Linux container so the pixels match CI on
# any machine. Needs the web app on port 3000 (docker compose up -d) and Clerk keys, from the
# environment or the repo's .env. The API isn't called: the test replays e2e/visual/api.har.
#
#   sh scripts/visual.sh                      # compare (make visual)
#   sh scripts/visual.sh --update-snapshots   # rewrite (make visual-update)
#   sh scripts/visual.sh --record             # re-record the API; needs the whole stack, seeded
#
# Differences are written to test-results-visual/ (expected, actual and diff images).
set -eu
cd "$(dirname "$0")/.."
IMAGE=mcr.microsoft.com/playwright:v1.64.0-noble

key() { # VALUE of KEY=VALUE in ../../.env, quotes removed
  [ -f ../../.env ] && grep -E "^$1=" ../../.env | head -n 1 | cut -d= -f2- | tr -d "\"'" || true
}
CLERK_SECRET_KEY=${CLERK_SECRET_KEY:-$(key CLERK_SECRET_KEY)}
CLERK_PUBLISHABLE_KEY=${CLERK_PUBLISHABLE_KEY:-$(key CLERK_PUBLISHABLE_KEY)}
export CLERK_SECRET_KEY CLERK_PUBLISHABLE_KEY
if [ -z "$CLERK_SECRET_KEY" ]; then
  echo "visual.sh: needs CLERK_SECRET_KEY (environment or .env)" >&2
  exit 1
fi

VISUAL_RECORD=
projects="--project=setup --project=visual-phone --project=visual-desktop"
if [ "${1:-}" = "--record" ]; then
  shift
  VISUAL_RECORD=1
  projects="--project=setup --project=visual-phone"
fi
export VISUAL_RECORD projects

# Updating rewrites every screenshot, not only those past the comparison's tolerance (a few
# small labels can stay under it, and the baselines would drift from the pages).
for a; do
  shift
  case "$a" in
    -u | --update-snapshots) set -- "$@" --update-snapshots=all ;;
    *) set -- "$@" "$a" ;;
  esac
done

rm -rf test-results-visual
# MSYS_NO_PATHCONV: Git Bash on Windows would otherwise rewrite the container paths.
MSYS_NO_PATHCONV=1 docker run --rm --ipc=host --add-host=host.docker.internal:host-gateway \
  -e CLERK_SECRET_KEY -e CLERK_PUBLISHABLE_KEY -e VISUAL=1 -e VISUAL_RECORD -e projects -e CI \
  -v "$(pwd):/web" "$IMAGE" sh -euc '
    mkdir -p /tmp/v && cd /tmp/v
    cp -r /web/e2e /web/playwright.config.ts .
    npm init -y > /dev/null
    npm install --no-audit --no-fund --loglevel=error \
      @playwright/test@1.64.0 @clerk/testing@2.2.44 @clerk/backend@3.23.1
    # The browser must see the app at localhost:3000 (its origin for Clerk and the API recording),
    # and a recording the API at localhost:8000, so pass those ports through to the host.
    node -e "for (const port of [3000, 8000]) require(\"net\").createServer((c) => {
      const s = require(\"net\").connect(port, \"host.docker.internal\");
      c.pipe(s).pipe(c); c.on(\"error\", () => s.destroy()); s.on(\"error\", () => c.destroy());
    }).listen(port)" &
    status=0
    npx playwright test $projects --reporter=list "$@" || status=$?
    if [ -d test-results ]; then cp -r test-results /web/test-results-visual; fi
    if [ -n "${VISUAL_RECORD:-}" ] && [ "$status" = 0 ]; then cp e2e/visual/* /web/e2e/visual/; fi
    case " $* " in *" --update-snapshots"*)
      rm -rf /web/e2e/__screenshots__ && cp -r e2e/__screenshots__ /web/e2e/ ;;
    esac
    exit $status
  ' visual "$@"

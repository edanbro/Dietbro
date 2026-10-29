#!/bin/sh
# Run a command against the local compose database, with DATABASE_URL taken from .env (only that
# key: sourcing the whole file breaks the API settings' cors_origins parse). The URL is never
# printed, so Claude Code can run benches while its permission rules keep it from reading .env.
#   sh scripts/dev/with-db.sh uv run larder-bench
#   sh scripts/dev/with-db.sh uv run larder-evals --catalog db --n 50
cd "$(dirname "$0")/../.."
url=$(grep -E '^DATABASE_URL=' .env | head -n 1 | cut -d= -f2- | tr -d "\"'" | sed 's/@db:/@localhost:/')
[ -n "$url" ] || { echo "with-db.sh: no DATABASE_URL in .env" >&2; exit 1; }
DATABASE_URL=$url exec "$@"

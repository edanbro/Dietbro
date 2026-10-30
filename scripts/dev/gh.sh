#!/bin/sh
# gh with git's stored GitHub credential, so no separate `gh auth login` is needed:
#   sh scripts/dev/gh.sh pr checks 66 --watch
#   sh scripts/dev/gh.sh run view --log-failed --job 123
GH=$(command -v gh || echo "/c/Program Files/GitHub CLI/gh.exe")
GH_TOKEN=$(sh "$(dirname "$0")/token.sh") exec "$GH" "$@"
